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
    def test_late_cancel_resolves_completed_worker_failure_without_false_cancelling(self) -> None:
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

            # The worker has already classified a real publication failure.
            # A later Cancel click cannot affect publication and therefore must
            # resolve that exact terminal immediately instead of announcing a
            # false new cancellation request to NVDA/browser status surfaces.
            terminal = controller("pgn.cancel_save", {})
            self.assertEqual(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(terminal.error_code, "pgn_save_failed")
            self.assertEqual(async_events, [terminal])
            self.assertEqual(sync_events, [started])
            self.assertTrue(session.dirty)
            self.assertNotIn("private writer failure", repr(terminal))
            self.assertFalse(controller.pgn_save_running)

            # The worker's already-queued owner callback is now stale and must
            # not publish the same terminal a second time when the UI pump drains.
            self.assertTrue(poster.callbacks)
            event_count = len(async_events)
            poster.drain()
            self.assertEqual(len(async_events), event_count)

    def test_late_cancel_resolves_completed_durable_save_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "success.pgn"
            source.write_text(_PGN, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            session.edit_tag("Event", "Durably saved before late cancel")
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

            started = controller("pgn.save", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
            self.assertTrue(controller.wait_for_pgn_save(5.0))

            # Publication is already durable, but the owner commit is queued.
            # Cancel can no longer affect disk bytes, so it must resolve the
            # already-fixed success terminal without first announcing CANCELLING.
            self.assertIn(
                '[Event "Durably saved before late cancel"]',
                source.read_text(encoding="utf-8"),
            )
            self.assertTrue(session.dirty)
            terminal = controller("pgn.cancel_save", {})
            self.assertEqual(terminal.kind, FileWorkflowEventKind.PGN_SAVED)
            self.assertEqual(terminal.action_id, "pgn.save")
            self.assertEqual(terminal.focus_target, "pgn-game-list")
            self.assertEqual(async_events, [terminal])
            self.assertEqual(sync_events, [started])
            self.assertFalse(session.dirty)
            self.assertFalse(controller.pgn_save_running)

            # The callback queued by the worker is stale after immediate owner
            # resolution and cannot publish a duplicate terminal later.
            self.assertTrue(poster.callbacks)
            event_count = len(async_events)
            poster.drain()
            self.assertEqual(len(async_events), event_count)

    def test_late_cancel_resolves_completed_durable_save_as_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "save-as-source.pgn"
            destination = Path(directory) / "save-as-destination.pgn"
            source.write_text(_PGN, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            session.edit_tag("Event", "Durable Save As before late cancel")
            dialogs = _Dialogs()
            dialogs.save_pgn_as = lambda suggested_filename="game.pgn": destination
            poster = _OwnerPoster()
            sync_events: list[FileWorkflowEvent] = []
            async_events: list[FileWorkflowEvent] = []
            controller = Version2WindowsFileActionDelegate(
                dialogs=dialogs,
                get_pgn_session=lambda: session,
                set_pgn_session=lambda value: None,
                import_services_factory=lambda: None,
                event_sink=sync_events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-game-list",
                post_to_ui=poster,
                owner_async_event_sink=async_events.append,
            )

            started = controller("pgn.save_as", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
            self.assertEqual(started.action_id, "pgn.save_as")
            self.assertTrue(controller.wait_for_pgn_save(5.0))

            # Save As has already published the detached bytes, while the owner
            # commit that rebinds source provenance is intentionally still queued.
            self.assertIn(
                '[Event "Durable Save As before late cancel"]',
                destination.read_text(encoding="utf-8"),
            )
            self.assertEqual(Path(session.source.path), source)
            self.assertTrue(session.dirty)

            terminal = controller("pgn.cancel_save", {})
            self.assertEqual(terminal.kind, FileWorkflowEventKind.PGN_SAVED_AS)
            self.assertEqual(terminal.action_id, "pgn.save_as")
            self.assertEqual(terminal.focus_target, "pgn-game-list")
            self.assertEqual(async_events, [terminal])
            self.assertEqual(sync_events, [started])
            self.assertEqual(Path(session.source.path), destination)
            self.assertFalse(session.dirty)
            self.assertFalse(controller.pgn_save_running)

            # The worker callback queued before the late Cancel is stale after
            # immediate owner resolution, so success cannot be announced twice.
            self.assertTrue(poster.callbacks)
            event_count = len(async_events)
            poster.drain()
            self.assertEqual(len(async_events), event_count)


if __name__ == "__main__":
    unittest.main()
