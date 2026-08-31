from __future__ import annotations

import unittest

from acs.bookdocument import (
    BookDocument,
    BookDocumentError,
    BookDocumentErrorCode,
    Diagram,
    VariationTree,
)
from acs.bookreader import BookReader
from acs.chesscore import Board


ORIGINAL_AUDIT_INVALID_FEN = "8/8/8/8/8/8/8/8 w - - 0 1"
VALID_FULL_FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"
VALID_COMPACT_FEN = "8/8/8/8/8/8/4K3/7k w - -"


class V2AuditBBookFenOwnerAcceptanceTests(unittest.TestCase):
    def test_original_zero_king_audit_fen_is_rejected_before_diagram_publication(self) -> None:
        with self.assertRaises(BookDocumentError) as caught:
            BookDocument(
                "FEN boundary",
                blocks=[
                    Diagram(
                        fen=ORIGINAL_AUDIT_INVALID_FEN,
                        caption="Invalid canonical position",
                        alt_text="Empty board.",
                        block_id="diagram",
                    )
                ],
            )
        self.assertEqual(caught.exception.code, BookDocumentErrorCode.INVALID_FIELD)

    def test_original_zero_king_audit_fen_is_rejected_before_variation_publication(self) -> None:
        with self.assertRaises(BookDocumentError) as caught:
            VariationTree(
                pgn="1. e4 e5 *",
                root_fen=ORIGINAL_AUDIT_INVALID_FEN,
                block_id="variation",
            )
        self.assertEqual(caught.exception.code, BookDocumentErrorCode.INVALID_FIELD)

    def test_valid_canonical_fen_remains_bookreader_and_board_compatible(self) -> None:
        canonical = Board(VALID_FULL_FEN).fen()
        self.assertEqual(canonical, VALID_FULL_FEN)

        document = BookDocument(
            "Valid FEN boundary",
            blocks=[
                Diagram(
                    fen=VALID_FULL_FEN,
                    caption="Canonical position",
                    alt_text="White king e2; black king h1.",
                    block_id="diagram",
                )
            ],
        )
        location = BookReader(document).location()
        self.assertEqual(location.position_fen, VALID_FULL_FEN)
        self.assertEqual(Board(location.position_fen).fen(), canonical)

    def test_historical_four_field_wire_form_uses_same_board_validation(self) -> None:
        board = Board(VALID_COMPACT_FEN)
        self.assertEqual(board.fen(), VALID_FULL_FEN)

        diagram = Diagram(
            fen=VALID_COMPACT_FEN,
            caption="Compact canonical position",
            alt_text="White king e2; black king h1.",
            block_id="diagram-compact",
        )
        self.assertEqual(diagram.fen, VALID_COMPACT_FEN)
        self.assertEqual(Board(diagram.fen).fen(), board.fen())


if __name__ == "__main__":
    unittest.main()
