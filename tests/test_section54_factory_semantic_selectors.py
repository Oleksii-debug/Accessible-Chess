from __future__ import annotations

"""Selected chess items use only explicit semantic source order, not invented pages."""

from hashlib import sha256
import unittest

from acs.format_factory_conversion import FactoryConversionError, convert_factory_book_private
from acs.format_factory_policy import FactoryJobPolicy, FactorySelection


FEN_START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
FEN_AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
POSITIONS = (
    "# Lesson\n\n"
    "```fen\n" + FEN_START + "\n```\n\n"
    "```diagram-fen\n" + FEN_AFTER_E4 + "\n```\n"
).encode("utf-8")
GAMES = (
    '[Event "First"]\n[White "A"]\n[Black "B"]\n[Result "*"]\n\n'
    '1. e4 e5 *\n\n'
    '[Event "Second"]\n[White "C"]\n[Black "D"]\n[Result "*"]\n\n'
    '1. d4 d5 *\n'
).encode("utf-8")


def make_policy(source: bytes, kind: str, ranges: str) -> FactoryJobPolicy:
    return FactoryJobPolicy(
        source_sha256=sha256(source).hexdigest(),
        source_id="selected-book",
        selection=FactorySelection.from_text(kind, ranges),
        output_formats=("html",),
        output_language="en",
    )


class SemanticSelectionTests(unittest.TestCase):
    def convert(self, source: bytes, name: str, kind: str, ranges: str):
        return convert_factory_book_private(
            source, source_name=name,
            policy=make_policy(source, kind, ranges),
            source_language="en",
        )

    def test_second_position_is_only_second_semantic_position(self):
        result = self.convert(POSITIONS, "positions.md", "positions", "2")
        body = result.outputs[0].output_bytes.decode("utf-8")
        self.assertIn(FEN_AFTER_E4, body)
        self.assertNotIn(FEN_START, body)
        self.assertEqual(result.selected_block_count, 1)
        self.assertEqual(result.chess_audit.legal_chess_blocks, 1)
        self.assertFalse(result.chess_audit.source_verified)

    def test_diagram_selector_excludes_non_diagram_positions(self):
        result = self.convert(POSITIONS, "positions.md", "diagrams", "1")
        body = result.outputs[0].output_bytes.decode("utf-8")
        self.assertIn(FEN_AFTER_E4, body)
        self.assertNotIn(FEN_START, body)
        self.assertIn("<figure", body)

    def test_second_game_selection_keeps_its_own_moves_and_annotations(self):
        result = self.convert(GAMES, "collection.pgn", "games", "2")
        body = result.outputs[0].output_bytes.decode("utf-8")
        self.assertIn("1. d4 d5", body)
        self.assertNotIn("1. e4 e5", body)
        self.assertEqual(result.selected_block_count, 1)
        self.assertEqual(result.chess_audit.legal_chess_blocks, 1)

    def test_missing_semantic_index_and_unanchored_pages_fail_closed(self):
        for kind, ranges in (
            ("positions", "3"),
            ("diagrams", "2"),
            ("games", "1"),
            ("printed_pages", "1"),
            ("file_pages", "1"),
        ):
            with self.subTest(kind=kind, ranges=ranges):
                with self.assertRaises(FactoryConversionError):
                    self.convert(POSITIONS, "positions.md", kind, ranges)


if __name__ == "__main__":
    unittest.main()
