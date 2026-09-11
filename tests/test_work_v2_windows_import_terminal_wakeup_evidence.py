from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import time
import unittest

from acs.library_import_service import LibraryImportProgress, LibraryImportResult
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
)
from acs.version2_windows_host_runtime import Version2WindowsFileWorkflowRuntime


_PGN = """[Event "Terminal wakeup evidence"]
[Site "?"]
[Date "2026.09.07"]
[Round "1"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 *
"""


class _DialogResult:
    OK = "ok"


class _OpenDialog:
    selected_paths: list[str] = []

    def __init__(self) -> None:
        self.FileName = ""

    def ShowDialog(self, owner):  # noqa: N802
        if type(self).selected_paths:
            self.FileName = type(self).selected_paths.pop(0)
        return _DialogResult.OK

    def Dispose(self):  # noqa: N802
        return None


class _SaveDialog:
    def __init__(self) -> None:
        self.FileName = ""

    def ShowDialog(self, owner):  # noqa: N802
        return _DialogResult.OK

    def Dispose(self):  # noqa: N802
        return None


def _forms_loader():
    return _DialogResult, _OpenDialog, _SaveDialog


class _FailOnceOwner:
    def __init__(self) -> None:
        self.IsDisposed = False
        self.Disposing = False
        self.InvokeRequired = False
        self.fail_next = False
        self.calls = 0
        self.posted: list[object] = []
        self._lock = threading.Lock()

    def BeginInvoke(self, delegate):  # noqa: N802
        with self._lock:
            self.calls += 1
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("transient BeginInvoke failure")
            self.posted.append(delegate)
            return self.calls

    def pop_posted(self):
        with self._lock:
            if not self.posted:
                return None
            return self.posted.pop(0)

    def has_posted(self) -> bool:
        with self._lock:
            return bool(self.posted)


class _TwoPhaseLibrary:
    """Emit ordinary progress, pause, then complete after the UI drained it."""

    def __init__(self) -> None:
        self.progress_published = threading.Event()
        self.release_completion = threading.Event()

    def import_games(
        self,
        games,
        *,
        source_name,
        source_format,
        source_sha256,
        source_warning_count=0,
        cancel_check=None,
        progress_callback=None,
    ) -> LibraryImportResult:
        total = len(games)
        if progress_callback is None:
            raise AssertionError("host import did not supply progress callback")
        progress_callback(LibraryImportProgress(1, 0, total))
        self.progress_published.set()
        if not self.release_completion.wait(5.0):
            raise AssertionError("test did not release terminal import completion")
        if cancel_check is not None and cancel_check():
            raise AssertionError("test import was unexpectedly cancelled")
        return LibraryImportResult(1, 1, total, source_warning_count, 1, total)


class Version2WindowsImportTerminalWakeupEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        _OpenDialog.selected_paths.clear()

    def test_terminal_event_self_recovers_after_one_transient_begininvoke_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "terminal.pgn"
            source.write_text(_PGN, encoding="utf-8")
            _OpenDialog.selected_paths.append(str(source))

            owner = _FailOnceOwner()
            library = _TwoPhaseLibrary()
            delivered = []
            closed_services = []

            def services_factory() -> Version2ImportWorkerServices:
                return Version2ImportWorkerServices(
                    library,
                    None,
                    lambda: closed_services.append(True),
                )

            def import_ui_ready(mailbox) -> None:
                delivered.extend(mailbox.drain())

            runtime = Version2WindowsFileWorkflowRuntime(
                owner_control=owner,
                get_pgn_session=lambda: None,
                set_pgn_session=lambda session: None,
                import_services_factory=services_factory,
                export_selected=lambda request, destination: None,
                import_ui_ready=import_ui_ready,
                pgn_export_event_sink=lambda event: None,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "library-import-file",
                ui_delegate_factory=lambda callback: callback,
                file_forms_loader=_forms_loader,
                export_forms_loader=_forms_loader,
            )

            started = runtime("library.import", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.IMPORT_STARTED)
            self.assertTrue(library.progress_published.wait(5.0))

            initial_callback = owner.pop_posted()
            self.assertIsNotNone(initial_callback)
            initial_callback()
            self.assertEqual(runtime.import_mailbox.pending_count, 0)
            self.assertEqual(
                [event.kind for event in delivered],
                [
                    FileWorkflowEventKind.IMPORT_STARTED,
                    FileWorkflowEventKind.IMPORT_PROGRESS,
                ],
            )

            owner.fail_next = True
            library.release_completion.set()
            self.assertTrue(runtime.wait_for_import(5.0))
            self.assertEqual(closed_services, [True])
            self.assertEqual(runtime.import_mailbox.pending_count, 1)
            self.assertGreaterEqual(owner.calls, 2)

            deadline = time.monotonic() + 1.0
            while not owner.has_posted() and time.monotonic() < deadline:
                time.sleep(0.01)

            self.assertTrue(
                owner.has_posted(),
                "terminal import event remained stranded after one transient UI scheduling failure",
            )
            retry_callback = owner.pop_posted()
            self.assertIsNotNone(retry_callback)
            retry_callback()

            self.assertEqual(runtime.import_mailbox.pending_count, 0)
            self.assertEqual(delivered[-1].kind, FileWorkflowEventKind.IMPORT_COMPLETED)
            self.assertEqual(delivered[-1].focus_target, "library-import-file")
            self.assertEqual(delivered[-1].game_count, 1)
            self.assertTrue(runtime.shutdown())


if __name__ == "__main__":
    unittest.main()
