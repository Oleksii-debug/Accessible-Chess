from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.gametree_navigation import GameTreeCursor, VariationStep
from acs.pgn_document import (
    PgnDocumentContext,
    PgnDocumentError,
    PgnDocumentErrorCode,
    PgnDocumentSession,
)


DOCUMENT = '''[Event "First"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 e5 (1... c5 {Sicilian} 2. Nf3 (2... d6) 2... Nc6) (1... c6 2. d4) 2. Nf3 Nc6 1-0

[Event "Custom black start"]
[White "Gamma"]
[Black "Delta"]
[SetUp "1"]
[FEN "7k/8/8/8/8/8/5K2/8 b - - 0 23"]
[Result "*"]

23... Kg7 24. Ke3 *
'''


class PgnDocumentContextAtomicityTests(unittest.TestCase):
    def assert_context_rejected_without_mutation(
        self,
        session: PgnDocumentSession,
        context: PgnDocumentContext,
    ) -> None:
        before_text = session.copy_pgn()
        before_document_view = session.view()
        before_workspace_view = session.workspace.view()

        with self.assertRaises(PgnDocumentError) as caught:
            session.restore_context(context)

        self.assertEqual(caught.exception.code, PgnDocumentErrorCode.CONTEXT_STALE)
        self.assertEqual(session.copy_pgn(), before_text)
        self.assertEqual(session.view(), before_document_view)
        self.assertEqual(session.workspace.view(), before_workspace_view)

    def test_stale_digest_leaves_current_document_and_view_exactly_unchanged(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        session.workspace.set_cursor(GameTreeCursor((), 2))
        stale = session.bookmark()

        session.edit_tag("Event", "Edited after bookmark")
        session.workspace.select_game(1)
        session.workspace.set_cursor(GameTreeCursor((), 1))

        self.assert_context_rejected_without_mutation(session, stale)

    def test_invalid_saved_cursor_does_not_partially_switch_selected_game(self) -> None:
        invalid_cursors = (
            GameTreeCursor((), 999),
            GameTreeCursor((VariationStep(0, 0),), 0),
        )
        for invalid_cursor in invalid_cursors:
            with self.subTest(cursor=invalid_cursor):
                session = PgnDocumentSession.from_text(DOCUMENT)
                session.workspace.set_cursor(GameTreeCursor((), 2))
                before = session.workspace.view()

                forged = PgnDocumentContext(
                    content_digest=before.content_digest,
                    selected_game_index=1,
                    cursor=invalid_cursor,
                )

                self.assert_context_rejected_without_mutation(session, forged)

    def test_invalid_saved_game_index_does_not_mutate_current_location(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        session.workspace.select_game(1)
        session.workspace.set_cursor(GameTreeCursor((), 1))
        before = session.workspace.view()

        forged = PgnDocumentContext(
            content_digest=before.content_digest,
            selected_game_index=99,
            cursor=GameTreeCursor(),
        )

        self.assert_context_rejected_without_mutation(session, forged)

    def test_nested_variation_restore_crosses_game_index_and_is_repeatable(self) -> None:
        session = PgnDocumentSession.from_text(DOCUMENT)
        nested_cursor = GameTreeCursor(
            (VariationStep(1, 0), VariationStep(1, 0)),
            0,
        )
        session.workspace.set_cursor(nested_cursor)
        bookmark = session.bookmark()

        session.workspace.select_game(1)
        session.workspace.set_cursor(GameTreeCursor((), 1))
        first = session.restore_context(bookmark)
        self.assertEqual(first.selected_game_index, 0)
        self.assertEqual(first.cursor, nested_cursor)
        self.assertEqual(session.workspace.current_move().san, "d6")

        session.workspace.document_end()
        second = session.restore_context(bookmark)
        self.assertEqual(second.selected_game_index, 0)
        self.assertEqual(second.cursor, nested_cursor)
        self.assertEqual(session.workspace.current_move().san, "d6")

        third = session.restore_context(bookmark)
        self.assertEqual(third, second)
        self.assertEqual(session.workspace.current_move().san, "d6")

    def test_black_to_move_context_survives_save_and_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "black custom start.pgn"
            path.write_text(DOCUMENT, encoding="utf-8", newline="\n")

            session = PgnDocumentSession.open(path)
            session.workspace.select_game(1)
            session.workspace.set_cursor(GameTreeCursor((), 0))
            bookmark = session.bookmark()

            session.workspace.select_game(0)
            restored = session.restore_context(bookmark)
            self.assertEqual(restored.selected_game_index, 1)
            self.assertEqual(restored.cursor, GameTreeCursor((), 0))
            self.assertEqual(session.workspace.current_move().san, "Kg7")
            game = session.workspace.current_game()
            self.assertEqual(game.tags["SetUp"], "1")
            self.assertEqual(
                game.tags["FEN"],
                "7k/8/8/8/8/8/5K2/8 b - - 0 23",
            )
            self.assertEqual(game.line.moves[0].move_number, "23...")

            session.save()
            saved_text = session.copy_pgn()
            session.workspace.select_game(0)
            session.restore_context(bookmark)
            self.assertEqual(session.workspace.current_move().san, "Kg7")

            reopened = PgnDocumentSession.open(path)
            self.assertEqual(reopened.copy_pgn(), saved_text)
            reopened.workspace.select_game(0)
            reopened_restore = reopened.restore_context(bookmark)
            self.assertEqual(reopened_restore.selected_game_index, 1)
            self.assertEqual(reopened_restore.cursor, GameTreeCursor((), 0))
            self.assertEqual(reopened.workspace.current_move().san, "Kg7")
            reopened_game = reopened.workspace.current_game()
            self.assertEqual(reopened_game.tags["SetUp"], "1")
            self.assertEqual(
                reopened_game.tags["FEN"],
                "7k/8/8/8/8/8/5K2/8 b - - 0 23",
            )


if __name__ == "__main__":
    unittest.main()
