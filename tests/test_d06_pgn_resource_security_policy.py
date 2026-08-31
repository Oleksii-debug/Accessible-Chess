from __future__ import annotations

import unittest
from unittest.mock import patch

import acs.pgn_roundtrip as pgn
from acs.gametree import MoveNode, PgnGame, VariationLine
from acs.pgn_service import _parse_file_games


class D06PgnResourceSecurityPolicyTests(unittest.TestCase):
    def assert_code(self, expected, callable_, *args, **kwargs):
        with self.assertRaises(pgn.PgnRoundTripError) as caught:
            callable_(*args, **kwargs)
        self.assertEqual(caught.exception.code, expected)
        self.assertNotIn("Traceback", str(caught.exception))
        return caught.exception

    def assert_preflight_rejects(self, expected, source):
        with patch.object(
            pgn,
            "parse_games",
            side_effect=AssertionError("structural parser must not be reached"),
        ):
            return self.assert_code(expected, pgn.parse_pgn_text, source, strict=False)

    def test_policy_exposes_explicit_hostile_input_bounds(self):
        self.assertEqual(pgn.MAX_PGN_LINES, 200_000)
        self.assertEqual(pgn.MAX_PGN_LINE_CHARS, 2 * 1024 * 1024)
        self.assertEqual(pgn.MAX_PGN_TAG_NAME_CHARS, 256)
        self.assertEqual(pgn.MAX_PGN_FEN_CHARS, 512)
        self.assertEqual(pgn.MAX_PGN_FEN_COUNTER_DIGITS, 12)
        self.assertEqual(pgn.MAX_VARIATION_DEPTH, 128)

    def test_newline_allocation_bomb_fails_before_structural_split(self):
        source = "\n" * 200_000
        self.assert_preflight_rejects(pgn.PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT, source)

    def test_pathological_whitespace_line_fails_before_full_line_scan(self):
        source = " " * ((2 * 1024 * 1024) + 1)
        self.assert_preflight_rejects(pgn.PgnRoundTripErrorCode.TOKEN_SIZE_LIMIT, source)

    def test_extreme_move_token_count_fails_before_structural_parser(self):
        source = '[Result "*"]\n\n' + ("e4 " * 500_001)
        self.assert_preflight_rejects(pgn.PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT, source)

    def test_nul_c0_c1_and_del_controls_fail_closed_before_parser(self):
        for control in ("\x00", "\x01", "\x1b", "\x7f", "\x85"):
            with self.subTest(codepoint=ord(control)):
                source = f'[Event "safe{control}hidden"]\n[Result "*"]\n\n1. e4 *\n'
                error = self.assert_preflight_rejects(
                    pgn.PgnRoundTripErrorCode.TOKEN_SIZE_LIMIT, source
                )
                self.assertNotIn("hidden", str(error))

    def test_tab_and_normal_unicode_are_not_rejected_as_controls(self):
        source = '[Event "Олексій"]\n[Result "*"]\n\n1.\te4 {нормальний коментар} *\n'
        games = pgn.parse_pgn_text(source)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].tags["Event"], "Олексій")

    def test_extreme_rav_depth_fails_before_recursive_structural_parse(self):
        source = '[Result "*"]\n\n1. e4 ' + ("(" * 129) + "1... e5" + (")" * 129) + " *"
        self.assert_preflight_rejects(pgn.PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT, source)

    def test_gigantic_tag_name_and_value_are_bounded_before_parser(self):
        name_source = f'[{"A" * 257} "x"]\n[Result "*"]\n\n1. e4 *\n'
        self.assert_preflight_rejects(pgn.PgnRoundTripErrorCode.TAG_SIZE_LIMIT, name_source)
        value_source = '[Event "' + ("x" * ((1024 * 1024) + 1)) + '"]\n[Result "*"]\n\n*\n'
        self.assert_preflight_rejects(pgn.PgnRoundTripErrorCode.TAG_SIZE_LIMIT, value_source)

    def test_unterminated_tag_line_fails_as_malformed_header_before_parser(self):
        source = '[Event "unterminated"\n[Result "*"]\n\n1. e4 *\n'
        self.assert_preflight_rejects(pgn.PgnRoundTripErrorCode.MALFORMED_HEADER, source)

    def test_fen_has_tighter_field_and_counter_bounds_than_generic_tags(self):
        oversized_fen = f'[FEN "{"x" * 513}"]\n[Result "*"]\n\n*\n'
        self.assert_preflight_rejects(pgn.PgnRoundTripErrorCode.TAG_SIZE_LIMIT, oversized_fen)
        huge_counter = (
            '[FEN "8/8/8/8/8/8/4K3/4k3 w - - 1234567890123 1"]\n'
            '[Result "*"]\n\n*\n'
        )
        self.assert_preflight_rejects(pgn.PgnRoundTripErrorCode.TAG_SIZE_LIMIT, huge_counter)

    def test_game_count_limit_is_enforced_before_structural_game_allocation(self):
        source = "\n\n".join(
            f'[Event "G{index}"]\n[Result "*"]\n\n1. e4 *' for index in range(3)
        )
        with patch.object(pgn, "MAX_PGN_GAMES", 2), patch.object(
            pgn, "parse_games", side_effect=AssertionError("structural parser must not be reached")
        ):
            self.assert_code(
                pgn.PgnRoundTripErrorCode.GAME_COUNT_LIMIT,
                pgn.parse_pgn_text,
                source,
                strict=False,
            )

    def test_malformed_utf8_and_oversized_unterminated_comment_fail_safely(self):
        error = self.assert_code(
            pgn.PgnRoundTripErrorCode.INVALID_ENCODING,
            pgn.parse_pgn_bytes,
            b'[Event "private"]\n\xff\n',
        )
        self.assertNotIn("private", str(error))
        with patch.object(pgn, "MAX_PGN_COMMENT_CHARS", 32):
            self.assert_code(
                pgn.PgnRoundTripErrorCode.COMMENT_SIZE_LIMIT,
                pgn.parse_pgn_text,
                '[Result "*"]\n\n1. e4 {' + ("x" * 33),
                strict=False,
            )

    def test_small_unterminated_comment_keeps_existing_recovery_semantics(self):
        source = '[Result "*"]\n\n1. e4 {recoverable note'
        self.assert_code(pgn.PgnRoundTripErrorCode.MALFORMED_PGN, pgn.parse_pgn_text, source)
        games = pgn.parse_pgn_text(source, strict=False)
        self.assertEqual(len(games), 1)
        self.assertTrue(any("unterminated brace comment" in w for w in games[0].warnings))

    def test_resource_policy_cannot_be_bypassed_by_file_recovery_fallback(self):
        source = "\n" * 200_000
        with patch(
            "acs.pgn_service.parse_games",
            side_effect=AssertionError("permissive fallback must not be reached"),
        ):
            self.assert_code(
                pgn.PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT, _parse_file_games, source
            )

    def test_recursive_programmatic_model_still_fails_without_recursion_escape(self):
        line = VariationLine(result="*")
        move = MoveNode("e4", move_number="1.")
        line.moves.append(move)
        move.variations.append(line)
        game = PgnGame(tags={"Result": "*"}, line=line)
        self.assert_code(
            pgn.PgnRoundTripErrorCode.INVALID_MODEL,
            pgn.serialize_pgn_text,
            (game,),
        )

    def test_realistic_large_annotated_multigame_document_remains_supported(self):
        game = '''[Event "Bulk {index} — Олексій"]
[Site "Uzhhorod"]
[SetUp "1"]
[FEN "8/8/8/8/8/8/4K3/4k3 w - - 0 1"]
[Annotator "resource-security"]
[Result "*"]

1. Kd2 {{main comment}} (1. Kf2 $1 {{side line}}) *'''
        source = "\n\n".join(game.format(index=index) for index in range(1_000))
        games = pgn.parse_pgn_text(source)
        self.assertEqual(len(games), 1_000)
        self.assertEqual(games[0].source_index, 0)
        self.assertEqual(games[-1].source_index, 999)
        self.assertEqual(games[-1].tags["Event"], "Bulk 999 — Олексій")
        self.assertEqual(games[500].line.moves[0].variations[0].moves[0].nags, ["$1"])


if __name__ == "__main__":
    unittest.main()
