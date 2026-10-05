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
from .training_progress_store import (
    TrainingProgressDurabilityUnknownError,
    TrainingProgressStore,
)
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
        # Training provenance is bound to the canonical semantic BookReader.
        # Reject subclasses before any location/document navigation hook can run.
        if type(reader) is not BookReader:
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
        message_key: str | None = None,
    ) -> TrainingWebViewBridge:
        presenter = TrainingPresenter(
            session,
            language=self.language,
            message=message,
            message_key=message_key,
        )
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
        message_key: str | None = None,
    ) -> tuple[ExerciseSession, TrainingWebViewBridge, TrainingProgressStore, str | None]:
        store = self._store_for(material)
        loaded = store.load(material.definition)
        session = ExerciseSession(material.definition) if loaded is None else loaded.session
        revision = None if loaded is None else loaded.revision
        return (
            session,
            self._bridge_for(session, message=message, message_key=message_key),
            store,
            revision,
        )

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

    @property
    def presenter_message_key(self) -> str | None:
        if self.bridge is None:
            raise RuntimeError("no Training exercise is active")
        return self.bridge.projection.presenter_message_key

    def start_current(
        self,
        *,
        message: str = "",
        message_key: str | None = None,
    ) -> TrainingWebViewBridge:
        location = self.reader.location()
        try:
            material = build_current_book_training_material(self.reader)
        except Exception:
            # If mutable authoring drift caused material derivation to fail, expose
            # only the canonical revision boundary. If the indexed revision is
            # still valid, preserve the original domain/programming exception.
            self.reader.block_snapshot(location.index)
            raise
        # BookReader is bound to one immutable indexed revision. Revalidate the
        # live authoring document after Training material derivation so a mutable
        # BookDocument cannot change between the reader check and publication.
        self.reader.block_snapshot(location.index)
        session, bridge, store, revision = self._prepare(
            material,
            message=message,
            message_key=message_key,
        )
        # Durable Training load is an external I/O boundary. Revalidate once more
        # immediately before publishing the prepared session/bridge.
        self.reader.block_snapshot(location.index)
        self.material, self._session, self.bridge = material, session, bridge
        self._store, self._revision = store, revision
        return bridge

    def save(self) -> str:
        if self.material is None or self.bridge is None or self._store is None:
            raise RuntimeError("no Training exercise is active")
        # The store owns compare-and-swap authority even for byte-identical
        # snapshots. It can elide the physical rewrite only after confirming
        # under its peer lock that the expected durable revision still exists.
        try:
            revision = self._store.save(
                self.session,
                expected_revision=self._revision,
            )
        except TrainingProgressDurabilityUnknownError as error:
            # This error exists only after atomic publication returned success.
            # Never move the live session back to a pre-publication snapshot.
            # Bind to the just-published revision first, then prefer a validated
            # reread in case a non-cooperating writer changed canonical state
            # after our replace but before durability confirmation completed.
            self._revision = error.published_revision
            try:
                loaded = self._store.load(self.material.definition)
            except Exception as reconcile_error:
                raise TrainingProgressDurabilityUnknownError(
                    "training progress was published but canonical state could not be reloaded",
                    published_revision=error.published_revision,
                ) from reconcile_error
            if loaded is not None:
                self.bridge.projection.restore_state(
                    loaded.session.snapshot(),
                    language=self.language,
                    message="",
                    message_key=None,
                )
                self._revision = loaded.revision
            raise
        self._revision = revision
        return revision

    def _next_exercise_material(self) -> tuple[int, BookTrainingMaterial]:
        material = self.material
        if material is None:
            raise RuntimeError("no Training exercise is active")
        # Fail closed through BookReader before provenance code touches the mutable
        # live BookDocument. Authoring can temporarily make blocks malformed; that
        # must surface as canonical revision drift, never as an internal parser/
        # attribute exception on the Training/NVDA path.
        self.reader.block_snapshot(self.reader.index)
        indexed_document = self.reader.document_snapshot()
        try:
            current = resolve_book_training_origin(indexed_document, material.origin)
        except Exception:
            # Detached indexed provenance is stable; if the live authoring source
            # changed while this work ran, normalize through BookReader's canonical
            # revision boundary before exposing any implementation error.
            self.reader.block_snapshot(self.reader.index)
            raise
        self.reader.block_snapshot(current.index)
        for index in range(current.index + 1, len(indexed_document.blocks)):
            # The detached document is already bound to the indexed revision.
            # Revalidating the entire live book for every intervening prose block
            # makes Continue availability quadratic in book length. Traverse this
            # snapshot, then revalidate before returning any successor or result.
            block = indexed_document.blocks[index]
            if not isinstance(block, Exercise):
                continue
            try:
                candidate = build_book_training_material(indexed_document, index)
            except BookTrainingError:
                # Stable malformed material stays readable. Live authoring drift
                # is still rejected by the final whole-revision validation; no
                # intermediate candidate is published or changes the reader.
                continue
            except Exception:
                # Never leak implementation exceptions caused by concurrent
                # malformed authoring state before checking revision authority.
                self.reader.block_snapshot(index)
                raise
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
        next_index, material = self._next_exercise_material()
        # Validate the successor and its durable state before any persistence or
        # reader mutation. A stale/malformed next exercise must not rewrite the
        # already-durable completed origin merely because Continue was attempted.
        session, bridge, store, revision = self._prepare(material)
        self.save()
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
        # Normalize only exact, already-bounded browser text. Overlong
        # exact strings and all non-exact values go unchanged to the bridge,
        # whose boundary checks length/type before strip(). This workspace must
        # not execute subclass strip/equality hooks or scan an oversized command.
        command_id = (
            command.strip()
            if type(command) is str and len(command) <= 64
            else command
        )
        classifiable_command = type(command_id) is str and len(command_id) <= 64
        is_continue = classifiable_command and command_id == "training.continue"
        is_language = classifiable_command and command_id == "training.language"
        is_disabled_completed_action = classifiable_command and command_id in (
            "training.hint",
            "training.reveal",
            "training.retry",
        )
        if is_continue and not (
            self.session.completed and self.has_next()
        ):
            # Continue is disabled unless a completed exercise has a validated
            # successor. Enforce that same authority before the callback can save
            # current progress, so stale/forged WebView activation of a disabled
            # Continue control cannot perform durable I/O.
            return bridge.projection.generic_error()
        if self.session.completed and is_disabled_completed_action:
            # These controls are explicitly disabled in the canonical snapshot
            # after completion. Enforce the same boundary server-side so stale
            # DOM/native-menu activation cannot mutate transient feedback or
            # trigger a needless persistence write behind a disabled control.
            return bridge.projection.generic_error()
        before = self.session.snapshot()
        revision = self._revision
        before_session = self._session
        before_store = self._store
        before_reader_index = self.reader.index
        before_language = bridge.projection.language
        before_message = bridge.projection.presenter_message
        before_message_key = bridge.projection.presenter_message_key

        def restore_active_state() -> None:
            # Keep retained session/bridge references authoritative across
            # rejected browser commands, render failures and durable CAS errors.
            self.material = material
            self._session = before_session
            self.bridge = bridge
            self._store = before_store
            self._revision = revision
            self.language = before_language
            bridge.projection.restore_state(
                before,
                language=before_language,
                message=before_message,
                message_key=before_message_key,
            )

        def restore_continue_state() -> None:
            # Continue can move the canonical BookReader and replace every active
            # Training object before the next surface renders. Keep the workspace
            # independently atomic; callers must not need Version2Application to
            # repair a failed render/callback.
            if self.reader.index != before_reader_index:
                self.reader.go_to(before_reader_index)
            self.material = material
            self._session = before_session
            self.bridge = bridge
            self._store = before_store
            self._revision = revision
            self.language = before_language

        try:
            event = bridge.dispatch(command_id, payload)
        except Exception:
            if is_continue:
                restore_continue_state()
            else:
                # The bridge normally sanitizes projection failures. If the
                # sanitizing error projection itself raises after a presenter or
                # session mutation, restore the exact pre-command Training state
                # in place before allowing the outer application boundary to
                # sanitize it.
                restore_active_state()
            raise
        if is_continue:
            if event.kind == "error":
                restore_continue_state()
            return event
        if event.kind == "error":
            # Projection/render failures can happen after submit/hint/reset or
            # transient presenter state has already mutated. The bridge deliberately
            # converts those exceptions to a generic error, so restore the complete
            # pre-command Training surface in place instead of leaving memory ahead
            # of disk or invalidating retained session/bridge references.
            restore_active_state()
            # The bridge can construct its generic error after partially mutating
            # presentation state (notably a rejected language switch). We have
            # just restored the authoritative pre-command projection, so never
            # return an error localized from the rejected transient state.
            return bridge.projection.generic_error()
        after = self.session.snapshot()
        if after == before:
            # Presentation-only or semantically no-op commands must not depend on
            # durable storage. This also remains correct if future Book Training
            # content gains real hints: a changed hints_used counter will make the
            # snapshots differ and therefore take the durable write path below.
            if is_language:
                self.language = self.bridge.projection.language
            return event
        try:
            self.save()
        except TrainingProgressDurabilityUnknownError:
            # save() has already reconciled from canonical storage in place (or
            # retained the definitely-published state with its publication
            # revision when canonical reread failed). Never apply stale rollback.
            raise
        except Exception:
            # A pre-publication stale/busy/error write leaves durable truth at the
            # old revision, so rollback remains the correct transaction boundary.
            restore_active_state()
            raise
        return event

    def snapshot(self) -> dict[str, object] | None:
        return None if self.bridge is None else self.bridge.projection.snapshot()
