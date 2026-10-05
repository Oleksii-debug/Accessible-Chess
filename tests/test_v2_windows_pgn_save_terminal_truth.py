from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from acs.pgn_document import PgnDocumentSession
from acs.version2_windows_file_workflows import (
    FileWorkflowEvent,
    FileWorkflowEventKind,
    Version2WindowsFileActionDelegate,
)


_PGN = """[Event "Failure truth"]
[Site "?"]
[Date "2026.10.05"]
[Round "1"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 *
"""


class _Dialogs:
    def open_pgn(self):
        return None

    def save_pgn_as(self, suggested_filename="game.pgn"):
        return None

    def select_library_import(self):
        return None


class _OwnerPoster:
    def __init__(self) -> None:
        self.owner = threading.get_ident()
        self.callbacks: list[object] = []
        self._lock = threading.Lock()

    def __call__(self, callback) -> None:
        with self._lock:
            self.callbacks.append(callback)

    def drain(self) -> None:
        if threading.get_ident() != self.owner:
            raise AssertionError("owner callback drained off owner thread")
        while True:
            with self._lock:
                if not self.callbacks:
                    return
                callback = self.callbacks.pop(0)
            callback()


class Version2WindowsPgnSaveTerminalTruthTests(unittest.TestCase):
    def test_late_cancel_cannot_relabel_completed_worker_failure_as_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "failure.pgn"
            source.write_text(_PGN, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            session.edit_tag("Event", "Still dirty after failure")
            poster = _OwnerPoster()
            sync_events: list[FileWorkflowEvent] = []
            async_events: list[FileWorkflowEvent] = []
            controller = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(),
                get_pgn_session=lambda: session,
                set_pgn_session=lambda value: None,
                import_services_factory=lambda: None,
                event_sink=sync_events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-game-list",
                post_to_ui=poster,
                owner_async_event_sink=async_events.append,
            )

            with mock.patch(
                "acs.version2_windows_file_workflows.publish_pgn_save_snapshot",
                side_effect=RuntimeError("private writer failure"),
            ):
                started = controller("pgn.save", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
                self.assertTrue(controller.wait_for_pgn_save(5.0))

            # The worker has already classified a real publication failure. A
            # later Cancel click can request no further work, but must not rewrite
            # that completed failure into a false cancellation announcement.
            cancelling = controller("pgn.cancel_save", {})
            self.assertEqual(cancelling.kind, FileWorkflowEventKind.PGN_SAVE_CANCELLING)
            poster.drain()

            self.assertTrue(session.dirty)
            self.assertEqual(len(async_events), 1)
            terminal = async_events[0]
            self.assertEqual(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(terminal.error_code, "pgn_save_failed")
            self.assertNotIn("private writer failure", repr(terminal))
            self.assertFalse(controller.pgn_save_running)


if __name__ == "__main__":
    unittest.main()
