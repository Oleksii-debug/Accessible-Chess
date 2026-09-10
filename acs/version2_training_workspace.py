from __future__ import annotations

"""Bounded V2 composition from semantic Book exercises to canonical Training.

This module owns no chess or exercise correctness.  It composes the existing
BookDocument -> Training provenance bridge, ExerciseSession/TrainingPresenter,
strict WebView projection, and atomic TrainingProgressStore.  Per-exercise file
names are SHA-256 digests of the already-canonical exercise identity so source
paths and authored identifiers never become filesystem names or browser state.
"""

import hashlib
from pathlib import Path
from collections.abc import Mapping

from .book_training import (
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
        self._store: TrainingProgressStore | None = None
        self._revision: str | None = None

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
        )
        return TrainingWebViewBridge(
            projection,
            continue_callback=self.continue_next,
        )

    def _prepare(
        self,
        material: BookTrainingMaterial,
    ) -> tuple[TrainingWebViewBridge, TrainingProgressStore, str | None]:
        store = self._store_for(material)
        loaded = store.load(material.definition)
        session = ExerciseSession(material.definition) if loaded is None else loaded.session
        revision = None if loaded is None else loaded.revision
        return self._bridge_for(session), store, revision

    @property
    def session(self) -> ExerciseSession:
        bridge = self.bridge
        if bridge is None:
            raise RuntimeError("no Training exercise is active")
        return bridge.projection._presenter.session

    def start_current(self) -> TrainingWebViewBridge:
        material = build_current_book_training_material(self.reader)
        bridge, store, revision = self._prepare(material)
        self.material, self.bridge = material, bridge
        self._store, self._revision = store, revision
        return bridge

    def save(self) -> str:
        if self.material is None or self.bridge is None or self._store is None:
            raise RuntimeError("no Training exercise is active")
        revision = self._store.save(self.session, expected_revision=self._revision)
        self._revision = revision
        return revision

    def _next_exercise_index(self) -> int:
        material = self.material
        if material is None:
            raise RuntimeError("no Training exercise is active")
        current = resolve_book_training_origin(self.reader.document, material.origin)
        for index in range(current.index + 1, len(self.reader.document.blocks)):
            if isinstance(self.reader.document.blocks[index], Exercise):
                return index
        raise LookupError("no next Training exercise")

    def has_next(self) -> bool:
        try:
            self._next_exercise_index()
        except (LookupError, RuntimeError, ValueError):
            return False
        return True

    def continue_next(self) -> TrainingWebViewEvent:
        if not self.session.completed:
            raise ValueError("current Training exercise is not complete")
        self.save()
        next_index = self._next_exercise_index()
        # Validate the next semantic exercise and its durable state before moving
        # the BookReader or replacing the active Training surface.
        material = build_book_training_material(self.reader.document, next_index)
        bridge, store, revision = self._prepare(material)
        self.reader.go_to(next_index)
        self.material, self.bridge = material, bridge
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
        before = self.session.snapshot()
        revision = self._revision
        event = bridge.dispatch(command, payload)
        if event.kind == "error" or command == "training.continue":
            return event
        try:
            self.save()
        except Exception:
            # A stale/busy durable write must not leave in-memory progress ahead
            # of disk truth. Restore the exact pre-command canonical session.
            restored = ExerciseSession.restore(material.definition, before)
            self.bridge = self._bridge_for(restored)
            self._revision = revision
            raise
        return event

    def snapshot(self) -> dict[str, object] | None:
        return None if self.bridge is None else self.bridge.projection.snapshot()
