import codecs
from pathlib import Path
import unittest
from unittest.mock import patch

from acs import pgn_roundtrip as rt
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

    def test_strict_mode_requires_exact_boolean_and_fails_before_byte_decode(self):
        damaged = '[Event "Damaged"]\n[Result "*"]\n\n1. e4 e5'
        for invalid in (0, 1, None, "", "false", (), object()):
            with self.subTest(invalid=repr(invalid)):
                with self.assertRaisesRegex(TypeError, "strict must be a boolean"):
                    parse_pgn_text(damaged, strict=invalid)

        with patch("acs.pgn_roundtrip.decode_pgn_bytes") as decode:
            with self.assertRaisesRegex(TypeError, "strict must be a boolean"):
                parse_pgn_bytes(b"not decoded", strict=0)
            decode.assert_not_called()


    def test_source_budget_subclasses_fail_before_overrideable_claim_hooks(self):
        calls = []

        class ActiveBudget(rt.PgnSourceBudget):
            def claim_text_chars(self, amount):
                calls.append(("text", amount))
                raise AssertionError("active budget hook must not execute")

        budget = ActiveBudget(rt.WHOLE_DOCUMENT_PGN_LIMITS)
        with self.assertRaisesRegex(TypeError, "source_budget must be PgnSourceBudget"):
            parse_pgn_text(
                '[Result "*"]\n\n1. e4 *',
                source_budget=budget,
            )
        self.assertEqual(calls, [])

        class DerivedLimits(rt.PgnSourceLimits):
            pass

        with self.assertRaisesRegex(TypeError, "limits must be PgnSourceLimits"):
            rt.PgnSourceBudget(
                DerivedLimits(
                    max_source_bytes=1024,
                    max_text_chars=1024,
                    max_lexical_tokens=128,
                    max_games=4,
                )
            )

    def test_model_subclasses_fail_before_overrideable_attribute_hooks(self):
        touches = []

        class ActivePgnGame(PgnGame):
            def __getattribute__(self, name):
                touches.append(("game", name))
                raise AssertionError("active PgnGame hook must not execute")

        class ActiveVariationLine(VariationLine):
            def __getattribute__(self, name):
                touches.append(("line", name))
                raise AssertionError("active VariationLine hook must not execute")

        class ActiveMoveNode(MoveNode):
            def __getattribute__(self, name):
                touches.append(("move", name))
                raise AssertionError("active MoveNode hook must not execute")

        class ActiveComment(Comment):
            def __getattribute__(self, name):
                touches.append(("comment", name))
                raise AssertionError("active Comment hook must not execute")

        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            (object.__new__(ActivePgnGame),),
        )
        self.assertEqual(touches, [])

        game_with_active_line = PgnGame(
            tags={"Result": "*"},
            line=object.__new__(ActiveVariationLine),
            warnings=[],
        )
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            (game_with_active_line,),
        )
        self.assertEqual(touches, [])

        game_with_active_move = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[object.__new__(ActiveMoveNode)],
                result="*",
            ),
            warnings=[],
        )
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            (game_with_active_move,),
        )
        self.assertEqual(touches, [])

        game_with_active_comment = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                leading_comments=[object.__new__(ActiveComment)],
                result="*",
            ),
            warnings=[],
        )
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            (game_with_active_comment,),
        )
        self.assertEqual(touches, [])

    def test_bytes_parse_runs_one_semantic_preflight_with_shared_budget(self):
        payload = b'[Result "*"]\n\n1. e4 *\n'
        with patch.object(
            rt,
            "_preflight_text",
            wraps=rt._preflight_text,
        ) as preflight:
            games = parse_pgn_bytes(payload)
        self.assertEqual(len(games), 1)
        self.assertEqual(preflight.call_count, 1)

        with patch.object(
            rt,
            "_preflight_text",
            wraps=rt._preflight_text,
        ) as preflight:
            decoded = decode_pgn_bytes(payload)
        self.assertIn('[Result "*"]', decoded)
        self.assertEqual(preflight.call_count, 1)

    def test_byte_round_trip_preflights_source_and_canonical_output_once_each(self):
        payload = b'[Result "*"]\n\n1. e4 *\n'
        with patch.object(
            rt,
            "_preflight_text",
            wraps=rt._preflight_text,
        ) as preflight:
            encoded, games = canonical_round_trip_bytes(payload)
        self.assertEqual(len(games), 1)
        self.assertIn(b'[Result "*"]', encoded)
        self.assertEqual(preflight.call_count, 2)

    def test_invalid_unicode_scalars_fail_with_stable_text_and_model_errors(self):
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_TEXT,
            parse_pgn_text,
            '[Event "bad\ud800"]\n[Result "*"]\n\n1. e4 *',
        )

        tag_game = PgnGame(
            tags={"Event": "bad\ud800", "Result": "*"},
            line=VariationLine(moves=[MoveNode("e4", move_number="1.")], result="*"),
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
                        comments_after=[Comment("bad\udfff")],
                    )
                ],
                result="*",
            ),
        )
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_bytes,
            (comment_game,),
        )

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
        with patch("acs.pgn_roundtrip.MAX_PGN_LEXICAL_TOKENS", 2):
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

    def test_preflight_counts_recovery_tokenizer_expansion_before_materialization(self):
        sources = (
            '[Result "*"]\n\n1.e4 *',
            '[Result "*"]\n\n{{x}} *',
            '[Result "*"]\n\n$x *',
            '[Result "*"]\n\n}} *',
        )
        for source in sources:
            with self.subTest(source=source):
                with (
                    patch("acs.pgn_roundtrip.MAX_PGN_LEXICAL_TOKENS", 3),
                    patch(
                        "acs.pgn_roundtrip.parse_games",
                        side_effect=AssertionError(
                            "parser token materialization must not run"
                        ),
                    ) as parser,
                ):
                    self.assert_code(
                        PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT,
                        parse_pgn_text,
                        source,
                        strict=False,
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

    def test_literal_double_brace_cannot_hide_next_game_header_limits(self):
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

    def test_tag_field_limit_runs_before_game_framer_allocation(self):
        source = '[Event "abcdef"]\n[Result "*"]\n\n1. e4 *'
        with (
            patch("acs.pgn_roundtrip.MAX_PGN_TAG_VALUE_CHARS", 5),
            patch(
                "acs.pgn_roundtrip.CanonicalPgnGameFramer.feed_line",
                side_effect=AssertionError("framer must not receive oversized tag"),
            ) as feed_line,
        ):
            self.assert_code(
                PgnRoundTripErrorCode.TAG_SIZE_LIMIT,
                parse_pgn_text,
                source,
            )
            feed_line.assert_not_called()

    def test_game_and_tag_count_bounds_are_independent(self):
        two_games = (
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
                two_games,
            )
            parser.assert_not_called()
        with patch("acs.pgn_roundtrip.MAX_PGN_TAGS_PER_GAME", 1):
            self.assert_code(
                PgnRoundTripErrorCode.TAG_COUNT_LIMIT,
                parse_pgn_text,
                '[Event "One"]\n[Result "*"]\n\n1. e4 *',
            )

    def test_tag_names_share_the_canonical_lexical_token_bound(self):
        source = '[EventLong "x"]\n[Result "*"]\n\n1. e4 *'
        with patch("acs.pgn_roundtrip.MAX_PGN_TOKEN_CHARS", 8):
            self.assert_code(
                PgnRoundTripErrorCode.TOKEN_SIZE_LIMIT,
                parse_pgn_text,
                source,
            )

            game = PgnGame(
                tags={"EventLong": "x", "Result": "*"},
                line=VariationLine(
                    moves=[MoveNode("e4", move_number="1.")],
                    result="*",
                ),
            )
            self.assert_code(
                PgnRoundTripErrorCode.TOKEN_SIZE_LIMIT,
                serialize_pgn_text,
                (game,),
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

    def test_serialization_preflight_counts_implicit_result_header(self):
        fits = PgnGame(
            tags={"Event": "One"},
            line=VariationLine(moves=[MoveNode("e4", move_number="1.")], result="*"),
        )
        overflow = PgnGame(
            tags={"Event": "One", "Site": "Here"},
            line=VariationLine(moves=[MoveNode("e4", move_number="1.")], result="*"),
        )
        with patch("acs.pgn_roundtrip.MAX_PGN_TAGS_PER_GAME", 2):
            text = serialize_pgn_text((fits,))
            self.assertIn('[Result "*"]', text)
            self.assert_code(
                PgnRoundTripErrorCode.TAG_COUNT_LIMIT,
                serialize_pgn_text,
                (overflow,),
            )

    def test_serialization_requires_explicit_matching_root_result(self):
        missing_movetext_result = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(moves=[MoveNode("e4", move_number="1.")]),
        )
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            (missing_movetext_result,),
        )

        mismatched_result = PgnGame(
            tags={"Result": "1-0"},
            line=VariationLine(
                moves=[MoveNode("e4", move_number="1.")],
                result="*",
            ),
        )
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            (mismatched_result,),
        )

    def test_serialization_rejects_lossy_programmatic_comment_layouts(self):
        missing_number = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[
                    MoveNode(
                        "e4",
                        comments_before=[Comment("before")],
                    )
                ],
                result="*",
            ),
        )
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            (missing_number,),
        )

        carriage_return = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[
                    MoveNode(
                        "e4",
                        move_number="1.",
                        comments_after=[Comment("line one\rline two")],
                    )
                ],
                result="*",
            ),
        )
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            (carriage_return,),
        )

        representable = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[
                    MoveNode(
                        "e4",
                        move_number="1.",
                        comments_before=[Comment("before")],
                    )
                ],
                result="*",
            ),
        )
        self.assertEqual(
            parse_pgn_text(serialize_pgn_text((representable,))),
            (representable,),
        )

    def test_serialization_preflight_budgets_escaped_tag_expansion_before_build(self):
        game = PgnGame(
            tags={"Event": chr(92) * 200, "Result": "*"},
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

    def test_byte_export_rejects_multibyte_overflow_before_encoding(self):
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

    def test_canonical_byte_rewrite_rejects_overflow_before_encoding(self):
        class NoEncodeText(str):
            def encode(self, *args, **kwargs):
                raise AssertionError("encode must not run after byte-size preflight fails")

        class CanonicalResult:
            text = NoEncodeText("é" * 6)
            games = ()

        with (
            patch(
                "acs.pgn_roundtrip._canonicalize_parsed_games",
                return_value=CanonicalResult(),
            ),
            patch("acs.pgn_roundtrip.MAX_PGN_SOURCE_BYTES", 10),
        ):
            self.assert_code(
                PgnRoundTripErrorCode.BYTE_SIZE_LIMIT,
                canonical_round_trip_bytes,
                b'[Result "*"]\n\n*\n',
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

    def test_invalid_yielded_game_stops_generator_before_read_ahead(self):
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

        error = self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            source(),
        )
        self.assertIn("requires PgnGame values", str(error))
        self.assertEqual(observed, ["invalid"])

    def test_canonical_model_validation_fails_before_generator_read_ahead(self):
        valid_second = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[MoveNode("e4", move_number="1.")],
                result="*",
            ),
        )
        invalid_games = (
            PgnGame(
                tags={"Bad Tag": "x", "Result": "*"},
                line=VariationLine(result="*"),
            ),
            PgnGame(
                tags={"Result": "*"},
                line=VariationLine(
                    moves=[MoveNode("e4", move_number="not-a-number")],
                    result="*",
                ),
            ),
            PgnGame(
                tags={"Result": "*"},
                line=VariationLine(
                    moves=[MoveNode("e4", move_number="1.", nags=["$999"])],
                    result="*",
                ),
            ),
            PgnGame(
                tags={"Result": "*"},
                line=VariationLine(
                    moves=[
                        MoveNode(
                            "e4",
                            move_number="1.",
                            comments_after=[Comment("bad } brace")],
                        )
                    ],
                    result="*",
                ),
            ),
        )

        for invalid in invalid_games:
            observed = []

            def source():
                observed.append("invalid")
                yield invalid
                observed.append("second")
                yield valid_second

            with self.subTest(invalid=repr(invalid)):
                self.assert_code(
                    PgnRoundTripErrorCode.INVALID_MODEL,
                    serialize_pgn_text,
                    source(),
                )
                self.assertEqual(observed, ["invalid"])

    def test_roundtrip_module_has_one_complete_codec_tail(self):
        source = (Path(__file__).parents[1] / "acs" / "pgn_roundtrip.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(source.count("def parse_pgn_text("), 1)
        self.assertEqual(source.count("def canonical_round_trip_bytes("), 1)
        self.assertTrue(source.rstrip().endswith("return encoded, result.games"))


    def test_recovery_warning_provenance_blocks_strict_serialization(self):
        recovered = parse_pgn_text(
            '[Event "Damaged"]\n[Result "*"]\n\n1. e4 e5',
            strict=False,
        )
        warnings_before = list(recovered[0].warnings)
        self.assertTrue(warnings_before)

        error = self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            recovered,
        )
        self.assertIn("explicit normalization", str(error))
        self.assertEqual(
            recovered[0].warnings,
            warnings_before,
            "failed strict serialization must not consume recovery provenance",
        )
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_bytes,
            recovered,
        )

    def test_recovery_warning_container_must_remain_passive_text(self):
        recovered = parse_pgn_text(
            '[Event "Damaged"]\n[Result "*"]\n\n1. e4 e5',
            strict=False,
        )
        recovered[0].warnings = ("diagnostic",)
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            recovered,
        )
        recovered[0].warnings = [object()]
        self.assert_code(
            PgnRoundTripErrorCode.INVALID_MODEL,
            serialize_pgn_text,
            recovered,
        )
    def test_empty_model_cannot_serialize_to_strictly_invalid_empty_pgn(self):
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


    def test_w1_gate_pins_d06_regression_authority_and_event_base(self):
        source = (
            Path(__file__).parents[1]
            / ".github"
            / "workflows"
            / "w1-d06-bounded-model-materialization-convergence.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("- 'tests/test_d06_pgn_roundtrip.py'", source)
        self.assertIn("EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}", source)
        self.assertIn('event_base="${EVENT_BASE_SHA:-$MANUAL_BASE_SHA}"', source)
        self.assertIn('git merge-base --is-ancestor "$event_base" HEAD', source)
        self.assertIn('git diff --name-only "$event_base...HEAD"', source)
        self.assertIn("D06_SOURCE_BLOB:", source)
        self.assertIn("D06_TEST_BLOB:", source)
        self.assertIn('HEAD:acs/pgn_roundtrip.py', source)
        self.assertIn('HEAD:tests/test_d06_pgn_roundtrip.py', source)
        self.assertIn(".github/workflows/w1-d06-bounded-model-materialization-convergence.yml", source)
        self.assertNotIn("EVENT_BASE_REF:", source)
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
