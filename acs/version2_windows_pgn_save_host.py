from __future__ import annotations

"""Background PGN Save/Save As composition for the current Windows file host.

This is a narrow successor layer over ``Version2WindowsStreamingFileActionDelegate``.
It reuses that delegate's single worker slot, generation fence, shutdown contract and
owner-thread poster. PGN serialization, destination fingerprinting and atomic file
publication remain owned by :mod:`acs.pgn_save_snapshot` and the canonical PGN writer.
No chess rules, PGN parser, serializer, or second executor live here.
"""

import logging
from pathlib import Path
import threading

from .pgn_document import PgnDocumentError, PgnDocumentErrorCode, PgnDocumentSession
from .pgn_save_snapshot import (
    PgnSaveCancelledError,
    PgnSaveMode,
    PgnSavePublication,
    PgnSaveSnapshot,
    capture_pgn_save_snapshot,
    commit_pgn_save_publication,
    expected_pgn_destination_sha256,
    publish_pgn_save_snapshot,
)
from .version2_windows_file_workflows import FileWorkflowEvent, FileWorkflowEventKind
from .version2_windows_pgn_streaming_host import Version2WindowsStreamingFileActionDelegate


_LOG = logging.getLogger(__name__)


class Version2WindowsSavingFileActionDelegate(Version2WindowsStreamingFileActionDelegate):
    """Keep PGN Save filesystem work off the Windows owner/UI thread."""

    @property
    def pgn_save_running(self) -> bool:
        with self._lock:
            return self._worker is not None and self._worker_kind == "pgn_save"

    def _busy_failure(self, action_id: str, previous_focus: str) -> FileWorkflowEvent | None:
        with self._lock:
            if self._shutdown_requested:
                return self._failed(
                    action_id,
                    "file_workflow_closed",
                    focus_target=previous_focus,
                )
            worker_kind = self._worker_kind if self._worker is not None else ""
        if not worker_kind:
            return None
        focus_target = previous_focus
        if worker_kind == "import":
            focus_target = "library-import-cancel"
        elif worker_kind == "pgn_open":
            focus_target = "pgn-open-cancel"
        return self._failed(
            action_id,
            "file_worker_busy",
            focus_target=focus_target,
        )

    def _save_pgn(self) -> FileWorkflowEvent | None:
        # Preserve the legacy synchronous seam for non-Windows/direct embeddings.
        if self._post_to_ui is None:
            return super()._save_pgn()

        previous_focus = self._focus()
        busy = self._busy_failure("pgn.save", previous_focus)
        if busy is not None:
            return busy

        current = self._session_or_failure("pgn.save")
        if isinstance(current, FileWorkflowEvent):
            return current
        try:
            snapshot = capture_pgn_save_snapshot(current, mode=PgnSaveMode.SAVE)
        except PgnDocumentError as exc:
            if exc.code in {
                PgnDocumentErrorCode.NO_SOURCE,
                PgnDocumentErrorCode.SOURCE_REQUIRES_SAVE_AS,
            }:
                return self._save_pgn_as(session=current, prior_focus=previous_focus)
            return self._failed(
                "pgn.save",
                "pgn_save_failed",
                focus_target=previous_focus,
            )
        except Exception:
            _LOG.warning("Version 2 PGN Save snapshot capture failed", exc_info=True)
            return self._failed(
                "pgn.save",
                "pgn_save_failed",
                focus_target=previous_focus,
            )
        return self._start_pgn_save_worker(
            action_id="pgn.save",
            session=current,
            snapshot=snapshot,
            destination=None,
            previous_focus=previous_focus,
        )

    def _save_pgn_as(
        self,
        *,
        session: PgnDocumentSession | None = None,
        prior_focus: str | None = None,
    ) -> FileWorkflowEvent | None:
        if self._post_to_ui is None:
            return super()._save_pgn_as(session=session, prior_focus=prior_focus)

        previous_focus = self._focus() if prior_focus is None else prior_focus
        busy = self._busy_failure("pgn.save_as", previous_focus)
        if busy is not None:
            return busy

        current: PgnDocumentSession | FileWorkflowEvent
        current = session if session is not None else self._session_or_failure("pgn.save_as")
        if isinstance(current, FileWorkflowEvent):
            return current
        try:
            view = current.view()
        except Exception:
            return self._failed(
                "pgn.save_as",
                "pgn_save_as_failed",
                focus_target=previous_focus,
            )
        suggested = "game.pgn"
        if view.source_path:
            suggested = Path(view.source_path).name or suggested

        try:
            destination = self._dialogs.save_pgn_as(suggested)
        except Exception:
            return self._failed(
                "pgn.save_as",
                "file_dialog_failed",
                focus_target=previous_focus,
            )
        if destination is None:
            return self._dialog_cancelled("pgn.save_as", previous_focus)

        # WinForms modal dialogs pump messages. Revalidate both document identity
        # and the one shared worker authority after the dialog returns.
        try:
            live_session = self._get_pgn_session()
        except Exception:
            return self._failed(
                "pgn.save_as",
                "pgn_session_unavailable",
                focus_target=previous_focus,
            )
        if live_session is not current:
            return self._failed(
                "pgn.save_as",
                "pgn_save_stale",
                focus_target=previous_focus,
            )
        busy = self._busy_failure("pgn.save_as", previous_focus)
        if busy is not None:
            return busy

        try:
            # Capture after the modal dialog so re-entrant edits made while it was
            # open are intentionally part of the generation the user saves.
            snapshot = capture_pgn_save_snapshot(current, mode=PgnSaveMode.SAVE_AS)
        except Exception:
            _LOG.warning("Version 2 PGN Save As snapshot capture failed", exc_info=True)
            return self._failed(
                "pgn.save_as",
                "pgn_save_as_failed",
                focus_target=previous_focus,
            )
        return self._start_pgn_save_worker(
            action_id="pgn.save_as",
            session=current,
            snapshot=snapshot,
            destination=Path(destination),
            previous_focus=previous_focus,
        )

    def _start_pgn_save_worker(
        self,
        *,
        action_id: str,
        session: PgnDocumentSession,
        snapshot: PgnSaveSnapshot,
        destination: Path | None,
        previous_focus: str,
    ) -> FileWorkflowEvent | None:
        with self._lock:
            if self._shutdown_requested:
                return self._failed(
                    action_id,
                    "file_workflow_closed",
                    focus_target=previous_focus,
                )
            if self._worker is not None:
                return self._failed(
                    action_id,
                    "file_worker_busy",
                    focus_target=previous_focus,
                )
            self._generation += 1
            generation = self._generation
            cancel_event = threading.Event()
            worker = threading.Thread(
                target=self._run_pgn_save,
                args=(
                    generation,
                    action_id,
                    session,
                    snapshot,
                    destination,
                    previous_focus,
                    cancel_event,
                ),
                name=f"AccessibleChess-V2-PgnSave-{generation}",
                daemon=False,
            )
            self._worker = worker
            self._worker_started = False
            self._worker_kind = "pgn_save"
            self._cancel_event = cancel_event
            self._terminal_pending = None

        shutdown_before_start = False
        try:
            with self._lock:
                if generation != self._generation or self._worker is not worker:
                    raise RuntimeError("PGN Save worker ownership changed before start")
                if self._shutdown_requested:
                    self._clear_worker_locked()
                    shutdown_before_start = True
                else:
                    worker.start()
                    if self._worker is worker:
                        self._worker_started = True
        except Exception:
            with self._lock:
                if generation == self._generation and self._worker is worker:
                    self._clear_worker_locked()
            return self._failed(
                action_id,
                "pgn_save_worker_unavailable",
                focus_target=previous_focus,
            )
        if shutdown_before_start:
            return self._failed(
                action_id,
                "file_workflow_closed",
                focus_target=previous_focus,
            )

        # The current FileWorkflowEvent enum has no truthful Save-start lifecycle
        # event. Do not announce a false "saved" state. Completion/error is queued
        # asynchronously through the owner UI mailbox; a dedicated start/cancel
        # presentation event is intentionally left to the follow-up UI slice.
        return None

    def _run_pgn_save(
        self,
        generation: int,
        action_id: str,
        session: PgnDocumentSession,
        snapshot: PgnSaveSnapshot,
        destination: Path | None,
        previous_focus: str,
        cancel_event: threading.Event,
    ) -> None:
        publication: PgnSavePublication | None = None
        error_code = ""
        try:
            if snapshot.mode is PgnSaveMode.SAVE_AS:
                if destination is None:
                    raise RuntimeError("Save As worker lost its destination")
                expected = expected_pgn_destination_sha256(
                    destination,
                    cancel_check=cancel_event.is_set,
                )
                publication = publish_pgn_save_snapshot(
                    snapshot,
                    path=destination,
                    overwrite=expected is not None,
                    expected_sha256=expected,
                    cancel_check=cancel_event.is_set,
                )
            else:
                publication = publish_pgn_save_snapshot(
                    snapshot,
                    cancel_check=cancel_event.is_set,
                )
        except PgnSaveCancelledError:
            error_code = "pgn_save_cancelled"
        except PgnDocumentError:
            error_code = "pgn_save_conflict"
        except Exception:
            _LOG.warning("Version 2 PGN Save publication failed", exc_info=True)
            error_code = "pgn_save_failed"

        def finish_on_owner() -> None:
            self._finish_pgn_save_on_owner(
                generation,
                action_id,
                session,
                snapshot,
                publication,
                error_code,
                previous_focus,
            )

        try:
            assert self._post_to_ui is not None
            self._post_to_ui(finish_on_owner)
        except Exception:
            _LOG.warning("Version 2 PGN Save UI publication post failed", exc_info=True)
            with self._lock:
                current = (
                    generation == self._generation
                    and self._worker_kind == "pgn_save"
                    and not self._shutdown_requested
                )
                if current:
                    self._clear_worker_locked()
            if current:
                self._emit(
                    FileWorkflowEvent(
                        FileWorkflowEventKind.FAILED,
                        action_id,
                        focus_target=previous_focus,
                        error_code="pgn_save_ui_post_failed",
                    )
                )

    def _finish_pgn_save_on_owner(
        self,
        generation: int,
        action_id: str,
        session: PgnDocumentSession,
        snapshot: PgnSaveSnapshot,
        publication: PgnSavePublication | None,
        error_code: str,
        previous_focus: str,
    ) -> None:
        with self._lock:
            current = (
                generation == self._generation
                and self._worker is not None
                and self._worker_kind == "pgn_save"
                and not self._shutdown_requested
            )
            if not current:
                return

        if error_code:
            terminal = FileWorkflowEvent(
                FileWorkflowEventKind.FAILED,
                action_id,
                focus_target=previous_focus,
                error_code=error_code,
            )
        elif publication is None:
            terminal = FileWorkflowEvent(
                FileWorkflowEventKind.FAILED,
                action_id,
                focus_target=previous_focus,
                error_code="pgn_save_failed",
            )
        else:
            try:
                live_session = self._get_pgn_session()
            except Exception:
                live_session = None
                terminal = FileWorkflowEvent(
                    FileWorkflowEventKind.FAILED,
                    action_id,
                    focus_target=previous_focus,
                    error_code="pgn_session_unavailable",
                )
            if live_session is not None:
                if live_session is not session:
                    terminal = FileWorkflowEvent(
                        FileWorkflowEventKind.FAILED,
                        action_id,
                        focus_target=previous_focus,
                        error_code="pgn_save_stale",
                    )
                else:
                    try:
                        committed = commit_pgn_save_publication(session, publication)
                    except Exception:
                        _LOG.warning("Version 2 PGN Save owner commit failed", exc_info=True)
                        terminal = FileWorkflowEvent(
                            FileWorkflowEventKind.FAILED,
                            action_id,
                            focus_target=previous_focus,
                            error_code="pgn_save_commit_failed",
                        )
                    else:
                        terminal = FileWorkflowEvent(
                            (
                                FileWorkflowEventKind.PGN_SAVED_AS
                                if snapshot.mode is PgnSaveMode.SAVE_AS
                                else FileWorkflowEventKind.PGN_SAVED
                            ),
                            action_id,
                            focus_target=previous_focus,
                            game_count=len(snapshot.games),
                        )
                        # ``committed`` is intentionally not used to derive the
                        # result kind: newer owner-thread edits may keep it dirty
                        # while this exact captured generation was durably saved.
                        _ = committed

        with self._lock:
            if (
                generation != self._generation
                or self._worker_kind != "pgn_save"
                or self._shutdown_requested
            ):
                return
            self._clear_worker_locked()
        self._emit_owner_async(terminal)

    def wait_for_pgn_save(self, timeout: float | None = None) -> bool:
        """Wait only for worker publication; owner commit may still be queued."""

        with self._lock:
            worker = self._worker if self._worker_kind == "pgn_save" else None
            worker_started = self._worker_started
        if worker is None:
            return True
        if not worker_started:
            return False
        worker.join(timeout)
        return not worker.is_alive()

    def shutdown(self, timeout: float | None = None) -> bool:
        with self._lock:
            save_worker = self._worker if self._worker_kind == "pgn_save" else None
        stopped = super().shutdown(timeout)
        if stopped and save_worker is not None:
            with self._lock:
                if self._worker is save_worker and self._worker_kind == "pgn_save":
                    # Shutdown makes queued owner publication stale before the UI
                    # pump closes. The canonical atomic writer itself has already
                    # either published or cancelled before this join completes.
                    self._clear_worker_locked()
        return stopped


__all__ = ["Version2WindowsSavingFileActionDelegate"]
