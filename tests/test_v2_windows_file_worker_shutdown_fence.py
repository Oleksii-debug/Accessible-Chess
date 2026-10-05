from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)


PGN_TEXT = """[Event \"Shutdown fence\"]
[Site \"?\"]
[Date \"2026.10.05\"]
[Round \"1\"]
[White \"White\"]
[Black \"Black\"]
[Result \"*\"]

1. e4 e5 *
"""


class _Dialogs:
    def __init__(self, source: Path) -> None:
        self.source = source

    def open_pgn(self):
        return self.source

    def save_pgn_as(self, suggested_filename: str = "game.pgn"):
        return None

    def select_library_import(self):
        return self.source


class _UnusedLibrary:
    def import_games(self, *args, **kwargs):
        raise AssertionError("worker must not start after shutdown")


class Version2WindowsFileWorkerShutdownFenceTests(unittest.TestCase):
    def _delegate(self, source: Path, *, event_sink, post_to_ui=None):
        return Version2WindowsFileActionDelegate(
            dialogs=_Dialogs(source),
            get_pgn_session=lambda: None,
            set_pgn_session=lambda session: None,
            import_services_factory=lambda: Version2ImportWorkerServices(
                _UnusedLibrary(), None, lambda: None
            ),
            event_sink=event_sink,
            next_delegate=lambda action_id, payload: None,
            current_focus_provider=lambda: "pgn-tree",
            post_to_ui=post_to_ui,
        )

    def test_import_started_reentrant_shutdown_does_not_start_reserved_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "import-shutdown.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            events = []
            shutdown_results = []
            holder = {}

            def sink(event):
                events.append(event)
                if event.kind is FileWorkflowEventKind.IMPORT_STARTED:
                    shutdown_results.append(holder["delegate"].shutdown(0.0))

            delegate = self._delegate(source, event_sink=sink, post_to_ui=lambda cb: None)
            holder["delegate"] = delegate

            with mock.patch.object(threading.Thread, "start", autospec=True) as start:
                result = delegate("library.import", {})

            self.assertEqual(shutdown_results, [False])
            self.assertEqual(start.call_count, 0)
            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.error_code, "file_workflow_closed")
            self.assertEqual(
                [event.kind for event in events],
                [FileWorkflowEventKind.IMPORT_STARTED, FileWorkflowEventKind.FAILED],
            )
            self.assertFalse(delegate.import_running)

    def test_import_cleanup_base_exception_releases_shared_worker_slot(self) -> None:
        class CleanupAbort(BaseException):
            pass

        class SuccessfulLibrary:
            def import_games(self, *args, **kwargs):
                return SimpleNamespace(game_count=1, warning_count=0)

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "import-cleanup-abort.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            events = []
            cleanup_calls = []

            def cleanup() -> None:
                cleanup_calls.append("close")
                raise CleanupAbort("secondary cleanup failure")

            delegate = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(source),
                get_pgn_session=lambda: None,
                set_pgn_session=lambda session: None,
                import_services_factory=lambda: Version2ImportWorkerServices(
                    SuccessfulLibrary(), None, cleanup
                ),
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-tree",
                post_to_ui=None,
            )

            started = delegate("library.import", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.IMPORT_STARTED)
            self.assertTrue(delegate.wait_for_import(2.0))
            self.assertEqual(cleanup_calls, ["close"])
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_COMPLETED)
            self.assertFalse(delegate.import_running)

            reopened = delegate("pgn.open", {})
            self.assertEqual(reopened.kind, FileWorkflowEventKind.PGN_OPENED)
            self.assertFalse(delegate.pgn_open_running)

    def test_pgn_open_started_reentrant_shutdown_does_not_start_reserved_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "open-shutdown.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            events = []
            shutdown_results = []
            posted = []
            holder = {}

            def sink(event):
                events.append(event)
                if event.kind is FileWorkflowEventKind.PGN_OPEN_STARTED:
                    shutdown_results.append(holder["delegate"].shutdown(0.0))

            delegate = self._delegate(source, event_sink=sink, post_to_ui=posted.append)
            holder["delegate"] = delegate

            with mock.patch.object(threading.Thread, "start", autospec=True) as start:
                result = delegate("pgn.open", {})

            self.assertEqual(shutdown_results, [False])
            self.assertEqual(start.call_count, 0)
            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.error_code, "file_workflow_closed")
            self.assertEqual(posted, [])
            self.assertEqual(
                [event.kind for event in events],
                [FileWorkflowEventKind.PGN_OPEN_STARTED, FileWorkflowEventKind.FAILED],
            )
            self.assertFalse(delegate.pgn_open_running)

    def test_pgn_ui_post_failure_after_shutdown_does_not_publish_late_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "late-post-failure.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            events = []
            post_entered = threading.Event()
            release_post = threading.Event()

            def failing_post(callback):
                post_entered.set()
                if not release_post.wait(2.0):
                    raise AssertionError("test did not release owner post")
                raise RuntimeError("owner window already closing")

            delegate = self._delegate(source, event_sink=events.append, post_to_ui=failing_post)
            started = delegate("pgn.open", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.PGN_OPEN_STARTED)
            self.assertTrue(post_entered.wait(2.0))

            self.assertFalse(delegate.shutdown(0.0))
            event_count_at_shutdown = len(events)
            release_post.set()
            self.assertTrue(delegate.shutdown(2.0))

            self.assertEqual(len(events), event_count_at_shutdown)
            self.assertEqual(events, [started])
            self.assertFalse(delegate.pgn_open_running)


if __name__ == "__main__":
    unittest.main()
