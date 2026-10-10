from __future__ import annotations

"""Section 54.4: canonical legality is never mistaken for source fidelity."""

import unittest

from acs.bookdocument import BookDocument, Diagram, Game, Paragraph, Position, VariationTree
from acs.chesscore import Board
from acs.format_factory_chess_audit import (
    FactoryChessAuditError, audit_factory_book_chess,
)


def game(moves: str, extra_tags: str = "") -> Game:
    return Game(pgn='[Event "Lesson"]\n[Result "*"]\n' + extra_tags + '\n' + moves)


class FactoryChessAuditTests(unittest.TestCase):
    def test_game_and_position_use_existing_canonical_chess(self) -> None:
        doc = BookDocument(title="Study", blocks=[
            Paragraph(text="Intro"),
            game("1. e4 e5 2. Nf3 Nc6 *"),
            Position(fen=Board().fen()),
        ])
        report = audit_factory_book_chess(doc)
        self.assertEqual(report.chess_blocks, 2)
        self.assertEqual(report.legal_chess_blocks, 2)
        self.assertEqual(report.invalid_chess_blocks, 0)
        self.assertEqual([x.block_index for x in report.blocks], [1, 2])
        self.assertTrue(report.structure_complete)
        self.assertTrue(all(x.status == "CHESS_LEGAL_ONLY" for x in report.blocks))
        self.assertEqual(report.blocks[0].legal_moves, 4)
        self.assertFalse(report.source_verified)
        self.assertFalse(report.ready_for_publication)
        self.assertTrue(all(not x.source_verified for x in report.blocks))

    def test_illegal_but_syntactically_valid_move_is_rejected(self) -> None:
        doc = BookDocument(title="Wrong move", blocks=[
            game("1. e4 e5 2. Bh5 *"),
        ])
        report = audit_factory_book_chess(doc)
        self.assertEqual(report.chess_blocks, 1)
        self.assertEqual(report.invalid_chess_blocks, 1)
        self.assertEqual(report.blocks[0].status, "INVALID_CHESS_STRUCTURE")
        self.assertFalse(report.structure_complete)
        self.assertFalse(report.ready_for_publication)

    def test_one_illegal_branch_blocks_a_mainline_that_is_legal(self) -> None:
        doc = BookDocument(title="Bad alternative", blocks=[
            game("1. e4 (1. d4 d5 2. Bh5) e5 *"),
        ])
        report = audit_factory_book_chess(doc)
        self.assertEqual(report.chess_blocks, 1)
        self.assertEqual(report.invalid_chess_blocks, 1)
        self.assertEqual(report.blocks[0].status, "INVALID_CHESS_STRUCTURE")
        self.assertTrue(report.blocks[0].issue_codes)
        self.assertFalse(report.ready_for_publication)

    def test_unsupported_game_variant_fails_closed(self) -> None:
        doc = BookDocument(title="Different rules", blocks=[
            game('1. e4 *', '[Variant "Chess960"]\n'),
        ])
        report = audit_factory_book_chess(doc)
        self.assertEqual(report.invalid_chess_blocks, 1)
        self.assertIn("unsupported_variant", report.blocks[0].issue_codes)

    def test_variation_uses_authored_start_position(self) -> None:
        doc = BookDocument(title="Variation", blocks=[
            VariationTree(
                root_fen=Board().fen(),
                pgn='[Event "Line"]\n[Result "*"]\n\n1. e4 e5 *',
            ),
        ])
        report = audit_factory_book_chess(doc)
        self.assertEqual(report.chess_blocks, 1)
        self.assertEqual(report.invalid_chess_blocks, 0)
        self.assertEqual(report.blocks[0].legal_moves, 2)
        self.assertFalse(report.ready_for_publication)

    def test_position_diagram_and_plain_text_remain_distinct(self) -> None:
        doc = BookDocument(title="Position", blocks=[
            Paragraph(text="This text is not chess legality evidence"),
            Diagram(fen=Board().fen(), caption="Start", alt_text="Board setup"),
        ])
        report = audit_factory_book_chess(doc)
        self.assertEqual(len(report.blocks), 1)
        self.assertEqual(report.blocks[0].kind, "Diagram")
        self.assertEqual(report.blocks[0].status, "CHESS_LEGAL_ONLY")
        self.assertFalse(report.blocks[0].source_verified)
        self.assertFalse(report.ready_for_publication)

    def test_corrupted_document_and_invalid_limits_fail_before_publication(self) -> None:
        doc = BookDocument(title="Source", blocks=[game("1. e4 e5 *")])
        first = audit_factory_book_chess(doc)
        self.assertEqual(first, audit_factory_book_chess(doc))
        with self.assertRaises(FactoryChessAuditError):
            audit_factory_book_chess(doc, max_blocks=False)
        with self.assertRaises(FactoryChessAuditError):
            audit_factory_book_chess(doc, max_blocks=0)
        with self.assertRaises(FactoryChessAuditError):
            audit_factory_book_chess(doc, max_blocks=4097)
        with self.assertRaises(FactoryChessAuditError):
            audit_factory_book_chess(doc, max_blocks=1 - 1)
        doc.blocks[0].pgn = ""
        with self.assertRaises(FactoryChessAuditError):
            audit_factory_book_chess(doc)


if __name__ == "__main__":
    unittest.main()
