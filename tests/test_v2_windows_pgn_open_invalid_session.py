from __future__ import annotations

import unittest

from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)


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


if __name__ == "__main__":
    unittest.main()
