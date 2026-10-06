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

    def test_import_move_number_period_flexibility_round_trips_structurally(self):
        source = '[Result "*"]\n\n1 e4 1 ..e5 2....Nf3 2 ... Nc6 *'
        games = parse_pgn_text(source)
        self.assertEqual(
            [move.move_number for move in games[0].line.moves],
            ["1", "1..", "2....", "2..."],
        )
        self.assertEqual(
            [move.san for move in games[0].line.moves],
            ["e4", "e5", "Nf3", "Nc6"],
        )

        serialized = serialize_pgn_text(games)
        self.assertEqual(parse_pgn_text(serialized), games)

        for damaged in (
            '... e4 *',
            '....e4 *',
            '1 . . e4 *',
            '1 {between integer and periods} .. e4 *',
        ):
            with self.subTest(damaged=damaged):
                self.assert_code(
                    PgnRoundTripErrorCode.MALFORMED_PGN,
                    parse_pgn_text,
                    f'[Result "*"]\n\n{damaged}',
                )

    def test_strict_mode_rejects_lossy_pending_move_structure(self):
        for damaged in (
            '1 2 e4 *',
            '1 {between move numbers} 2 e4 *',
            '1. 2... e4 *',
            '1 *',
            '1. e4 1... $1 e5 *',
            '1. e4 1... ! e5 *',
        ):
            with self.subTest(damaged=damaged):
                self.assert_code(
                    PgnRoundTripErrorCode.MALFORMED_PGN,
                    parse_pgn_text,
                    f'[Result "*"]\n\n{damaged}',
                )

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


    def test_strict_flag_requires_exact_boolean_before_any_parse_work(self):
        source = '[Result "*"]\n\n*'
        for invalid in (0, 1, None, "", (), object()):
            with self.subTest(invalid=repr(invalid)):
                with self.assertRaises(TypeError):
                    parse_pgn_text(source, strict=invalid)
        with patch(
            "acs.pgn_roundtrip.decode_pgn_bytes",
            side_effect=AssertionError("decode must not run"),
        ) as decoder:
            with self.assertRaises(TypeError):
                parse_pgn_bytes(source.encode("utf-8"), strict=0)
            decoder.assert_not_called()

    def test_invalid_unicode_scalar_fails_closed_in_source_and_model(self):
        surrogate = "\ud800"
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_TEXT,
            parse_pgn_text,
            f'[Event "{surrogate}"]\n[Result "*"]\n\n*',
        )

        tag_game = PgnGame(
            tags={"Event": surrogate, "Result": "*"},
            line=VariationLine(result="*"),
        )
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            (tag_game,),
        )

        comment_game = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[
                    MoveNode(
                        "e4",
                        move_number="1.",
                        comments_after=[Comment(surrogate)],
                    )
                ],
                result="*",
            ),
        )
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            (comment_game,),
        )

    def test_tag_names_share_parser_and_serializer_lexical_bound(self):
        source = '[EventLong "x"]\n[Result "*"]\n\n*'
        with patch("acs.pgn_roundtrip.MAX_PGN_TOKEN_CHARS", 8):
            self.assert_code(
                PgnRoundTripErrorCode.TOKEN_SIZE_LIMIT,
                parse_pgn_text,
                source,
            )
            game = PgnGame(
                tags={"EventLong": "x", "Result": "*"},
                line=VariationLine(result="*"),
            )
            self.assert_code(
                PgnRoundTripErrorCode.TOKEN_SIZE_LIMIT,
                serialize_pgn_text,
                (game,),
            )

    def test_serialization_counts_implicit_result_tag_before_payload_build(self):
        game = PgnGame(
            tags={"Event": "One"},
            line=VariationLine(result="*"),
        )
        with (
            patch("acs.pgn_roundtrip.MAX_PGN_TAGS_PER_GAME", 1),
            patch("acs.pgn_roundtrip.serialize_games") as serializer,
        ):
            self.assert_code(
                PgnRoundTripErrorCode.TAG_COUNT_LIMIT,
                serialize_pgn_text,
                (game,),
            )
            serializer.assert_not_called()

    def test_serialization_requires_explicit_matching_root_result(self):
        missing = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(moves=[MoveNode("e4", move_number="1.")]),
        )
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            (missing,),
        )

        mismatched = PgnGame(
            tags={"Result": "1-0"},
            line=VariationLine(
                moves=[MoveNode("e4", move_number="1.")],
                result="*",
            ),
        )
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            (mismatched,),
        )

    def test_empty_model_fails_closed_in_text_and_bytes_serialization(self):
        self.assert_code(
            PgnRoundTripErrorCode.EMPTY_PGN,
            serialize_pgn_text,
            (),
        )
        self.assert_code(
            PgnRoundTripErrorCode.EMPTY_PGN,
            serialize_pgn_bytes,
            (),
        )

    def test_lossy_comment_layouts_fail_before_serializer(self):
        missing_move_number = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[MoveNode("e4", comments_before=[Comment("before")])],
                result="*",
            ),
        )
        carriage_return = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[
                    MoveNode(
                        "e4",
                        move_number="1.",
                        comments_after=[Comment("one\rtwo")],
                    )
                ],
                result="*",
            ),
        )
        for game in (missing_move_number, carriage_return):
            with self.subTest(game=repr(game)):
                with patch("acs.pgn_roundtrip.serialize_games") as serializer:
                    self.assert_code(
                        PgnRoundTripErrorCode.INVALID_MODEL,
                        serialize_pgn_text,
                        (game,),
                    )
                    serializer.assert_not_called()

    def test_recovery_warning_container_remains_passive_text_only(self):
        game = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(result="*"),
        )
        game.warnings = ("diagnostic",)
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            (game,),
        )
        game.warnings = [object()]
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            (game,),
        )

    def test_escaped_tag_growth_is_budgeted_before_serializer_payload(self):
        game = PgnGame(
            tags={"Event": "\\" * 200, "Result": "*"},
            line=VariationLine(result="*"),
        )
        with (
            patch("acs.pgn_roundtrip.MAX_PGN_TEXT_CHARS", 380),
            patch("acs.pgn_roundtrip.serialize_games") as serializer,
        ):
            self.assert_code(
                PgnRoundTripErrorCode.TEXT_SIZE_LIMIT,
                serialize_pgn_text,
                (game,),
            )
            serializer.assert_not_called()


    def test_bytes_parse_runs_one_semantic_preflight(self):
        source = '[Result "*"]\n\n*'
        with patch(
            "acs.pgn_roundtrip._preflight_text",
            side_effect=[source, AssertionError("semantic preflight ran twice")],
        ) as preflight:
            games = parse_pgn_bytes(source.encode("utf-8"))
        self.assertEqual(len(games), 1)
        self.assertEqual(preflight.call_count, 1)

    def test_byte_export_rejects_multibyte_overflow_before_encode_allocation(self):
        class NoEncodeText(str):
            def encode(self, *args, **kwargs):
                raise AssertionError("encode must not run after byte-size preflight fails")

        with (
            patch(
                "acs.pgn_roundtrip.serialize_pgn_text",
                return_value=NoEncodeText("é" * 6),
            ),
            patch("acs.pgn_roundtrip.MAX_PGN_SOURCE_BYTES", 10),
        ):
            self.assert_code(
                PgnRoundTripErrorCode.BYTE_SIZE_LIMIT,
                serialize_pgn_bytes,
                (),
            )

    def test_canonical_byte_export_rejects_overflow_before_encode_allocation(self):
        class NoEncodeText(str):
            def encode(self, *args, **kwargs):
                raise AssertionError("encode must not run after byte-size preflight fails")

        class CanonicalResult:
            text = NoEncodeText("é" * 6)
            games = ()

        with (
            patch("acs.pgn_roundtrip.parse_pgn_bytes", return_value=()),
            patch(
                "acs.pgn_roundtrip._canonicalize_parsed_games",
                return_value=CanonicalResult(),
            ),
            patch("acs.pgn_roundtrip.MAX_PGN_SOURCE_BYTES", 10),
        ):
            self.assert_code(
                PgnRoundTripErrorCode.BYTE_SIZE_LIMIT,
                canonical_round_trip_bytes,
                b"*",
            )


    def test_serialization_preflight_matches_strict_lexical_token_budget(self):
        game = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[MoveNode("e4", move_number="1.", nags=["!"])],
                result="*",
            ),
        )
        with patch("acs.pgn_roundtrip.MAX_PGN_LEXICAL_TOKENS", 5):
            text = serialize_pgn_text((game,))
            self.assertEqual(parse_pgn_text(text), (game,))
        with patch("acs.pgn_roundtrip.MAX_PGN_LEXICAL_TOKENS", 4):
            self.assert_code(
                PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT,
                serialize_pgn_text,
                (game,),
            )

    def test_invalid_first_yielded_game_stops_generator_before_read_ahead(self):
        observed = []
        valid_second = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[MoveNode("e4", move_number="1.")],
                result="*",
            ),
        )

        def source():
            observed.append("invalid")
            yield object()
            observed.append("second")
            yield valid_second

        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            source(),
        )
        self.assertEqual(observed, ["invalid"])

    def test_invalid_canonical_model_stops_generator_before_read_ahead(self):
        valid_second = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[MoveNode("e4", move_number="1.")],
                result="*",
            ),
        )
        invalid = PgnGame(
            tags={"Bad Tag": "x", "Result": "*"},
            line=VariationLine(result="*"),
        )
        observed = []

        def source():
            observed.append("invalid")
            yield invalid
            observed.append("second")
            yield valid_second

        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            source(),
        )
        self.assertEqual(observed, ["invalid"])


    def test_game_count_limit_fails_before_parser_materialization(self):
        source = (
            '[Event "One"]\n[Result "*"]\n\n1. e4 *\n\n'
            '[Event "Two"]\n[Result "*"]\n\n1. d4 *\n'
        )
        with (
            patch("acs.pgn_roundtrip.MAX_PGN_GAMES", 1),
            patch(
                "acs.pgn_roundtrip.parse_games",
                side_effect=AssertionError("parser materialization must not run"),
            ) as parser,
        ):
            self.assert_code(
                PgnRoundTripErrorCode.GAME_COUNT_LIMIT,
                parse_pgn_text,
                source,
            )
            parser.assert_not_called()

    def test_compact_move_number_token_budget_fails_before_parser(self):
        source = '[Result "*"]\n\n1.e4 *'
        with (
            patch("acs.pgn_roundtrip.MAX_PGN_LEXICAL_TOKENS", 3),
            patch(
                "acs.pgn_roundtrip.parse_games",
                side_effect=AssertionError("parser token materialization must not run"),
            ) as parser,
        ):
            self.assert_code(
                PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT,
                parse_pgn_text,
                source,
            )
            parser.assert_not_called()

    def test_game_preflight_preserves_multiline_nested_comment_frame_state(self):
        source = (
            '[Result "*"]\n\n'
            '1. e4 {outer\n'
            '{inner\n'
            '} inner close\n'
            '[Event "comment text, not a boundary"]\n'
            '} *\n'
        )
        with patch("acs.pgn_roundtrip.MAX_PGN_GAMES", 1):
            games = parse_pgn_text(source, strict=False)
        self.assertEqual(len(games), 1)

    def test_recovery_span_cannot_hide_next_game_header_field_limit(self):
        source = (
            '[Result "*"]\n\n'
            '1. e4 {{literal}\n'
            '[Event "abcdef"]\n'
            '[Result "*"]\n\n'
            '1. d4 } *\n'
        )
        with patch("acs.pgn_roundtrip.MAX_PGN_TAG_VALUE_CHARS", 5):
            self.assert_code(
                PgnRoundTripErrorCode.TAG_SIZE_LIMIT,
                parse_pgn_text,
                source,
                strict=False,
            )


    def test_canonical_bytes_preflights_source_once_then_canonical_output_once(self):
        source = '[Result "*"]\n\n*'
        observed = []

        def preflight(text, **kwargs):
            observed.append(text)
            return text

        with patch("acs.pgn_roundtrip._preflight_text", side_effect=preflight):
            encoded, games = canonical_round_trip_bytes(source.encode("utf-8"))

        self.assertTrue(encoded)
        self.assertEqual(len(games), 1)
        self.assertEqual(len(observed), 2)


if __name__ == "__main__":
    unittest.main()
