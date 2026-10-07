from __future__ import annotations

import unittest

from acs.chesscore import Board
from acs.input_limits import MAX_SAN_CHARS
from acs.notation import MAX_SAN_CHARS as NOTATION_MAX_SAN_CHARS, format_san


class Section1SanTransitionContractTests(unittest.TestCase):
    def test_notation_and_legality_share_one_raw_san_budget(self) -> None:
        self.assertEqual(MAX_SAN_CHARS, 64)
        self.assertEqual(NOTATION_MAX_SAN_CHARS, MAX_SAN_CHARS)

        board = Board()
        before = board.fen()
        undo_before = list(board.undo_stack)
        redo_before = list(board.redo_stack)
        last_before = board.last_move
        oversized = " " * (MAX_SAN_CHARS + 1)

        for operation in (
            Board.norm_san,
            board.parse_move,
            board.push_text,
        ):
            with self.subTest(operation=getattr(operation, "__name__", repr(operation))):
                with self.assertRaisesRegex(ValueError, "занадто довгий"):
                    operation(oversized)
                self.assertEqual(board.fen(), before)
                self.assertEqual(board.undo_stack, undo_before)
                self.assertEqual(board.redo_stack, redo_before)
                self.assertEqual(board.last_move, last_before)

    def test_active_text_is_rejected_before_length_or_normalization_hooks(self) -> None:
        class ActiveText(str):
            def __len__(self):
                raise AssertionError("length hook must not run")

            def strip(self, *args, **kwargs):
                raise AssertionError("strip hook must not run")

        board = Board()
        hostile = ActiveText("e4")
        for operation in (Board.norm_san, board.parse_move, board.push_text):
            with self.subTest(operation=getattr(operation, "__name__", repr(operation))):
                with self.assertRaisesRegex(ValueError, "текстом"):
                    operation(hostile)

    def test_generated_san_is_one_grammar_and_round_trips_to_same_move(self) -> None:
        # Each fixture targets a Section 1 transition edge while Board remains
        # the only legality authority: castling, en-passant, promotion and
        # source-square disambiguation.
        fens = (
            "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
            "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2",
            "4k3/P7/8/8/8/8/8/4K3 w - - 0 1",
            "4k3/8/8/8/8/8/8/1N2KN2 w - - 0 1",
        )
        saw = {
            "castle": False,
            "en_passant": False,
            "promotion": False,
            "disambiguation": False,
        }

        for fen in fens:
            board = Board(fen)
            for move in board.legal_moves():
                san = board.san(move)
                self.assertEqual(format_san(san, "san"), san)
                self.assertEqual(board.parse_move(san), move)

                if move.castle:
                    saw["castle"] = True
                if move.en_passant:
                    saw["en_passant"] = True
                if move.promotion:
                    saw["promotion"] = True
                if san.startswith(("Nb", "Nf")) and san.endswith("d2"):
                    saw["disambiguation"] = True

                candidate = board.clone()
                before = candidate.fen()
                pushed_san = candidate.push(move)
                after = candidate.fen()
                self.assertEqual(pushed_san, san)
                self.assertNotEqual(after, before)
                self.assertEqual(Board(after).fen(), after)

                self.assertEqual(candidate.undo(), san)
                self.assertEqual(candidate.fen(), before)
                self.assertEqual(candidate.redo(), san)
                self.assertEqual(candidate.fen(), after)

        self.assertTrue(all(saw.values()), saw)

    def test_explicit_check_suffix_must_match_canonical_board_san(self) -> None:
        board = Board()
        before = board.fen()

        # e4 is legal, but neither check nor mate.  A false semantic suffix
        # must not be silently discarded by the canonical legality boundary.
        for token in ("e4+", "e4#"):
            with self.subTest(token=token):
                with self.assertRaisesRegex(ValueError, "не вдалося|нелегальний"):
                    board.parse_move(token)
                with self.assertRaisesRegex(ValueError, "не вдалося|нелегальний"):
                    board.push_text(token)
                self.assertEqual(board.fen(), before)

        # Missing suffix remains accepted as historical human-input
        # convenience, while an explicitly wrong suffix is rejected.
        for token in ("f3", "e5", "g4"):
            board.push_text(token)
        mate = board.parse_move("Qh4#")
        self.assertEqual(board.san(mate), "Qh4#")
        self.assertEqual(board.parse_move("Qh4"), mate)
        with self.assertRaisesRegex(ValueError, "не вдалося|нелегальний"):
            board.parse_move("Qh4+")

    def test_checkmate_suffix_is_canonical_and_replayable(self) -> None:
        board = Board()
        for token in ("f3", "e5", "g4"):
            board.push_text(token)

        mate = board.parse_move("Qh4#")
        self.assertEqual(board.san(mate), "Qh4#")
        self.assertEqual(format_san("Qh4#", "san"), "Qh4#")

        before = board.fen()
        self.assertEqual(board.push(mate), "Qh4#")
        self.assertNotEqual(board.fen(), before)
        self.assertEqual(board.legal_moves(), [])


if __name__ == "__main__":
    unittest.main()
