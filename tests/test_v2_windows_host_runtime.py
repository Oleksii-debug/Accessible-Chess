from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest

from acs.library_import_service import (
    LibraryImportCancelledError,
    LibraryImportProgress,
    LibraryImportResult,
)
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
)
from acs.version2_windows_host_runtime import Version2WindowsFileWorkflowRuntime
from acs.version2_windows_pgn_export import PgnSelectionExportEventKind


_PGN = """[Event "Runtime"]
[Site "?"]
[Date "2026.08.28"]
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
    owners: list[object] = []

    def __init__(self) -> None:
        self.FileName = ""

    def ShowDialog(self, owner):  # noqa: N802
        type(self).owners.append(owner)
        if type(self).selected_paths:
            self.FileName = type(self).selected_paths.pop(0)
        return _DialogResult.OK

    def Dispose(self):  # noqa: N802
        return None


class _SaveDialog:
    owners: list[object] = []

    def __init__(self) -> None:
        self.FileName = ""

    def ShowDialog(self, owner):  # noqa: N802
        type(self).owners.append(owner)
        return _DialogResult.OK

    def Dispose(self):  # noqa: N802
        return None


def _forms_loader():
    return _DialogResult, _OpenDialog, _SaveDialog


class _Owner:
    def __init__(self) -> None:
        self.IsDisposed = False
        self.Disposing = False
        self.InvokeRequired = False
        self.posted: list[object] = []

    def BeginInvoke(self, delegate):  # noqa: N802
        self.posted.append(delegate)
        return len(self.posted)


class _Library:
    def __init__(self) -> None:
        self.calls = 0

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
        self.calls += 1
        total = len(games)
        if progress_callback is not None:
            progress_callback(LibraryImportProgress(1, 0, total))
            progress_callback(LibraryImportProgress(1, total, total))
        return LibraryImportResult(1, 1, total, source_warning_count, 1, total)


class _CancellableLibrary(_Library):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()

    def import_games(self, games, **kwargs) -> LibraryImportResult:
        self.calls += 1
        cancel_check = kwargs["cancel_check"]
        self.entered.set()
        if not self.entered.wait(1.0):
            raise AssertionError("cancellable import did not enter")
        for _ in range(10000):
            if cancel_check():
                raise LibraryImportCancelledError("cancelled")
            threading.Event().wait(0.001)
        raise AssertionError("runtime shutdown did not request cancellation")


class Version2WindowsFileWorkflowRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        _OpenDialog.selected_paths.clear()
        _OpenDialog.owners.clear()
        _SaveDialog.owners.clear()

    def _runtime(
        self,
        owner: _Owner,
        *,
        library: object | None = None,
        imported_events: list[object] | None = None,
        export_calls: list[tuple[object, Path]] | None = None,
        export_events: list[object] | None = None,
        fallback_calls: list[tuple[str, dict[str, object]]] | None = None,
        closed_services: list[bool] | None = None,
    ) -> Version2WindowsFileWorkflowRuntime:
        imported_events = imported_events if imported_events is not None else []
        export_calls = export_calls if export_calls is not None else []
        export_events = export_events if export_events is not None else []
        fallback_calls = fallback_calls if fallback_calls is not None else []
        closed_services = closed_services if closed_services is not None else []
        library = library or _Library()

        def import_services_factory() -> Version2ImportWorkerServices:
            return Version2ImportWorkerServices(
                library,
                None,
                lambda: closed_services.append(True),
            )

        def export_selected(request, destination: Path) -> None:
            export_calls.append((request, destination))

        def import_ui_ready(mailbox) -> None:
            imported_events.extend(mailbox.drain())

        def fallback(action_id: str, payload) -> object:
            fallback_calls.append((action_id, dict(payload)))
            return ("fallback", action_id)

        return Version2WindowsFileWorkflowRuntime(
            owner_control=owner,
            get_pgn_session=lambda: None,
            set_pgn_session=lambda session: None,
            import_services_factory=import_services_factory,
            export_selected=export_selected,
            import_ui_ready=import_ui_ready,
            pgn_export_event_sink=export_events.append,
            next_delegate=fallback,
            current_focus_provider=lambda: "stable-focus",
            ui_delegate_factory=lambda callback: callback,
            file_forms_loader=_forms_loader,
            export_forms_loader=_forms_loader,
        )

    def test_non_host_action_chains_exactly_once_to_canonical_delegate(self) -> None:
        owner = _Owner()
        fallback_calls: list[tuple[str, dict[str, object]]] = []
        runtime = self._runtime(owner, fallback_calls=fallback_calls)

        result = runtime("analysis.restart", {"source": "board"})

        self.assertEqual(result, ("fallback", "analysis.restart"))
        self.assertEqual(fallback_calls, [("analysis.restart", {"source": "board"})])
        self.assertEqual(owner.posted, [])
        self.assertTrue(runtime.shutdown())

    def test_export_routes_through_owned_dialog_then_injected_canonical_exporter(self) -> None:
        owner = _Owner()
        export_calls: list[tuple[object, Path]] = []
        export_events: list[object] = []
        fallback_calls: list[tuple[str, dict[str, object]]] = []
        runtime = self._runtime(
            owner,
            export_calls=export_calls,
            export_events=export_events,
            fallback_calls=fallback_calls,
        )
        payload = {
            "game_index": 0,
            "line_path": ((0, 0),),
            "move_index": 0,
            "expected_record_digest": "a" * 64,
            "content_revision": 1,
        }

        result = runtime("pgn.export_selection", payload)

        self.assertEqual(result.kind, PgnSelectionExportEventKind.EXPORTED)
        self.assertEqual(result.focus_target, "stable-focus")
        self.assertEqual(len(export_calls), 1)
        self.assertEqual(export_calls[0][1], Path("selection.pgn"))
        self.assertEqual(export_calls[0][0].game_index, 0)
        self.assertEqual(export_calls[0][0].line_path, ((0, 0),))
        self.assertEqual(_SaveDialog.owners, [owner])
        self.assertEqual(export_events, [result])
        self.assertEqual(fallback_calls, [])
        self.assertTrue(runtime.shutdown())

    def test_real_pgn_import_posts_one_ui_wakeup_and_owner_drains_on_ui_thread(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pgn"
            source.write_text(_PGN, encoding="utf-8")
            _OpenDialog.selected_paths.append(str(source))
            owner = _Owner()
            library = _Library()
            imported_events: list[object] = []
            closed_services: list[bool] = []
            runtime = self._runtime(
                owner,
                library=library,
                imported_events=imported_events,
                closed_services=closed_services,
            )

            started = runtime("library.import", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.IMPORT_STARTED)
            self.assertTrue(runtime.wait_for_import(5.0))
            self.assertEqual(library.calls, 1)
            self.assertEqual(closed_services, [True])
            self.assertEqual(len(owner.posted), 1)
            self.assertGreaterEqual(runtime.import_mailbox.pending_count, 2)

            callback = owner.posted.pop(0)
            callback()

            self.assertEqual(runtime.import_mailbox.pending_count, 0)
            self.assertEqual(
                [event.kind for event in imported_events],
                [
                    FileWorkflowEventKind.IMPORT_STARTED,
                    FileWorkflowEventKind.IMPORT_PROGRESS,
                    FileWorkflowEventKind.IMPORT_COMPLETED,
                ],
            )
            self.assertEqual(imported_events[-1].game_count, 1)
            self.assertEqual(_OpenDialog.owners, [owner])
            self.assertTrue(runtime.shutdown())

    def test_shutdown_cancels_and_joins_worker_before_runtime_closes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "cancel.pgn"
            source.write_text(_PGN, encoding="utf-8")
            _OpenDialog.selected_paths.append(str(source))
            owner = _Owner()
            library = _CancellableLibrary()
            closed_services: list[bool] = []
            runtime = self._runtime(
                owner,
                library=library,
                closed_services=closed_services,
            )

            runtime("library.import", {})
            self.assertTrue(library.entered.wait(2.0))
            self.assertTrue(runtime.import_running)

            self.assertTrue(runtime.shutdown(5.0))
            self.assertTrue(runtime.closed)
            self.assertFalse(runtime.import_running)
            self.assertEqual(closed_services, [True])
            with self.assertRaisesRegex(RuntimeError, "runtime is closed"):
                runtime("analysis.restart", {})

            # A wakeup posted before close is safe to execute after close; the
            # closed pump performs no projection callback.
            for callback in list(owner.posted):
                callback()

    def test_shutdown_is_ui_thread_affine_and_retryable_from_owner_thread(self) -> None:
        owner = _Owner()
        runtime = self._runtime(owner)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                runtime.shutdown()
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=worker, name="runtime-shutdown-wrong-thread")
        thread.start()
        thread.join(5.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertIn("UI thread", str(errors[0]))
        self.assertFalse(runtime.closed)
        self.assertTrue(runtime.shutdown())
        self.assertTrue(runtime.closed)


if __name__ == "__main__":
    unittest.main()
