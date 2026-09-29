from __future__ import annotations

import unittest

from acs.pgn_document import PgnDocumentError, PgnDocumentErrorCode, PgnDocumentSession


CUSTOM_POSITION = """[Event "Custom black start"]
[SetUp "1"]
[FEN "7k/8/8/8/8/8/5K2/8 b - - 0 23"]
[Result "*"]

23... Kg7 24. Ke3 *
"""


class PgnDocumentNewGamePositionIntegrityTests(unittest.TestCase):
    def test_generic_new_game_tags_cannot_create_or_split_start_position(self) -> None:
        fen = "7k/8/8/8/8/8/5K2/8 b - - 0 23"
        cases = (
            {"SetUp": "1"},
            {"FEN": fen},
            {"SetUp": "1", "FEN": fen},
        )

        for supplied in cases:
            with self.subTest(tags=supplied):
                original = dict(supplied)
                with self.assertRaises(PgnDocumentError) as caught:
                    PgnDocumentSession.new_game(supplied)
                self.assertEqual(caught.exception.code, PgnDocumentErrorCode.INVALID_TAG)
                self.assertEqual(supplied, original)

    def test_generic_new_game_still_accepts_descriptive_metadata(self) -> None:
        session = PgnDocumentSession.new_game(
            {
                "Event": "Fresh analysis",
                "White": "Alpha",
                "Black": "Beta",
                "Annotator": "Accessible Chess",
                "Result": "*",
            }
        )

        game = session.workspace.current_game()
        self.assertEqual(game.tags["Event"], "Fresh analysis")
        self.assertEqual(game.tags["White"], "Alpha")
        self.assertEqual(game.tags["Black"], "Beta")
        self.assertEqual(game.tags["Annotator"], "Accessible Chess")
        self.assertNotIn("SetUp", game.tags)
        self.assertNotIn("FEN", game.tags)

    def test_existing_canonical_custom_start_pgn_ingress_is_unchanged(self) -> None:
        session = PgnDocumentSession.from_text(CUSTOM_POSITION)
        game = session.workspace.current_game()

        self.assertEqual(game.tags["SetUp"], "1")
        self.assertEqual(
            game.tags["FEN"],
            "7k/8/8/8/8/8/5K2/8 b - - 0 23",
        )
        self.assertEqual(game.line.moves[0].move_number, "23...")
        self.assertEqual(game.line.moves[0].san, "Kg7")


if __name__ == "__main__":
    unittest.main()
