from __future__ import annotations

"""Thread-safe host handoff for asynchronous Version 2 file-workflow events.

``Version2WindowsFileActionDelegate`` returns user-invoked file-action status on
the UI thread, but long Library imports also emit progress/terminal events from a
worker thread.  A WebView/NVDA projection must not be called from that worker.

This mailbox is deliberately presentation-neutral: UI-thread events are left to
the synchronous command caller, while worker-thread import events are queued for
later draining by the captured UI thread.  Progress is coalesced to the newest
count so a fast import cannot create background live-region spam or unbounded
memory growth.  No chess, PGN, Library, ChessBase, or projection semantics live
here.
"""

from collections import deque
import threading

from .version2_windows_file_workflows import FileWorkflowEvent, FileWorkflowEventKind


_ASYNC_IMPORT_KINDS = frozenset(
    {
        FileWorkflowEventKind.IMPORT_STARTED,
        FileWorkflowEventKind.IMPORT_PROGRESS,
        FileWorkflowEventKind.IMPORT_CANCELLING,
        FileWorkflowEventKind.IMPORT_COMPLETED,
        FileWorkflowEventKind.IMPORT_CANCELLED,
        FileWorkflowEventKind.IMPORT_EMPTY,
        FileWorkflowEventKind.FAILED,
    }
)
_IMPORT_ACTION_IDS = frozenset({"library.import", "library.cancel_import"})
_ASYNC_PGN_OPEN_KINDS = frozenset(
    {
        FileWorkflowEventKind.PGN_OPENED,
        FileWorkflowEventKind.PGN_OPEN_CANCELLED,
        FileWorkflowEventKind.FAILED,
    }
)
_ASYNC_PGN_SAVE_KINDS = frozenset(
    {
        FileWorkflowEventKind.PGN_SAVED,
        FileWorkflowEventKind.PGN_SAVED_AS,
        FileWorkflowEventKind.PGN_SAVE_CANCELLED,
        FileWorkflowEventKind.FAILED,
    }
)
_PGN_SAVE_ACTION_IDS = frozenset({"pgn.save", "pgn.save_as"})


def _validate_async_file_event(event: FileWorkflowEvent) -> None:
    if type(event) is not FileWorkflowEvent:
        raise TypeError("UI event mailbox accepts exact FileWorkflowEvent only")

    # A terminal event is part of the accessibility truth boundary, not merely
    # a transport envelope.  Keep error semantics internally consistent before
    # the UI/NVDA presentation owner can announce them.
    if event.kind is FileWorkflowEventKind.FAILED:
        if not event.error_code:
            raise ValueError("failed worker UI event requires an error code")
    elif event.error_code:
        raise ValueError("successful worker UI event must not carry an error code")

    if event.action_id in _IMPORT_ACTION_IDS:
        if event.kind not in _ASYNC_IMPORT_KINDS:
            raise ValueError("worker UI mailbox received an invalid Library import event")
        return
    if event.action_id == "pgn.open":
        if event.kind not in _ASYNC_PGN_OPEN_KINDS:
            raise ValueError("worker UI mailbox received an invalid PGN Open event")
        return
    if event.action_id in _PGN_SAVE_ACTION_IDS:
        expected_success = (
            FileWorkflowEventKind.PGN_SAVED
            if event.action_id == "pgn.save"
            else FileWorkflowEventKind.PGN_SAVED_AS
        )
        if event.kind not in {
            expected_success,
            FileWorkflowEventKind.PGN_SAVE_CANCELLED,
            FileWorkflowEventKind.FAILED,
        }:
            raise ValueError("worker UI mailbox received an invalid PGN Save event")
        return
    raise ValueError("worker UI mailbox received an invalid file action")


class Version2ImportUiEventMailbox:
    """Bounded asynchronous file-workflow mailbox for path-free host events.

    Construct this object on the Windows UI thread and use it as the file-action
    delegate's ``event_sink``.  Events emitted on that same UI thread are not
    enqueued because the command caller already receives the exact event as its
    return value.  Worker-thread events are queued until the UI thread calls
    :meth:`drain`.

    Only the newest pending progress event is retained.  If the UI stops draining
    long enough to exhaust the bounded lifecycle queue, the mailbox fails closed
    to one sanitized ``ui_event_queue_overflow`` event instead of silently
    returning stale progress or growing without bound.
    """

    def __init__(self, *, max_events: int = 64) -> None:
        if type(max_events) is not int:
            raise TypeError("max_events must be an integer")
        if not 4 <= max_events <= 1024:
            raise ValueError("max_events must be between 4 and 1024")
        self._ui_thread_id = threading.get_ident()
        self._max_events = max_events
        self._events: deque[FileWorkflowEvent] = deque()
        self._lock = threading.RLock()
        self._overflowed = False
        self._coalesced_progress = 0

    @property
    def ui_thread_id(self) -> int:
        return self._ui_thread_id

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._events)

    @property
    def overflowed(self) -> bool:
        with self._lock:
            return self._overflowed

    @property
    def coalesced_progress_count(self) -> int:
        with self._lock:
            return self._coalesced_progress

    def __call__(self, event: FileWorkflowEvent) -> FileWorkflowEvent:
        return self.put(event)

    def put(self, event: FileWorkflowEvent) -> FileWorkflowEvent:
        if type(event) is not FileWorkflowEvent:
            raise TypeError("UI event mailbox accepts exact FileWorkflowEvent only")

        # User-invoked actions already return this event synchronously to the UI
        # caller. Re-queueing them would duplicate announcements/focus work.
        if threading.get_ident() == self._ui_thread_id:
            return event
        return self._put_async(event)

    def put_async_owner(self, event: FileWorkflowEvent) -> FileWorkflowEvent:
        """Queue one asynchronous completion that already reached the UI thread."""

        if threading.get_ident() != self._ui_thread_id:
            raise RuntimeError("owner asynchronous file events require the UI thread")
        return self._put_async(event)

    def _put_async(self, event: FileWorkflowEvent) -> FileWorkflowEvent:
        _validate_async_file_event(event)
        with self._lock:
            if self._overflowed:
                return event

            if event.kind is FileWorkflowEventKind.IMPORT_PROGRESS:
                for index in range(len(self._events) - 1, -1, -1):
                    if self._events[index].kind is FileWorkflowEventKind.IMPORT_PROGRESS:
                        del self._events[index]
                        self._coalesced_progress += 1
                        break

            if len(self._events) >= self._max_events:
                self._events.clear()
                if event.action_id == "pgn.open":
                    overflow_action = "pgn.open"
                    overflow_focus = event.focus_target or "pgn-game-list"
                elif event.action_id in _PGN_SAVE_ACTION_IDS:
                    overflow_action = event.action_id
                    overflow_focus = event.focus_target or "pgn-game-list"
                else:
                    overflow_action = "library.import"
                    overflow_focus = "library-import-file"
                self._events.append(
                    FileWorkflowEvent(
                        FileWorkflowEventKind.FAILED,
                        overflow_action,
                        focus_target=overflow_focus,
                        error_code="ui_event_queue_overflow",
                    )
                )
                self._overflowed = True
                return event

            self._events.append(event)
        return event

    def drain(self, *, max_events: int | None = None) -> tuple[FileWorkflowEvent, ...]:
        """Remove queued worker events; callable only from the captured UI thread."""

        if threading.get_ident() != self._ui_thread_id:
            raise RuntimeError("Library import UI events must be drained on the UI thread")
        if max_events is not None:
            if type(max_events) is not int:
                raise TypeError("max_events must be an integer or None")
            if max_events < 1:
                raise ValueError("max_events must be positive")

        with self._lock:
            count = len(self._events) if max_events is None else min(max_events, len(self._events))
            drained = tuple(self._events.popleft() for _ in range(count))
            if not self._events:
                self._overflowed = False
            return drained


__all__ = ["Version2ImportUiEventMailbox"]
