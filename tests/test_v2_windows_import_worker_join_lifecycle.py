from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest

from acs.acsdb import AcsDatabase
from acs.library_import_service import LibraryImportService
from acs.version2_windows_file_workflows import Version2ImportWorkerServices
from acs.version2_windows_pgn_streaming_host import (
    Version2WindowsStreamingFileActionDelegate,
)


_VALID_PGN = '''[Event "Join lifecycle"]
[Result "*"]

1. e4 e5 *
'''


class _Dialogs:
    def __init__(self, source: Path) -> None:
        self.source = source

    def open_pgn(self):
        raise AssertionError("ordinary PGN open is outside this lifecycle test")

    def save_pgn_as(self, suggested_filename="game.pgn"):
        raise AssertionError("ordinary PGN save is outside this lifecycle test")

    def select_library_import(self):
        return self.source


class _HoldAfterStreamingRun(Version2WindowsStreamingFileActionDelegate):
    """Keep the Python worker alive after the real import body has returned."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.after_worker_body = threading.Event()
        self.allow_thread_exit = threading.Event()

    def _run_import(self, generation, source_path, suffix, cancel_event) -> None:
        super()._run_import(generation, source_path, suffix, cancel_event)
        self.after_worker_body.set()
        self.allow_thread_exit.wait(5.0)


class Version2WindowsImportWorkerJoinLifecycleTests(unittest.TestCase):
    def test_wait_keeps_real_streaming_worker_joinable_until_thread_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "join-lifecycle.pgn"
            database_path = root / "library.acsdb"
            source.write_text(_VALID_PGN, encoding="utf-8", newline="")
            events = []

            def factory():
                database = AcsDatabase(database_path)
                library = LibraryImportService(database)
                return Version2ImportWorkerServices(library, None, database.close)

            controller = _HoldAfterStreamingRun(
                dialogs=_Dialogs(source),
                get_pgn_session=lambda: None,
                set_pgn_session=lambda session: None,
                import_services_factory=factory,
                event_sink=events.append,
                next_delegate=lambda action, payload: None,
            )

            try:
                controller("library.import", {})
                self.assertTrue(controller.after_worker_body.wait(3.0))

                first_worker = controller._worker
                self.assertIsNotNone(first_worker)
                assert first_worker is not None
                self.assertTrue(first_worker.is_alive())
                self.assertFalse(controller.wait_for_import(0.01))

                controller.allow_thread_exit.set()
                self.assertTrue(controller.wait_for_import(5.0))
                self.assertFalse(controller.import_running)
                self.assertIs(controller._worker, first_worker)

                # A joined completed worker must not block a subsequent import;
                # _start_import replaces it with the new generation's Thread.
                controller.after_worker_body.clear()
                controller.allow_thread_exit.clear()
                controller("library.import", {})
                self.assertTrue(controller.after_worker_body.wait(3.0))
                second_worker = controller._worker
                self.assertIsNotNone(second_worker)
                self.assertIsNot(second_worker, first_worker)

                controller.allow_thread_exit.set()
                self.assertTrue(controller.wait_for_import(5.0))
                self.assertFalse(controller.import_running)
            finally:
                controller.allow_thread_exit.set()
                controller.shutdown(5.0)


if __name__ == "__main__":
    unittest.main()
