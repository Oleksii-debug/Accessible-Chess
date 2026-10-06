from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from acs.pgn_document import PgnDocumentSession
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)


PGN = """[Event \"Original\"]
[Site \"?\"]
[Date \"2026.09.07\"]
[Round \"1\"]
[White \"White\"]
[Black \"Black\"]
[Result \"*\"]

1. e4 e5 *
"""


class _Library:
    def import_games(self, *args, **kwargs):
        raise AssertionError("unexpected import")


class _Dialogs:
    def __init__(self, replacement: Path, *, discard: bool) -> None:
        self.replacement = replacement
        self.discard = discard
        self.confirm_calls = 0
        self.open_calls = 0

    def confirm_discard_unsaved_pgn(self) -> bool:
        self.confirm_calls += 1
        return self.discard

    def open_pgn(self) -> Path | None:
        self.open_calls += 1
        return self.replacement

    def save_pgn_as(self, suggested_filename: str = "game.pgn") -> Path | None:
        return None

    def select_library_import(self) -> Path | None:
        return None


class UnsavedPgnOpenGuardTests(unittest.TestCase):
    def _controller(self, dialogs: _Dialogs, session: PgnDocumentSession):
        box = {"session": session}
        events = []
        controller = Version2WindowsFileActionDelegate(
            dialogs=dialogs,
            get_pgn_session=lambda: box["session"],
            set_pgn_session=lambda value: box.__setitem__("session", value),
            import_services_factory=lambda: Version2ImportWorkerServices(
                _Library(), None, lambda: None
            ),
            event_sink=events.append,
            next_delegate=lambda action_id, payload: None,
            current_focus_provider=lambda: "pgn-tree",
        )
        return controller, box, events

    def test_clean_document_opens_replacement_without_discard_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pgn"
            replacement = Path(tmp) / "replacement.pgn"
            source.write_text(PGN, encoding="utf-8")
            replacement.write_text(PGN.replace("Original", "Replacement"), encoding="utf-8")
            session = PgnDocumentSession.open(source)
            dialogs = _Dialogs(replacement, discard=False)
            controller, box, _ = self._controller(dialogs, session)

            result = controller("pgn.open", {})

            self.assertEqual(result.kind, FileWorkflowEventKind.PGN_OPENED)
            self.assertEqual(dialogs.confirm_calls, 0)
            self.assertEqual(dialogs.open_calls, 1)
            self.assertEqual(box["session"].workspace.current_game().tags["Event"], "Replacement")

    def test_refusing_confirmation_preserves_dirty_document_and_skips_open_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pgn"
            replacement = Path(tmp) / "replacement.pgn"
            source.write_text(PGN, encoding="utf-8")
            replacement.write_text(PGN.replace("Original", "Replacement"), encoding="utf-8")
            session = PgnDocumentSession.open(source)
            session.edit_tag("Event", "Unsaved")
            dialogs = _Dialogs(replacement, discard=False)
            controller, box, events = self._controller(dialogs, session)

            result = controller("pgn.open", {})

            self.assertEqual(result.kind, FileWorkflowEventKind.DIALOG_CANCELLED)
            self.assertEqual(result.focus_target, "pgn-tree")
            self.assertEqual(dialogs.confirm_calls, 1)
            self.assertEqual(dialogs.open_calls, 0)
            self.assertIs(box["session"], session)
            self.assertEqual(box["session"].workspace.current_game().tags["Event"], "Unsaved")
            self.assertEqual(events[-1], result)

    def test_explicit_confirmation_allows_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pgn"
            replacement = Path(tmp) / "replacement.pgn"
            source.write_text(PGN, encoding="utf-8")
            replacement.write_text(PGN.replace("Original", "Replacement"), encoding="utf-8")
            session = PgnDocumentSession.open(source)
            session.edit_tag("Event", "Unsaved")
            dialogs = _Dialogs(replacement, discard=True)
            controller, box, _ = self._controller(dialogs, session)

            result = controller("pgn.open", {})

            self.assertEqual(result.kind, FileWorkflowEventKind.PGN_OPENED)
            self.assertEqual(dialogs.confirm_calls, 1)
            self.assertEqual(dialogs.open_calls, 1)
            self.assertEqual(box["session"].workspace.current_game().tags["Event"], "Replacement")


if __name__ == "__main__":
    unittest.main()
