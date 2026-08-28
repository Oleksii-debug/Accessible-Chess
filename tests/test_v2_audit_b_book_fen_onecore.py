from __future__ import annotations

import unittest

from acs.bookdocument import BookDocument, Diagram, VariationTree
from acs.bookreader import BookReader
from acs.chesscore import Board


INVALID_CANONICAL_FEN = "8/8/8/8/8/8/8/8 w - - 0 1"


class V2AuditBBookFenOneCoreTests(unittest.TestCase):
    def test_book_diagram_fen_must_be_canonical_board_valid(self) -> None:
        document = BookDocument(
            "FEN boundary",
            blocks=[
                Diagram(
                    fen=INVALID_CANONICAL_FEN,
                    caption="Invalid canonical position",
                    alt_text="Empty board.",
                    block_id="diagram",
                )
            ],
        )
        reader = BookReader(document)
        location = reader.location()
        self.assertEqual(location.position_fen, INVALID_CANONICAL_FEN)

        board = Board()
        try:
            board.set_fen(location.position_fen)
        except ValueError as exc:
            self.fail(
                "AB-V2-008: BookDocument accepted a Diagram FEN that canonical Board rejects: "
                f"{exc}"
            )

    def test_book_variation_root_fen_must_be_canonical_board_valid(self) -> None:
        document = BookDocument(
            "Variation FEN boundary",
            blocks=[
                VariationTree(
                    pgn="1. e4 e5 *",
                    root_fen=INVALID_CANONICAL_FEN,
                    block_id="variation",
                )
            ],
        )
        block = document.blocks[0]
        self.assertEqual(block.root_fen, INVALID_CANONICAL_FEN)

        board = Board()
        try:
            board.set_fen(block.root_fen)
        except ValueError as exc:
            self.fail(
                "AB-V2-008: Book VariationTree accepted a root FEN outside canonical Board policy: "
                f"{exc}"
            )


if __name__ == "__main__":
    unittest.main()
