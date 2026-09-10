from __future__ import annotations

"""Version 2 Training composition over canonical Book/Training owners.

This module is an application collection/workspace only.  It does not parse
chess, decide answer correctness, or create a second training state model.
Exercises come exclusively from explicit semantic ``BookDocument.Exercise``
blocks and are converted by :mod:`acs.book_training`; canonical move legality and
session state remain owned by :mod:`acs.training`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path

from .book_training import BookTrainingError, BookTrainingMaterial, build_book_training_material
from .bookdocument import BookDocument, Exercise
from .full_product_presenters import TrainingPresenter
from .full_product_ui_shell import UILanguage
from .training import ExerciseSession
from .training_progress_store import TrainingProgressStore
from .training_webview_bridge import TrainingWebViewBridge
from .training_webview_projection import TrainingWebViewEvent, TrainingWebViewProjection


@dataclass(frozen=True, slots=True)
class Version2TrainingEntry:
    block_index: int
    material: BookTrainingMaterial


class Version2TrainingWorkspace:
    """Deterministic ordered Training journey for one immutable BookDocument."""

    def __init__(
        self,
        document: BookDocument,
        progress_root: str | Path,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not isinstance(document, BookDocument):
            raise TypeError("training workspace requires a BookDocument")
        if not isinstance(progress_root, (str, Path)):
            raise TypeError("training progress root must be a filesystem path")
        if not isinstance(language, UILanguage):
            raise TypeError("training workspace language must be UILanguage")

        self._document = document
        self._progress_root = Path(progress_root)
        self._language = language
        entries: list[Version2TrainingEntry] = []
        for index, block in enumerate(document.blocks):
            if not isinstance(block, Exercise):
                continue
            try:
                material = build_book_training_material(document, index)
            except BookTrainingError:
                # An explicit semantic Exercise may still be readable book content
                # without being a valid canonical training exercise.  Never infer
                # or repair missing chess semantics here.
                continue
            entries.append(Version2TrainingEntry(index, material))
        self._entries = tuple(entries)
        self._index = -1
        self._store: TrainingProgressStore | None = None
        self._revision: str | None = None
        self._session: ExerciseSession | None = None
        self._presenter: TrainingPresenter | None = None
        self._projection: TrainingWebViewProjection | None = None
        self._bridge: TrainingWebViewBridge | None = None
        if self._entries:
            self._activate(0)

    @property
    def available(self) -> bool:
        return bool(self._entries)

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def current_block_index(self) -> int | None:
        if self._index < 0:
            return None
        return self._entries[self._index].block_index

    def _progress_path(self, exercise_id: str) -> Path:
        digest = hashlib.sha256(exercise_id.encode("utf-8")).hexdigest()
        return self._progress_root / f"{digest}.json"

    def _activate(self, index: int) -> None:
        if not 0 <= index < len(self._entries):
            raise IndexError("training exercise index is outside the collection")
        definition = self._entries[index].material.definition
        store = TrainingProgressStore(self._progress_path(definition.exercise_id))
        loaded = store.load(definition)
        session = loaded.session if loaded is not None else ExerciseSession(definition)
        revision = loaded.revision if loaded is not None else None
        presenter = TrainingPresenter(session, language=self._language)
        projection = TrainingWebViewProjection(presenter, language=self._language)
        bridge = TrainingWebViewBridge(projection)
        self._index = index
        self._store = store
        self._revision = revision
        self._session = session
        self._presenter = presenter
        self._projection = projection
        self._bridge = bridge

    def _require_active(self) -> tuple[TrainingProgressStore, ExerciseSession, TrainingWebViewProjection, TrainingWebViewBridge]:
        if self._store is None or self._session is None or self._projection is None or self._bridge is None:
            raise LookupError("no canonical training exercise is available")
        return self._store, self._session, self._projection, self._bridge

    def _save(self) -> None:
        store, session, _projection, _bridge = self._require_active()
        self._revision = store.save(session, expected_revision=self._revision)

    def _rebuild_from_snapshot(self, snapshot: Mapping[str, object]) -> None:
        if self._index < 0:
            raise LookupError("no canonical training exercise is available")
        definition = self._entries[self._index].material.definition
        session = ExerciseSession.restore(definition, snapshot)
        presenter = TrainingPresenter(session, language=self._language)
        projection = TrainingWebViewProjection(presenter, language=self._language)
        self._session = session
        self._presenter = presenter
        self._projection = projection
        self._bridge = TrainingWebViewBridge(projection)

    def _snapshot_with_continuation(self) -> dict[str, object]:
        _store, session, projection, _bridge = self._require_active()
        snapshot = projection.snapshot()
        actions = list(snapshot.get("actions", ()))
        if session.completed and self._index + 1 < len(self._entries):
            label = "Наступна вправа" if self._language is UILanguage.UA else "Next exercise"
            actions.append({"command": "training.next", "label": label, "enabled": True})
        snapshot["actions"] = tuple(actions)
        snapshot["collection"] = {
            "index": self._index + 1,
            "total": len(self._entries),
            "has_next": self._index + 1 < len(self._entries),
        }
        return snapshot

    def snapshot(self) -> dict[str, object]:
        return self._snapshot_with_continuation()

    def set_language(self, language: UILanguage) -> None:
        if not isinstance(language, UILanguage):
            raise TypeError("training workspace language must be UILanguage")
        self._language = language
        if self._presenter is not None and self._projection is not None:
            self._presenter.set_language(language)
            self._projection.set_language(language)

    def _render_current(self, *, announcement: str = "", focus_target: str = "training-answer") -> TrainingWebViewEvent:
        return TrainingWebViewEvent(
            "render",
            {
                "snapshot": self._snapshot_with_continuation(),
                "focus_target": focus_target,
                "announcement": announcement,
                "clear_answer": True,
                "solution": (),
            },
        )

    def dispatch(
        self,
        command: object,
        payload: Mapping[str, object] | None = None,
    ) -> TrainingWebViewEvent:
        store, session, _projection, bridge = self._require_active()
        command_id = command.strip() if isinstance(command, str) else ""
        data = {} if payload is None else payload
        if not isinstance(data, Mapping):
            raise TypeError("training command payload must be a mapping")

        if command_id == "training.next":
            if data:
                raise ValueError("training next accepts no payload")
            if not session.completed:
                raise ValueError("complete the current exercise before continuing")
            if self._index + 1 >= len(self._entries):
                raise LookupError("there is no next training exercise")
            self._save()
            self._activate(self._index + 1)
            message = "Наступна вправа." if self._language is UILanguage.UA else "Next exercise."
            return self._render_current(announcement=message)

        before = session.snapshot()
        event = bridge.dispatch(command_id, data)
        if event.kind == "error":
            return event
        if command_id in {"training.submit", "training.hint", "training.reset"}:
            try:
                self._revision = store.save(session, expected_revision=self._revision)
            except Exception:
                self._rebuild_from_snapshot(before)
                raise
        if event.kind == "render":
            rendered = dict(event.payload)
            rendered["snapshot"] = self._snapshot_with_continuation()
            return TrainingWebViewEvent("render", rendered)
        return event


__all__ = ["Version2TrainingEntry", "Version2TrainingWorkspace"]
