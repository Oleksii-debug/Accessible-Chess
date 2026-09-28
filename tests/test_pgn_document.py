from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.gametree_navigation import GameTreeCursor, VariationStep
from acs.pgn_document import (
    PgnConcurrentWriteError,
    PgnDocumentError,
    PgnDocumentErrorCode,
    PgnDocumentSession,
)
from acs.pgn_service import open_pgn


DOCUMENT = '''[Event "Workspace One"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 e5 (1... c5 {Sicilian} 2. Nf3 (2... d6) 2... Nc6) (1... c6 2. d4) 2. Nf3 Nc6 1-0

[Event "Workspace Two"]
[White "Gamma"]
[Black "Delta"]
[Result "1/2-1/2"]

1. d4 d5 2. c4 e6 1/2-1/2
'''

PASTE = '''[Event "Imported Three"]
[White "Epsilon"]
[Black "Zeta"]
[Result "*"]

1. c4 e5 (1... c5) 2. Nc3 *
'''


class ProfessionalPgnDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_document(self, name: str = "source.pgn") -> Path:
        path = self.root / name
        path.write_text(DOCUMENT, encoding="utf-8", newline="\n")
        return path

    def test_new_game_save_as_and_reopen_is_canonical(self) -> None:
        session = PgnDocumentSession.new_game({"White": "Ada", "Black": "Boris"})
        self.assertEqual(session.workspace.game_count, 1)
        self.assertTrue(session.dirty)
        self.assertIsNone(session.source)
        self.assertEqual(session.workspace.current_game().result, "*")

        target = self.root / "new game.pgn"
        saved = session.save_as(target)
        self.assertTrue(Path(saved.path).samefile(target))
        self.assertFalse(session.dirty)
        reopened = PgnDocumentSession.open(target)
        self.assertEqual(reopened.copy_pgn(), session.copy_pgn())
        self.assertEqual(reopened.workspace.current_game().tags["White"], "Ada")

    def test_open_multigame_copy_and_exact_nested_context_restore(self) -> None:
        session = PgnDocumentSession.open(self.write_document())
        session.workspace.set_cursor(
            GameTreeCursor((VariationStep(1, 0), VariationStep(1, 0)), 0)
        )
        bookmark = session.bookmark()
        copied = session.copy_pgn()
        self.assertIn("Sicilian", copied)
        self.assertIn("Imported Three", PASTE)

        # Simulate a temporary non-mutating Engine/Board handoff.
        session.workspace.document_end()
        restored = session.restore_context(bookmark)
        self.assertEqual(restored.selected_game_index, 0)
        self.assertEqual(restored.cursor, bookmark.cursor)
        self.assertEqual(session.workspace.current_move().san, "d6")
        self.assertFalse(session.dirty)

    def test_tag_and_result_edit_save_reopen_preserves_tree(self) -> None:
        path = self.write_document()
        session = PgnDocumentSession.open(path)
        session.edit_tag("Event", "Edited Event")
        session.edit_tag("Annotator", "Accessible Chess")
        session.set_result("0-1")
        before_save = session.copy_pgn()
        self.assertTrue(session.dirty)

        saved = session.save()
        self.assertEqual(saved.sha256, session.source.sha256)
        self.assertFalse(session.dirty)
        reopened = PgnDocumentSession.open(path)
        game = reopened.workspace.current_game()
        self.assertEqual(game.tags["Event"], "Edited Event")
        self.assertEqual(game.tags["Annotator"], "Accessible Chess")
        self.assertEqual(game.result, "0-1")
        self.assertEqual(reopened.copy_pgn(), before_save)
        self.assertEqual(len(game.line.moves[1].variations), 2)
        self.assertEqual(game.line.moves[1].variations[0].moves[0].san, "c5")

    def test_save_detects_external_change_instead_of_losing_it(self) -> None:
        path = self.write_document()
        session = PgnDocumentSession.open(path)
        session.edit_tag("Event", "Local Edit")
        path.write_text(DOCUMENT.replace("Workspace One", "External Edit"), encoding="utf-8")

        with self.assertRaises(PgnConcurrentWriteError):
            session.save()
        self.assertTrue(session.dirty)
        self.assertIn("External Edit", path.read_text(encoding="utf-8"))

    def test_invalid_utf8_source_requires_save_as(self) -> None:
        path = self.root / "legacy.pgn"
        raw = DOCUMENT.replace("Sicilian", "Sicilian {legacy}").encode("utf-8")
        path.write_bytes(raw + b"\n{broken byte: \xff}\n")
        session = PgnDocumentSession.open(path)
        self.assertFalse(session.view().source_overwrite_safe)
        self.assertTrue(session.view().global_warnings)
        self.assertTrue(session.dirty)
        self.assertTrue(
            any("Invalid UTF-8 bytes were replaced" in warning for warning in session.view().global_warnings)
        )
        self.assertTrue(
            any(
                "nested brace comment delimiters normalized to parentheses" in warning
                for warning in session.view().global_warnings
            )
        )

        with self.assertRaises(PgnDocumentError) as caught:
            session.save()
        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.SOURCE_REQUIRES_SAVE_AS)

        target = self.root / "recovered.pgn"
        session.save_as(target)
        self.assertTrue(target.exists())
        self.assertFalse(session.dirty)
        reopened = PgnDocumentSession.open(target)
        self.assertTrue(reopened.view().source_overwrite_safe)
        self.assertFalse(reopened.view().global_warnings)

    def test_append_pasted_multigame_preserves_current_location(self) -> None:
        session = PgnDocumentSession.open(self.write_document())
        session.workspace.set_cursor(GameTreeCursor((), 3))
        before = session.workspace.view()
        count = session.append_text(PASTE)
        self.assertEqual(count, 1)
        self.assertEqual(session.workspace.game_count, 3)
        self.assertEqual(session.workspace.selected_game_index, before.selected_game_index)
        self.assertEqual(session.workspace.cursor, before.cursor)
        summaries = session.workspace.summaries()
        self.assertEqual(summaries[2].event, "Imported Three")
        self.assertEqual([item.source_index for item in summaries], [0, 1, 2])
        imported = session.workspace.games()[2]
        self.assertEqual(imported.line.moves[1].variations[0].moves[0].san, "c5")
        self.assertTrue(session.dirty)

    def test_export_selected_outputs_only_selected_game(self) -> None:
        session = PgnDocumentSession.open(self.write_document())
        session.workspace.select_game(1)
        target = self.root / "selected.pgn"
        session.export_selected(target)
        opened = open_pgn(target)
        self.assertEqual(opened.total_games, 1)
        self.assertEqual(opened.games[0].tags["Event"], "Workspace Two")
        self.assertEqual(opened.games[0].result, "1/2-1/2")

    def test_existing_save_as_target_requires_expected_version(self) -> None:
        session = PgnDocumentSession.from_text(PASTE)
        target = self.root / "existing.pgn"
        target.write_text(DOCUMENT, encoding="utf-8")

        with self.assertRaises(PgnDocumentError) as caught:
            session.save_as(target, overwrite=True)
        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.DESTINATION_VERSION_REQUIRED)

        expected = session.expected_destination_sha256(target)
        session.save_as(target, overwrite=True, expected_sha256=expected)
        self.assertEqual(PgnDocumentSession.open(target).workspace.game_count, 1)
        self.assertEqual(PgnDocumentSession.open(target).workspace.summaries()[0].event, "Imported Three")

    def test_bookmark_fails_closed_after_content_edit(self) -> None:
        session = PgnDocumentSession.open(self.write_document())
        session.workspace.set_cursor(GameTreeCursor((), 2))
        bookmark = session.bookmark()
        session.edit_tag("Event", "Changed")
        with self.assertRaises(PgnDocumentError) as caught:
            session.restore_context(bookmark)
        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.CONTEXT_STALE)

    def test_result_tag_routes_through_result_consistency(self) -> None:
        session = PgnDocumentSession.from_text(PASTE)
        session.edit_tag("Result", "1-0")
        game = session.workspace.current_game()
        self.assertEqual(game.tags["Result"], "1-0")
        self.assertEqual(game.line.result, "1-0")
        with self.assertRaises(PgnDocumentError) as caught:
            session.set_result("draw")
        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.INVALID_RESULT)

    def test_delete_tag_is_roundtrip_safe_but_result_cannot_be_removed(self) -> None:
        session = PgnDocumentSession.from_text(PASTE)
        session.edit_tag("Annotator", "A")
        session.delete_tag("Annotator")
        self.assertNotIn("Annotator", session.workspace.current_game().tags)
        with self.assertRaises(PgnDocumentError) as caught:
            session.delete_tag("Result")
        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.INVALID_TAG)


if __name__ == "__main__":
    unittest.main()
