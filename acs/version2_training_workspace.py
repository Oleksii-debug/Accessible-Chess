from __future__ import annotations

"""Bounded V2 composition from semantic Book exercises to canonical Training.

This module owns no chess or exercise correctness. It composes the existing
BookDocument -> Training provenance bridge, ExerciseSession/TrainingPresenter,
strict WebView projection, and atomic TrainingProgressStore. Per-exercise file
names are SHA-256 digests of the already-canonical exercise identity so source
paths and authored identifiers never become filesystem names or browser state.
"""

from collections.abc import Mapping
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
from .training import ExerciseSession
from .training_progress_store import TrainingProgressStore
from .training_webview_bridge import TrainingWebViewBridge
from .training_webview_projection import TrainingWebViewEvent, TrainingWebViewProjection


class Version2BookTrainingWorkspace:
    """One current Book exercise plus deterministic next-exercise continuation."""

    def __init__(
        self,
        reader: BookReader,
        *,
        progress_root: str | Path,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not isinstance(reader, BookReader):
            raise TypeError("reader must be BookReader")
        if not isinstance(progress_root, (str, Path)):
            raise TypeError("progress_root must be a filesystem path")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self.reader = reader
        self.progress_root = Path(progress_root)
        self.language = language
        self.material: BookTrainingMaterial | None = None
        self.bridge: TrainingWebViewBridge | None = None
        self._session: ExerciseSession | None = None
        self._store: TrainingProgressStore | None = None
        self._revision: str | None = None

    @staticmethod
    def _exercise_filename(material: BookTrainingMaterial) -> str:
        token = hashlib.sha256(material.definition.exercise_id.encode("utf-8")).hexdigest()
        return token + ".json"

    def _store_for(self, material: BookTrainingMaterial) -> TrainingProgressStore:
        return TrainingProgressStore(self.progress_root / self._exercise_filename(material))

    def _bridge_for(
        self,
        session: ExerciseSession,
        *,
        message: str = "",
    ) -> TrainingWebViewBridge:
        presenter = TrainingPresenter(session, language=self.language, message=message)
        projection = TrainingWebViewProjection(
            presenter,
            language=self.language,
            can_continue=self.has_next,
        )
        return TrainingWebViewBridge(
            projection,
            continue_callback=self.continue_next,
        )

    def _prepare(
        self,
        material: BookTrainingMaterial,
        *,
        message: str = "",
    ) -> tuple[ExerciseSession, TrainingWebViewBridge, TrainingProgressStore, str | None]:
        store = self._store_for(material)
        loaded = store.load(material.definition)
        session = ExerciseSession(material.definition) if loaded is None else loaded.session
        revision = None if loaded is None else loaded.revision
        return session, self._bridge_for(session, message=message), store, revision

    @property
    def session(self) -> ExerciseSession:
        if self._session is None:
            raise RuntimeError("no Training exercise is active")
        return self._session

    @property
    def presenter_message(self) -> str:
        if self.bridge is None:
            raise RuntimeError("no Training exercise is active")
        return self.bridge.projection.presenter_message

    def start_current(self, *, message: str = "") -> TrainingWebViewBridge:
        location = self.reader.location()
        material = build_current_book_training_material(self.reader)
        # BookReader is bound to one immutable indexed revision. Revalidate the
        # live authoring document after Training material derivation so a mutable
        # BookDocument cannot change between the reader check and publication.
        self.reader.block_snapshot(location.index)
        session, bridge, store, revision = self._prepare(material, message=message)
        # Durable Training load is an external I/O boundary. Revalidate once more
        # immediately before publishing the prepared session/bridge.
        self.reader.block_snapshot(location.index)
        self.material, self._session, self.bridge = material, session, bridge
        self._store, self._revision = store, revision
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
        # resolve_book_training_origin() operates on BookDocument for provenance
        # compatibility. Immediately cross-check through BookReader's detached
        # indexed revision before scanning or publishing any successor.
        self.reader.block_snapshot(current.index)
        upper_bound = len(self.reader.document.blocks)
        for index in range(current.index + 1, upper_bound):
            block = self.reader.block_snapshot(index)
            if not isinstance(block, Exercise):
                continue
            try:
                candidate = build_book_training_material(self.reader.document, index)
            except BookTrainingError:
                # Keep malformed authored chess content readable as a Book block,
                # but never advertise or fabricate it as a Training exercise.
                continue
            # The material builder consumes the mutable BookDocument. Revalidate
            # the whole indexed revision after derivation so a concurrent/in-place
            # authoring mutation cannot become the next Training publication.
            self.reader.block_snapshot(index)
            return index, candidate
        # Also validate an empty/exhausted scan: the live list could have changed
        # after upper_bound was read and otherwise be misreported as "no next".
        self.reader.block_snapshot(current.index)
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
        next_index, material = self._next_exercise_material()
        # Validate the next semantic exercise and its durable state before moving
        # the BookReader or replacing the active Training surface.
        session, bridge, store, revision = self._prepare(material)
        self.reader.go_to(next_index)
        self.material, self._session, self.bridge = material, session, bridge
        self._store, self._revision = store, revision
        return bridge.projection.retry()

    def dispatch(
        self,
        command: object,
        payload: Mapping[str, object] | None = None,
    ) -> TrainingWebViewEvent:
        bridge = self.bridge
        material = self.material
        if bridge is None or material is None:
            raise RuntimeError("no Training exercise is active")
        if command == "training.continue" and not (
            self.session.completed and self.has_next()
        ):
            # Continue is disabled unless a completed exercise has a validated
            # successor. Enforce that same authority before the callback can save
            # current progress, so stale/forged WebView activation of a disabled
            # Continue control cannot perform durable I/O.
            return bridge.projection.generic_error()
        if (
            self.session.completed
            and command in ("training.hint", "training.reveal", "training.retry")
        ):
            # These controls are explicitly disabled in the canonical snapshot
            # after completion. Enforce the same boundary server-side so stale
            # DOM/native-menu activation cannot mutate transient feedback or
            # trigger a needless persistence write behind a disabled control.
            return bridge.projection.generic_error()
        before = self.session.snapshot()
        revision = self._revision
        before_language = bridge.projection.language
        before_message = bridge.projection.presenter_message
        try:
            event = bridge.dispatch(command, payload)
        except Exception:
            if command != "training.continue":
                # The bridge normally sanitizes projection failures. If the
                # sanitizing error projection itself raises after a presenter or
                # session mutation, restore the exact pre-command Training state
                # before allowing the outer application boundary to sanitize it.
                restored = ExerciseSession.restore(material.definition, before)
                self._session = restored
                self.language = before_language
                self.bridge = self._bridge_for(restored, message=before_message)
                self._revision = revision
            raise
        if command == "training.continue":
            return event
        if event.kind == "error":
            # Projection/render failures can happen after submit/hint/reset or
            # transient presenter state has already mutated. The bridge deliberately
            # converts those exceptions to a generic error, so restore the complete
            # pre-command Training surface instead of leaving memory ahead of disk.
            restored = ExerciseSession.restore(material.definition, before)
            self._session = restored
            self.language = before_language
            self.bridge = self._bridge_for(restored, message=before_message)
            self._revision = revision
            # The bridge can construct its generic error after partially mutating
            # presentation state (notably a rejected language switch). We have
            # just restored the authoritative pre-command projection, so never
            # return an error localized from the rejected transient state.
            return self.bridge.projection.generic_error()
        try:
            self.save()
        except Exception:
            # A stale/busy durable write must not leave in-memory progress ahead
            # of disk truth. Restore the exact pre-command canonical session and
            # presentation language.
            restored = ExerciseSession.restore(material.definition, before)
            self._session = restored
            self.language = before_language
            self.bridge = self._bridge_for(restored, message=before_message)
            self._revision = revision
            raise
        if command == "training.language":
            self.language = self.bridge.projection.language
        return event

    def snapshot(self) -> dict[str, object] | None:
        return None if self.bridge is None else self.bridge.projection.snapshot()
