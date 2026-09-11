import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

from acs.library_import_service import LibraryImportProgress, LibraryImportResult
from acs.library_webview_projection import LibraryImportWebViewProjection
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind, Version2WindowsFileActionDelegate, Version2ImportWorkerServices,
)


class ImportTerminalUiTests(unittest.TestCase):
    def test_unknown_count_empty_and_retry_never_fabricate_games(self):
        commands = []
        ui = LibraryImportWebViewProjection(lambda *args: commands.append(args))
        started = ui.prepare().payload["import"]
        self.assertEqual(started["total_games"], 0)
        self.assertNotIn("0 з 0", started["progress_label"])
        empty = ui.empty().payload["import"]
        self.assertEqual(empty["phase"], "empty")
        self.assertEqual(empty["processed_games"], 0)
        self.assertTrue(empty["actions"][0]["enabled"])
        ui.request_import()
        self.assertEqual(commands, [("library.import", {})])

    def test_host_cancel_does_not_redispatch_and_count_keeps_cancelling(self):
        commands = []
        ui = LibraryImportWebViewProjection(lambda *args: commands.append(args))
        ui.prepare()
        ui.host_cancelling()
        ui.begin(2)
        ui.progress(LibraryImportProgress(7, 1, 2))
        self.assertEqual(ui.phase.value, "cancelling")
        self.assertEqual(commands, [])
        self.assertEqual(ui.cancelled().payload["import"]["phase"], "cancelled")

    def test_real_attempt_identity_remains_required_for_completion(self):
        ui = LibraryImportWebViewProjection(lambda *_: None)
        ui.prepare()
        ui.begin(2)
        ui.progress(LibraryImportProgress(7, 1, 2))
        with self.assertRaises(ValueError):
            ui.complete(LibraryImportResult(8, 1, 2, 0, 1, 2))
        with self.assertRaises(ValueError):
            ui.empty()
        self.assertEqual(ui.phase.value, "running")
        self.assertEqual(ui.complete(LibraryImportResult(7, 1, 2, 0, 1, 2)).payload["import"]["phase"], "completed")

    def test_immediate_worker_terminal_cannot_precede_start(self):
        events = []
        dialogs = SimpleNamespace(open_pgn=lambda: None, save_pgn_as=lambda *_: None,
                                  select_library_import=lambda: Path("empty.pgn"))
        service = SimpleNamespace(import_games=lambda *_: None)
        host = Version2WindowsFileActionDelegate(
            dialogs=dialogs, get_pgn_session=lambda: None, set_pgn_session=lambda _: None,
            import_services_factory=lambda: Version2ImportWorkerServices(service, None, lambda: None),
            event_sink=events.append, next_delegate=lambda *_: None,
        )

        class ImmediateThread:
            def __init__(self, *, target, args, **kwargs): self.run = lambda: target(*args)
            def start(self): self.run()
            def is_alive(self): return False

        with patch("acs.version2_windows_file_workflows.threading.Thread", ImmediateThread), patch(
            "acs.version2_windows_file_workflows.open_pgn", return_value=SimpleNamespace(games=())
        ):
            host("library.import", {})
        self.assertEqual([event.kind for event in events], [FileWorkflowEventKind.IMPORT_STARTED, FileWorkflowEventKind.IMPORT_EMPTY])


if __name__ == "__main__": unittest.main()
