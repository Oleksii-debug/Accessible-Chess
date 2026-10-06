from __future__ import annotations

import unittest

from acs.pgn_document import PgnDocumentSession
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)
from acs.version2_windows_host_runtime import Version2WindowsFileWorkflowRuntime


class _Dialogs:
    def __init__(self) -> None:
        self.open_calls = 0

    def open_pgn(self):
        self.open_calls += 1
        raise AssertionError("invalid current session must fail before opening a native dialog")

    def save_pgn_as(self, suggested_filename: str = "game.pgn"):
        return None

    def select_library_import(self):
        return None


class _UnusedLibrary:
    def import_games(self, *args, **kwargs):
        raise AssertionError("unexpected Library import")


class _Owner:
    IsDisposed = False
    Disposing = False
    InvokeRequired = False

    def __init__(self) -> None:
        self.posted: list[object] = []

    def BeginInvoke(self, delegate):  # noqa: N802
        self.posted.append(delegate)
        return len(self.posted)


class _ActiveSession(PgnDocumentSession):
    """Executable subclass that must never cross the production host boundary."""

    @property
    def document_revision(self):
        raise AssertionError("foreign document_revision hook executed")

    @property
    def dirty(self):
        raise AssertionError("foreign dirty hook executed")

    @property
    def source(self):
        raise AssertionError("foreign source hook executed")

    def view(self):
        raise AssertionError("foreign view hook executed")

    def save(self):
        raise AssertionError("foreign save hook executed")


class Version2WindowsPgnOpenInvalidSessionTests(unittest.TestCase):
    def test_invalid_current_session_fails_closed_before_revision_or_dialog_access(self) -> None:
        dialogs = _Dialogs()
        invalid_session = object()
        events = []
        delegate = Version2WindowsFileActionDelegate(
            dialogs=dialogs,
            get_pgn_session=lambda: invalid_session,
            set_pgn_session=lambda session: None,
            import_services_factory=lambda: Version2ImportWorkerServices(
                _UnusedLibrary(), None, lambda: None
            ),
            event_sink=events.append,
            next_delegate=lambda action_id, payload: None,
            current_focus_provider=lambda: "pgn-tree",
        )

        result = delegate("pgn.open", {})

        self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
        self.assertEqual(result.error_code, "pgn_session_invalid")
        self.assertEqual(result.focus_target, "pgn-tree")
        self.assertEqual(events, [result])
        self.assertEqual(dialogs.open_calls, 0)

    def test_direct_delegate_rejects_active_session_subclass_without_hooks(self) -> None:
        dialogs = _Dialogs()
        active_session = object.__new__(_ActiveSession)
        events = []
        delegate = Version2WindowsFileActionDelegate(
            dialogs=dialogs,
            get_pgn_session=lambda: active_session,
            set_pgn_session=lambda session: None,
            import_services_factory=lambda: Version2ImportWorkerServices(
                _UnusedLibrary(), None, lambda: None
            ),
            event_sink=events.append,
            next_delegate=lambda action_id, payload: None,
            current_focus_provider=lambda: "pgn-tree",
        )

        result = delegate("pgn.open", {})

        self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
        self.assertEqual(result.error_code, "pgn_session_invalid")
        self.assertEqual(result.focus_target, "pgn-tree")
        self.assertEqual(events, [result])
        self.assertEqual(dialogs.open_calls, 0)

    def test_direct_delegate_contains_corrupted_canonical_session_revision(self) -> None:
        class ActiveInt(int):
            def __lt__(self, other):
                raise AssertionError("active session revision ordering executed")

        dialogs = _Dialogs()
        session = PgnDocumentSession.from_text(
            '[Event "Corrupted revision"]\n[Result "*"]\n\n*\n'
        )
        session._document_revision = ActiveInt(0)
        events = []
        delegate = Version2WindowsFileActionDelegate(
            dialogs=dialogs,
            get_pgn_session=lambda: session,
            set_pgn_session=lambda replacement: None,
            import_services_factory=lambda: Version2ImportWorkerServices(
                _UnusedLibrary(), None, lambda: None
            ),
            event_sink=events.append,
            next_delegate=lambda action_id, payload: None,
            current_focus_provider=lambda: "pgn-tree",
        )

        result = delegate("pgn.open", {})

        self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
        self.assertEqual(result.error_code, "pgn_session_invalid")
        self.assertEqual(events, [result])
        self.assertEqual(dialogs.open_calls, 0)

    def test_production_runtime_rejects_active_session_subclass_without_hooks(self) -> None:
        # Bypass the canonical constructor deliberately. If the production
        # runtime leaked this active subclass into the shared delegate, Open
        # would execute document_revision/dirty and Save would execute other
        # overridden session behavior before it could fail closed.
        active_session = object.__new__(_ActiveSession)
        owner = _Owner()
        forms_loader_calls: list[bool] = []

        def forms_loader():
            forms_loader_calls.append(True)
            raise AssertionError("invalid session must fail before native dialogs load")

        runtime = Version2WindowsFileWorkflowRuntime(
            owner_control=owner,
            get_pgn_session=lambda: active_session,
            set_pgn_session=lambda session: None,
            import_services_factory=lambda: Version2ImportWorkerServices(
                _UnusedLibrary(), None, lambda: None
            ),
            export_selected=lambda request, destination: None,
            import_ui_ready=lambda mailbox: None,
            pgn_export_event_sink=lambda event: None,
            next_delegate=lambda action_id, payload: None,
            current_focus_provider=lambda: "pgn-tree",
            ui_delegate_factory=lambda callback: callback,
            file_forms_loader=forms_loader,
            export_forms_loader=forms_loader,
        )

        try:
            for action_id in ("pgn.open", "pgn.save", "pgn.save_as"):
                result = runtime(action_id, {})
                self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
                self.assertEqual(result.error_code, "pgn_session_invalid")
                self.assertEqual(result.focus_target, "pgn-tree")
            self.assertEqual(forms_loader_calls, [])
            self.assertFalse(runtime.pgn_open_running)
            self.assertFalse(runtime.pgn_save_running)
        finally:
            self.assertTrue(runtime.shutdown())


if __name__ == "__main__":
    unittest.main()
