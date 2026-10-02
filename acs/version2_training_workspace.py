from __future__ import annotations

"""Bounded V2 composition from semantic Book exercises to canonical Training.

This module owns no chess or exercise correctness. It composes the existing
BookDocument -> Training provenance bridge, ExerciseSession/TrainingPresenter,
strict WebView projection, atomic TrainingProgressStore, and a secondary local
mastery ledger. Training progress is always authoritative: a mastery-store
failure never rolls back a correct exercise answer.

Per-exercise file names are SHA-256 digests of the already-canonical exercise
identity so source paths and authored identifiers never become filesystem names
or browser state. Mastery completion identity is derived from the exact durable
Training revision so a restart can reconcile a completion without awarding it
twice.
"""

from collections.abc import Mapping
from datetime import date, datetime
import hashlib
from pathlib import Path

from .book_training import (
    BookTrainingError,
    BookTrainingMaterial,
    build_book_training_material,
    build_current_book_training_material,
    resolve_book_training_origin,
)
from .bookdocument import Exercise
from .bookreader import BookReader
from .full_product_presenters import TrainingPresenter
from .full_product_ui_shell import UILanguage
from .learning_mastery import (
    LearningMode,
    MasteryError,
    MasteryState,
    record_training_outcome,
)
from .learning_mastery_store import (
    MasteryStore,
    MasteryStoreBusyError,
    MasteryStoreConflictError,
)
from .learning_mastery_training import outcome_from_completed_training
from .training import ExerciseSession
from .training_progress_store import TrainingProgressStore
from .training_webview_bridge import TrainingWebViewBridge
from .training_webview_projection import TrainingWebViewEvent, TrainingWebViewProjection


_MASTERY_LABELS = {
    UILanguage.UA: {
        "heading": "Майстерність",
        "mode": "Режим",
        "adult": "Дорослий",
        "child": "Дитячий",
        "level": "Рівень",
        "points": "Очки майстерності",
        "streak": "Поточна серія днів",
        "best_streak": "Найкраща серія днів",
        "completed": "Завершені вправи",
        "achievements": "Досягнення",
        "pending": "Збереження майстерності буде повторено локально.",
        "unavailable": "Локальні дані майстерності недоступні; прогрес вправи збережено окремо.",
        "first_completion": "Перша завершена вправа",
        "practice_streak_7": "Серія практики 7 днів",
        "mastery_1000": "1000 очок майстерності",
        "perfect_10": "10 вправ без помилок і підказок",
    },
    UILanguage.EN: {
        "heading": "Mastery",
        "mode": "Mode",
        "adult": "Adult",
        "child": "Child",
        "level": "Level",
        "points": "Mastery points",
        "streak": "Current practice-day streak",
        "best_streak": "Best practice-day streak",
        "completed": "Completed exercises",
        "achievements": "Achievements",
        "pending": "Mastery save will be retried locally.",
        "unavailable": "Local mastery data is unavailable; exercise progress is stored separately.",
        "first_completion": "First completed exercise",
        "practice_streak_7": "Seven-day practice streak",
        "mastery_1000": "1000 mastery points",
        "perfect_10": "10 exercises without mistakes or hints",
    },
}


class Version2BookTrainingWorkspace:
    """One current Book exercise plus deterministic next-exercise continuation."""

    def __init__(
        self,
        reader: BookReader,
        *,
        progress_root: str | Path,
        language: UILanguage = UILanguage.UA,
        mastery_mode: LearningMode = LearningMode.ADULT,
    ) -> None:
        if not isinstance(reader, BookReader):
            raise TypeError("reader must be BookReader")
        if not isinstance(progress_root, (str, Path)):
            raise TypeError("progress_root must be a filesystem path")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        if not isinstance(mastery_mode, LearningMode):
            raise TypeError("mastery_mode must be LearningMode")
        self.reader = reader
        self.progress_root = Path(progress_root)
        self.language = language
        self.material: BookTrainingMaterial | None = None
        self.bridge: TrainingWebViewBridge | None = None
        self._session: ExerciseSession | None = None
        self._store: TrainingProgressStore | None = None
        self._revision: str | None = None

        # Keep mastery outside the per-exercise *.json namespace used by current
        # Training progress and tests. It is a secondary local ledger only.
        self._mastery_store = MasteryStore(
            self.progress_root / ".mastery" / "state.json"
        )
        self._mastery_default_mode = mastery_mode
        self._mastery_state: MasteryState | None = None
        self._mastery_revision: str | None = None
        self._mastery_pending = False
        self._mastery_unavailable = False

    @staticmethod
    def _exercise_filename(material: BookTrainingMaterial) -> str:
        token = hashlib.sha256(material.definition.exercise_id.encode("utf-8")).hexdigest()
        return token + ".json"

    def _store_for(self, material: BookTrainingMaterial) -> TrainingProgressStore:
        return TrainingProgressStore(self.progress_root / self._exercise_filename(material))

    def _bridge_for(self, session: ExerciseSession) -> TrainingWebViewBridge:
        presenter = TrainingPresenter(session, language=self.language)
        projection = TrainingWebViewProjection(
            presenter,
            language=self.language,
            can_continue=self.has_next,
            mastery_snapshot=self._mastery_summary,
        )
        return TrainingWebViewBridge(
            projection,
            continue_callback=self.continue_next,
        )

    def _prepare(
        self,
        material: BookTrainingMaterial,
    ) -> tuple[ExerciseSession, TrainingWebViewBridge, TrainingProgressStore, str | None]:
        store = self._store_for(material)
        loaded = store.load(material.definition)
        session = ExerciseSession(material.definition) if loaded is None else loaded.session
        revision = None if loaded is None else loaded.revision
        return session, self._bridge_for(session), store, revision

    @property
    def session(self) -> ExerciseSession:
        if self._session is None:
            raise RuntimeError("no Training exercise is active")
        return self._session

    @property
    def mastery_state(self) -> MasteryState | None:
        return self._mastery_state

    def _load_mastery(self) -> None:
        try:
            loaded = self._mastery_store.load()
        except (ValueError, OSError):
            # Never overwrite a corrupt/redirected mastery store with a fresh
            # ledger. Training remains usable and its own durable state remains
            # authoritative.
            self._mastery_state = None
            self._mastery_revision = None
            self._mastery_unavailable = True
            self._mastery_pending = False
            return
        self._mastery_state = (
            MasteryState.empty(self._mastery_default_mode)
            if loaded is None
            else loaded.state
        )
        self._mastery_revision = None if loaded is None else loaded.revision
        self._mastery_unavailable = False
        self._mastery_pending = False

    @staticmethod
    def _mastery_event_id(
        material: BookTrainingMaterial,
        training_revision: str,
    ) -> str:
        payload = (
            "v1\0"
            + material.definition.exercise_id
            + "\0"
            + training_revision
        ).encode("utf-8")
        return "completion:" + hashlib.sha256(payload).hexdigest()[:48]

    def _completion_practice_date(self) -> str:
        store = self._store
        if store is None:
            return date.today().isoformat()
        try:
            when = datetime.fromtimestamp(store.path.stat().st_mtime).date()
        except (OSError, OverflowError, ValueError):
            when = date.today()
        candidate = when.isoformat()
        state = self._mastery_state
        if state is not None and state.last_practice_date is not None:
            # Recovery of a missed older completion must not move the global
            # practice ledger backwards after newer activity was recorded.
            candidate = max(candidate, state.last_practice_date)
        return candidate

    def _reconcile_mastery_completion(self) -> None:
        material = self.material
        training_revision = self._revision
        if (
            material is None
            or training_revision is None
            or not self.session.completed
            or self._mastery_unavailable
        ):
            return
        if self._mastery_state is None:
            self._load_mastery()
        if self._mastery_state is None:
            return

        event_id = self._mastery_event_id(material, training_revision)
        for _attempt in range(2):
            state = self._mastery_state
            if state is None:
                return
            if any(item.event_id == event_id for item in state.activity_events):
                self._mastery_pending = False
                return

            try:
                outcome = outcome_from_completed_training(
                    self.session,
                    sequence=state.revision + 1,
                    event_id=event_id,
                    practice_date=self._completion_practice_date(),
                    duration_seconds=0,
                )
                update = record_training_outcome(state, outcome)
            except (MasteryError, ValueError):
                self._mastery_pending = True
                return

            if update.duplicate_retry:
                self._mastery_state = update.state
                self._mastery_pending = False
                return

            try:
                revision = self._mastery_store.save(
                    update.state,
                    expected_revision=self._mastery_revision,
                )
            except MasteryStoreBusyError:
                self._mastery_pending = True
                return
            except MasteryStoreConflictError:
                try:
                    loaded = self._mastery_store.load()
                except (ValueError, OSError):
                    self._mastery_state = None
                    self._mastery_revision = None
                    self._mastery_unavailable = True
                    self._mastery_pending = False
                    return
                self._mastery_state = (
                    MasteryState.empty(self._mastery_default_mode)
                    if loaded is None
                    else loaded.state
                )
                self._mastery_revision = None if loaded is None else loaded.revision
                continue
            except (ValueError, OSError):
                self._mastery_pending = True
                return

            self._mastery_state = update.state
            self._mastery_revision = revision
            self._mastery_pending = False
            return

        self._mastery_pending = True

    def _mastery_summary(self) -> dict[str, object]:
        language = self.language
        labels = _MASTERY_LABELS[language]
        state = self._mastery_state
        if self._mastery_unavailable or state is None:
            return {
                "heading": labels["heading"],
                "available": False,
                "status": labels["unavailable"],
            }

        achievements = tuple(
            labels.get(token, token) for token in state.achievements
        )
        status = labels["pending"] if self._mastery_pending else ""
        return {
            "heading": labels["heading"],
            "available": True,
            "status": status,
            "mode_label": labels["mode"],
            "mode": labels[state.mode.value],
            "level_label": labels["level"],
            "level": state.level,
            "points_label": labels["points"],
            "points": state.total_points,
            "streak_label": labels["streak"],
            "streak": state.current_streak,
            "best_streak_label": labels["best_streak"],
            "best_streak": state.best_streak,
            "completed_label": labels["completed"],
            "completed": state.completed_count,
            "achievements_label": labels["achievements"],
            "achievements": achievements,
        }

    def _decorate_event(self, event: TrainingWebViewEvent) -> TrainingWebViewEvent:
        if event.kind != "render":
            return event
        payload = dict(event.payload)
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, Mapping):
            return event
        updated_snapshot = dict(snapshot)
        updated_snapshot["mastery"] = self._mastery_summary()
        payload["snapshot"] = updated_snapshot
        return TrainingWebViewEvent(event.kind, payload)

    def start_current(self) -> TrainingWebViewBridge:
        material = build_current_book_training_material(self.reader)
        session, bridge, store, revision = self._prepare(material)
        self.material, self._session, self.bridge = material, session, bridge
        self._store, self._revision = store, revision
        self._load_mastery()
        if session.completed:
            self._reconcile_mastery_completion()
        return bridge

    def save(self) -> str:
        if self.material is None or self.bridge is None or self._store is None:
            raise RuntimeError("no Training exercise is active")
        revision = self._store.save(self.session, expected_revision=self._revision)
        self._revision = revision
        return revision

    def _next_exercise_material(self) -> tuple[int, BookTrainingMaterial]:
        material = self.material
        if material is None:
            raise RuntimeError("no Training exercise is active")
        current = resolve_book_training_origin(self.reader.document, material.origin)
        for index in range(current.index + 1, len(self.reader.document.blocks)):
            if not isinstance(self.reader.document.blocks[index], Exercise):
                continue
            try:
                candidate = build_book_training_material(self.reader.document, index)
            except BookTrainingError:
                # Keep malformed authored chess content readable as a Book block,
                # but never advertise or fabricate it as a Training exercise.
                continue
            return index, candidate
        raise LookupError("no next valid Training exercise")

    def has_next(self) -> bool:
        try:
            self._next_exercise_material()
        except (LookupError, RuntimeError, ValueError):
            return False
        return True

    def continue_next(self) -> TrainingWebViewEvent:
        if not self.session.completed:
            raise ValueError("current Training exercise is not complete")
        self.save()
        self._reconcile_mastery_completion()
        next_index, material = self._next_exercise_material()
        # Validate the next semantic exercise and its durable state before moving
        # the BookReader or replacing the active Training surface.
        session, bridge, store, revision = self._prepare(material)
        self.reader.go_to(next_index)
        self.material, self._session, self.bridge = material, session, bridge
        self._store, self._revision = store, revision
        return self._decorate_event(bridge.projection.retry())

    def dispatch(
        self,
        command: object,
        payload: Mapping[str, object] | None = None,
    ) -> TrainingWebViewEvent:
        bridge = self.bridge
        material = self.material
        if bridge is None or material is None:
            raise RuntimeError("no Training exercise is active")
        before = self.session.snapshot()
        revision = self._revision
        event = bridge.dispatch(command, payload)
        if event.kind == "error":
            return event
        if command == "training.continue":
            return self._decorate_event(event)
        try:
            self.save()
        except Exception:
            # A stale/busy durable Training write must not leave in-memory
            # exercise progress ahead of disk truth. Mastery reconciliation is
            # intentionally after this canonical Training publication.
            restored = ExerciseSession.restore(material.definition, before)
            self._session = restored
            self.bridge = self._bridge_for(restored)
            self._revision = revision
            raise

        if command == "training.language" and payload is not None:
            raw_language = payload.get("language")
            if isinstance(raw_language, str):
                try:
                    self.language = UILanguage(raw_language.strip().lower())
                except ValueError:
                    pass

        if self.session.completed:
            self._reconcile_mastery_completion()
        return self._decorate_event(event)

    def snapshot(self) -> dict[str, object] | None:
        if self.bridge is None:
            return None
        snapshot = self.bridge.projection.snapshot()
        snapshot["mastery"] = self._mastery_summary()
        return snapshot
