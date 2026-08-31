from __future__ import annotations

import unittest

from acs.gametree import CommentStyle
from acs.gametree_legality import validate_game_legality
from acs.pgn_roundtrip import (
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    canonical_round_trip_text,
    parse_pgn_text,
    serialize_pgn_text,
)


class V2PgnSemanticFidelityTests(unittest.TestCase):
    def assert_semantic_round_trip(self, source: str):
        games = parse_pgn_text(source, strict=True)
        serialized = serialize_pgn_text(games)
        reopened = parse_pgn_text(serialized, strict=True)
        self.assertEqual(reopened, games)
        self.assertEqual(canonical_round_trip_text(source).games, games)
        return games, serialized

    def test_import_tag_pair_whitespace_escapes_unknown_tag_and_unicode(self) -> None:
        source = (
            r' [ Event"Live \"Rapid\" \\ Final" ]' "\r\n"
            r'[ X_Custom "Україна ♟" ]' "\r\n"
            r'[Result"*"]' "\r\n\r\n"
            "\t1.\te4\t*\r\n"
        )

        games, serialized = self.assert_semantic_round_trip(source)
        game = games[0]
        self.assertEqual(game.tags["Event"], 'Live "Rapid" \\ Final')
        self.assertEqual(game.tags["X_Custom"], "Україна ♟")
        self.assertIn('[Event "Live \\"Rapid\\" \\\\ Final"]', serialized)
        self.assertIn('[X_Custom "Україна ♟"]', serialized)

    def test_duplicate_tag_is_recovery_only_but_unknown_tag_is_preserved(self) -> None:
        source = (
            '[Event "First"]\n'
            '[Event "Second"]\n'
            '[EngineNote "opaque but supported metadata"]\n'
            '[Result "*"]\n\n'
            '1. e4 *\n'
        )
        with self.assertRaises(PgnRoundTripError) as caught:
            parse_pgn_text(source, strict=True)
        self.assertEqual(caught.exception.code, PgnRoundTripErrorCode.MALFORMED_PGN)

        recovered = parse_pgn_text(source, strict=False)[0]
        self.assertEqual(recovered.tags["Event"], "Second")
        self.assertEqual(recovered.tags["EngineNote"], "opaque but supported metadata")
        self.assertTrue(any("duplicate tag Event" in item for item in recovered.warnings))

    def test_comment_slots_numeric_and_symbolic_annotations_nested_rav_round_trip(self) -> None:
        source = (
            '[Event "Annotated"]\n'
            '[Result "*"]\n\n'
            ';root lead\n'
            '1. {before e4} e4$1 {after e4} '
            'e5$14 (1... c5!? {Sicilian} 2. Nf3 d6$5 (2... Nc6?! {nested})) '
            '2. Nf3 ;after Nf3\n'
            ' Nc6$255 * ;root tail\n'
        )

        games, _ = self.assert_semantic_round_trip(source)
        game = games[0]
        self.assertEqual(game.line.leading_comments[0].text, "root lead")
        self.assertEqual(game.line.leading_comments[0].style, CommentStyle.SEMICOLON)
        self.assertEqual(game.line.moves[0].comments_before[0].text, "before e4")
        self.assertEqual(game.line.moves[0].comments_after[0].text, "after e4")
        self.assertEqual(game.line.moves[0].nags, ["$1"])
        self.assertEqual(game.line.moves[1].nags, ["$14"])
        variation = game.line.moves[1].variations[0]
        self.assertEqual(variation.moves[0].san, "c5")
        self.assertEqual(variation.moves[0].nags, ["!?"])
        self.assertEqual(variation.moves[1].nags, ["$5"])
        nested = variation.moves[1].variations[0]
        self.assertEqual(nested.moves[0].san, "Nc6")
        self.assertEqual(nested.moves[0].nags, ["?!"])
        self.assertEqual(game.line.moves[2].comments_after[0].text, "after Nf3")
        self.assertEqual(game.line.moves[3].nags, ["$255"])
        self.assertEqual(game.line.trailing_comments[0].text, "root tail")
        self.assertEqual(game.line.trailing_comments[0].style, CommentStyle.SEMICOLON)

        legality = validate_game_legality(game)
        self.assertTrue(legality.complete, legality.issues)
        self.assertFalse(legality.issues)

    def test_numeric_nag_out_of_range_fails_closed_on_parse_and_serialize(self) -> None:
        with self.assertRaises(PgnRoundTripError) as caught:
            parse_pgn_text('[Result "*"]\n\n1. e4$256 *\n', strict=True)
        self.assertEqual(caught.exception.code, PgnRoundTripErrorCode.INVALID_NAG)

        game = parse_pgn_text('[Result "*"]\n\n1. e4$255 *\n', strict=True)[0]
        game.line.moves[0].nags = ["$999"]
        with self.assertRaises(PgnRoundTripError) as caught:
            serialize_pgn_text((game,))
        self.assertEqual(caught.exception.code, PgnRoundTripErrorCode.INVALID_NAG)

    def test_black_to_move_setup_fen_preserves_fullmove_and_is_legal(self) -> None:
        source = (
            '[Event "Black to move"]\n'
            '[SetUp "1"]\n'
            '[FEN "7k/8/8/8/8/8/5K2/8 b - - 0 23"]\n'
            '[Result "*"]\n\n'
            '23... Kg7 24. Ke3 *\n'
        )

        games, serialized = self.assert_semantic_round_trip(source)
        game = games[0]
        self.assertEqual(game.tags["SetUp"], "1")
        self.assertEqual(game.tags["FEN"].split()[-1], "23")
        self.assertEqual(game.line.moves[0].move_number, "23...")
        self.assertIn("23... Kg7", serialized)
        legality = validate_game_legality(game)
        self.assertTrue(legality.complete, legality.issues)
        self.assertFalse(legality.issues)

    def test_promotion_and_all_underpromotion_piece_choices_round_trip_legally(self) -> None:
        cases = (
            ("a8=Q+", "Q"),
            ("a8=R+", "R"),
            ("a8=B", "B"),
            ("a8=N", "N"),
        )
        for san, promoted in cases:
            with self.subTest(promotion=promoted):
                source = (
                    '[SetUp "1"]\n'
                    '[FEN "7k/P7/8/8/8/8/8/7K w - - 0 1"]\n'
                    '[Result "*"]\n\n'
                    f'1. {san} *\n'
                )
                games, _ = self.assert_semantic_round_trip(source)
                legality = validate_game_legality(games[0])
                self.assertTrue(legality.complete, legality.issues)
                self.assertFalse(legality.issues)
                self.assertEqual(games[0].line.moves[0].san, san)

    def test_long_legal_san_sequence_round_trips_without_state_drift(self) -> None:
        move_text: list[str] = []
        fullmoves = 60
        for number in range(1, fullmoves + 1):
            if number % 2:
                white, black = "Nf3", "Nf6"
            else:
                white, black = "Ng1", "Ng8"
            move_text.append(f"{number}. {white} {black}")
        source = '[Event "Long legal sequence"]\n[Result "*"]\n\n' + " ".join(move_text) + ' *\n'

        games, _ = self.assert_semantic_round_trip(source)
        legality = validate_game_legality(games[0])
        self.assertTrue(legality.complete, legality.issues)
        self.assertFalse(legality.issues)
        self.assertEqual(legality.legal_move_count, fullmoves * 2)

    def test_incomplete_result_and_malformed_boundaries_are_fail_closed(self) -> None:
        incomplete = '[Event "Incomplete"]\n[Result "*"]\n\n1. e4 *\n'
        games, _ = self.assert_semantic_round_trip(incomplete)
        self.assertEqual(games[0].result, "*")

        invalid_sources = (
            '[Result "1-0"]\n\n1. e4 0-1\n',
            '[Result "*"]\n\n1. e4 e5\n',
            '[Result "*"]\n\n1. e4 (1... c5 *\n',
            '[Result "*"]\n\n1. e4 * trailing\n',
            '[Result "*"]\n\n1. e4$ *\n',
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(PgnRoundTripError):
                    parse_pgn_text(source, strict=True)


if __name__ == "__main__":
    unittest.main()
