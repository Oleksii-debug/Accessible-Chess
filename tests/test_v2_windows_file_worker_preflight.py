from __future__ import annotations

from types import SimpleNamespace
import tempfile
import threading
from pathlib import Path
import unittest

from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)


PGN_TEXT = """[Event \"Worker preflight\"]
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
        self.open_calls = 0
        self.import_calls = 0
        self.import_hook = None

    def open_pgn(self):
        self.open_calls += 1
        return self.source

    def save_pgn_as(self, suggested_filename: str = "game.pgn"):
        return None

    def select_library_import(self):
        self.import_calls += 1
        if self.import_hook is not None:
            self.import_hook()
        return self.source


class _BlockingLibrary:
    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        self.entered = entered
        self.release = release

    def import_games(self, *args, **kwargs):
        self.entered.set()
        if not self.release.wait(2.0):
            raise AssertionError("test did not release Library import")
        return SimpleNamespace(game_count=1, warning_count=0)


class Version2WindowsFileWorkerPreflightTests(unittest.TestCase):
    def test_pgn_open_rejects_active_import_before_native_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "worker-preflight.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            entered = threading.Event()
            release = threading.Event()
            dialogs = _Dialogs(source)
            events = []
            delegate = Version2WindowsFileActionDelegate(
                dialogs=dialogs,
                get_pgn_session=lambda: None,
                set_pgn_session=lambda session: None,
                import_services_factory=lambda: Version2ImportWorkerServices(
                    _BlockingLibrary(entered, release), None, lambda: None
                ),
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-tree",
                post_to_ui=lambda callback: None,
            )

            started = delegate("library.import", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.IMPORT_STARTED)
            self.assertTrue(entered.wait(1.0))

            busy = delegate("pgn.open", {})
            self.assertEqual(busy.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(busy.error_code, "file_worker_busy")
            self.assertEqual(busy.focus_target, "library-import-cancel")
            self.assertEqual(dialogs.open_calls, 0)

            release.set()
            self.assertTrue(delegate.wait_for_import(2.0))

    def test_import_picker_reentrant_shutdown_cannot_start_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "shutdown-during-picker.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            dialogs = _Dialogs(source)
            events = []
            factory_calls = []
            delegate = Version2WindowsFileActionDelegate(
                dialogs=dialogs,
                get_pgn_session=lambda: None,
                set_pgn_session=lambda session: None,
                import_services_factory=lambda: factory_calls.append(True),
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "library-import-file",
                post_to_ui=lambda callback: None,
            )
            dialogs.import_hook = lambda: self.assertTrue(delegate.shutdown(0.0))

            result = delegate("library.import", {})

            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.error_code, "file_workflow_closed")
            self.assertEqual(result.focus_target, "library-import-file")
            self.assertFalse(delegate.import_running)
            self.assertEqual(factory_calls, [])
            self.assertEqual(dialogs.import_calls, 1)
            self.assertEqual(events[-1], result)


if __name__ == "__main__":
    unittest.main()
