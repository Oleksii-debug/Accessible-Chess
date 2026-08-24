import codecs
import unittest
from unittest.mock import patch

from acs.gametree import Comment, CommentStyle, MoveNode, PgnGame, VariationLine
from acs.pgn_roundtrip import (
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    canonical_round_trip_bytes,
    canonical_round_trip_text,
    decode_pgn_bytes,
    parse_pgn_bytes,
    parse_pgn_text,
    serialize_pgn_bytes,
    serialize_pgn_text,
)


REALISTIC_CORPUS = '''[Event "D06 nested corpus"]
[Site "Uzhhorod"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 {main idea} e5 $1 (1... c5!? {Sicilian} 2. Nf3 (2... d6?! {nested}) 2... Nc6) 2. Nf3 Nc6 *

[Event "SetUp corpus"]
[SetUp "1"]
[FEN "rnbqkbnr/pp1ppppp/8/2p5/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 2"]
[Annotator "Олексій \\"D06\\""]
[Result "0-1"]

2. d4 ;line comment
 cxd4 0-1
'''


class D06PgnRoundTripTests(unittest.TestCase):
    def assert_code(self, code, callable_, *args, **kwargs):
        with self.assertRaises(PgnRoundTripError) as caught:
            callable_(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_realistic_multigame_parse_edit_write_reparse_equivalence(self):
        games = parse_pgn_text(REALISTIC_CORPUS)
        self.assertEqual(len(games), 2)
        self.assertEqual(games[0].tags["Event"], "D06 nested corpus")
        self.assertEqual(games[1].tags["SetUp"], "1")
        self.assertEqual(games[1].tags["FEN"].split()[1], "w")

        sicilian = games[0].line.moves[1].variations[0]
        self.assertEqual(sicilian.moves[0].san, "c5")
        self.assertIn("!?", sicilian.moves[0].nags)
        nested = sicilian.moves[1].variations[0]
        self.assertEqual(nested.moves[0].san, "d6")
        self.assertIn("?!", nested.moves[0].nags)

        # Simulate an editing-persistence operation without touching canonical
        # legality/Position ownership: edit metadata and a nested annotation,
        # then prove write -> strict reparse structural equivalence.
        games[0].tags["Annotator"] = "D06 round-trip"
        sicilian.moves[0].comments_after.append(
            Comment("edited nested comment", CommentStyle.BRACE)
        )
        serialized = serialize_pgn_text(games)
        reparsed = parse_pgn_text(serialized)
        self.assertEqual(reparsed, games)
        self.assertEqual(
            reparsed[0].line.moves[1].variations[0].moves[0].comments_after[-1].text,
            "edited nested comment",
        )

    def test_canonical_round_trip_normalizes_attached_symbolic_nag_without_loss(self):
        source = '[Event "NAG"]\n[Result "*"]\n\n1. Nf3!? d5 2. e4! *\n'
        result = canonical_round_trip_text(source)

        self.assertIn("Nf3 !?", result.text)
        self.assertIn("e4 !", result.text)
        self.assertEqual(result.games[0].line.moves[0].san, "Nf3")
        self.assertEqual(result.games[0].line.moves[0].nags, ["!?"])
        self.assertEqual(result.games[0].line.moves[2].nags, ["!"])

    def test_utf8_bom_is_supported_but_invalid_utf8_fails_closed(self):
        payload = codecs.BOM_UTF8 + '[Event "UTF8"]\n[Result "*"]\n\n1. e4 *\n'.encode("utf-8")
        decoded = decode_pgn_bytes(payload)
        self.assertTrue(decoded.startswith('[Event "UTF8"]'))
        self.assertEqual(len(parse_pgn_bytes(payload)), 1)

        error = self.assert_code(
            PgnRoundTripErrorCode.INVALID_ENCODING,
            parse_pgn_bytes,
            b'[Event "bad"]\n\xff\n',
        )
        self.assertNotIn("codec", str(error).lower())
        self.assertNotIn("position", str(error).lower())

    def test_bytes_round_trip_is_deterministic_utf8(self):
        source = codecs.BOM_UTF8 + REALISTIC_CORPUS.encode("utf-8")
        encoded, games = canonical_round_trip_bytes(source)
        self.assertFalse(encoded.startswith(codecs.BOM_UTF8))
        self.assertEqual(parse_pgn_bytes(encoded), games)
        self.assertEqual(serialize_pgn_bytes(games), encoded)

    def test_strict_mode_rejects_every_recovery_only_loss_surface(self):
        cases = (
            (
                '[Event "First"]\n[Event "Second"]\n[Result "*"]\n\n1. e4 *',
                PgnRoundTripErrorCode.MALFORMED_PGN,
            ),
            (
                '[Event "Missing result"]\n[Result "*"]\n\n1. e4 e5',
                PgnRoundTripErrorCode.MALFORMED_PGN,
            ),
            (
                '[Result "*"]\n\n1. e4 ) e5 *',
                PgnRoundTripErrorCode.MALFORMED_PGN,
            ),
            (
                '[Result "*"]\n\n1. e4 {unterminated',
                PgnRoundTripErrorCode.MALFORMED_PGN,
            ),
            (
                '[Event broken]\n[Result "*"]\n\n1. e4 *',
                PgnRoundTripErrorCode.MALFORMED_HEADER,
            ),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assert_code(expected, parse_pgn_text, source)

    def test_strict_mode_rejects_tokens_that_recovery_parser_would_treat_as_san(self):
        for token in ("hello", "$oops", "[Event"):
            with self.subTest(token=token):
                source = f'[Result "*"]\n\n1. {token} *'
                expected = (
                    PgnRoundTripErrorCode.MALFORMED_HEADER
                    if token == "[Event"
                    else PgnRoundTripErrorCode.INVALID_SAN
                )
                self.assert_code(expected, parse_pgn_text, source)

    def test_recovery_mode_remains_available_for_read_only_damaged_inspection(self):
        games = parse_pgn_text(
            '[Event "Damaged"]\n[Result "*"]\n\n1. e4 e5',
            strict=False,
        )
        self.assertEqual(len(games), 1)
        self.assertTrue(games[0].warnings)
        self.assertEqual([move.san for move in games[0].line.moves], ["e4", "e5"])

    def test_empty_input_fails_closed_for_strict_editing(self):
        self.assert_code(PgnRoundTripErrorCode.EMPTY_PGN, parse_pgn_text, "")
        self.assertEqual(parse_pgn_text("", strict=False), ())

    def test_parse_resource_bounds_are_enforced_before_unbounded_recovery(self):
        with patch("acs.pgn_roundtrip.MAX_PGN_COMMENT_CHARS", 5):
            self.assert_code(
                PgnRoundTripErrorCode.COMMENT_SIZE_LIMIT,
                parse_pgn_text,
                '[Result "*"]\n\n1. e4 {123456} *',
            )
        with patch("acs.pgn_roundtrip.MAX_PGN_TOKEN_CHARS", 4):
            self.assert_code(
                PgnRoundTripErrorCode.TOKEN_SIZE_LIMIT,
                parse_pgn_text,
                '[Result "*"]\n\n1. Nf3++ *',
            )
        with patch("acs.pgn_roundtrip.MAX_PGN_LEXICAL_TOKENS", 3):
            self.assert_code(
                PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT,
                parse_pgn_text,
                '[Result "*"]\n\n1. e4 *',
            )
        with patch("acs.pgn_roundtrip.MAX_PGN_TEXT_CHARS", 12):
            self.assert_code(
                PgnRoundTripErrorCode.TEXT_SIZE_LIMIT,
                parse_pgn_text,
                '[Result "*"]\n\n*',
            )
        with patch("acs.pgn_roundtrip.MAX_PGN_SOURCE_BYTES", 8):
            self.assert_code(
                PgnRoundTripErrorCode.BYTE_SIZE_LIMIT,
                decode_pgn_bytes,
                b'[Result "*"]',
            )

    def test_game_and_tag_count_bounds_are_independent(self):
        two_games = (
            '[Event "One"]\n[Result "*"]\n\n1. e4 *\n\n'
            '[Event "Two"]\n[Result "*"]\n\n1. d4 *\n'
        )
        with patch("acs.pgn_roundtrip.MAX_PGN_GAMES", 1):
            self.assert_code(
                PgnRoundTripErrorCode.GAME_COUNT_LIMIT,
                parse_pgn_text,
                two_games,
            )
        with patch("acs.pgn_roundtrip.MAX_PGN_TAGS_PER_GAME", 1):
            self.assert_code(
                PgnRoundTripErrorCode.TAG_COUNT_LIMIT,
                parse_pgn_text,
                '[Event "One"]\n[Result "*"]\n\n1. e4 *',
            )

    def test_serialization_preflight_rejects_oversized_models_before_building_payload(self):
        game = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[
                    MoveNode(
                        "e4",
                        move_number="1.",
                        comments_after=[Comment("abcdefghij")],
                    )
                ],
                result="*",
            ),
        )
        with patch("acs.pgn_roundtrip.MAX_PGN_COMMENT_CHARS", 5):
            self.assert_code(
                PgnRoundTripErrorCode.COMMENT_SIZE_LIMIT,
                serialize_pgn_text,
                (game,),
            )
        with patch("acs.pgn_roundtrip.MAX_PGN_TEXT_CHARS", 20):
            self.assert_code(
                PgnRoundTripErrorCode.TEXT_SIZE_LIMIT,
                serialize_pgn_text,
                (game,),
            )

    def test_programmatic_model_must_store_symbolic_nag_separately_from_san(self):
        game = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[MoveNode("Nf3!?", move_number="1.")],
                result="*",
            ),
        )
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_SAN,
            serialize_pgn_text,
            (game,),
        )
        game.line.moves[0].san = "Nf3"
        game.line.moves[0].nags = ["!?"]
        self.assertEqual(parse_pgn_text(serialize_pgn_text((game,))), (game,))


if __name__ == "__main__":
    unittest.main()
