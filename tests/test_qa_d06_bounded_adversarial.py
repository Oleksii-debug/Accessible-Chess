from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import acs.pgn_roundtrip as pgn_roundtrip
from acs.gametree import Comment, MoveNode, PgnGame, VariationLine
from acs.pgn_roundtrip import (
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    parse_pgn_bytes,
    parse_pgn_text,
    serialize_pgn_text,
)
from acs.pgn_service import save_pgn_atomic


def _game(index: int = 0) -> PgnGame:
    return PgnGame(
        tags={"Event": f"QA {index}", "Result": "*"},
        line=VariationLine(moves=[MoveNode("e4", move_number="1.")], result="*"),
        source_index=index,
    )


class _HostileIterator:
    """One-shot producer that fails with an implementation-independent exception."""

    def __init__(self, *, fail_after: int) -> None:
        self.fail_after = fail_after
        self.pulls = 0
        self.iter_calls = 0

    def __iter__(self):
        self.iter_calls += 1
        if self.iter_calls != 1:
            raise AssertionError("hostile source was iterated more than once")
        return self

    def __next__(self) -> PgnGame:
        if self.pulls >= self.fail_after:
            raise RuntimeError("HOSTILE_PRIVATE_SENTINEL must not escape codec boundary")
        game = _game(self.pulls)
        self.pulls += 1
        return game


class D06BoundedAdversarialOracle(unittest.TestCase):
    """Deterministic D06 grammar/resource adversarial matrix.

    All large-input checks use reduced limits or bounded fixed-size payloads.
    This is intentionally not fuzzing and never allocates near production caps.
    """

    def assert_code(self, code: PgnRoundTripErrorCode, callable_, *args, **kwargs):
        with self.assertRaises(PgnRoundTripError) as caught:
            callable_(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertLess(len(str(caught.exception)), 256)
        return caught.exception

    def test_huge_tag_value_rejects_at_exact_reduced_boundary(self) -> None:
        accepted = '[Event "12345678"]\n[Result "*"]\n\n*\n'
        rejected = '[Event "123456789"]\n[Result "*"]\n\n*\n'
        with mock.patch.object(pgn_roundtrip, "MAX_PGN_TAG_VALUE_CHARS", 8):
            self.assertEqual(len(parse_pgn_text(accepted)), 1)
            self.assert_code(PgnRoundTripErrorCode.TAG_SIZE_LIMIT, parse_pgn_text, rejected)

    def test_huge_brace_and_semicolon_comments_reject_before_parser(self) -> None:
        cases = (
            '[Result "*"]\n\n1. e4 {123456789} *\n',
            '[Result "*"]\n\n1. e4 ;123456789\n*\n',
        )
        for source in cases:
            with self.subTest(source=source[:24]), mock.patch.object(
                pgn_roundtrip, "MAX_PGN_COMMENT_CHARS", 8
            ), mock.patch.object(
                pgn_roundtrip,
                "parse_games",
                side_effect=AssertionError("oversized comment reached structural parser"),
            ):
                self.assert_code(PgnRoundTripErrorCode.COMMENT_SIZE_LIMIT, parse_pgn_text, source)

    def test_many_nags_hit_lexical_budget_before_structural_parse(self) -> None:
        source = '[Result "*"]\n\n1. e4 ' + ' '.join(["$1"] * 32) + ' *\n'
        with mock.patch.object(pgn_roundtrip, "MAX_PGN_LEXICAL_TOKENS", 8), mock.patch.object(
            pgn_roundtrip,
            "parse_games",
            side_effect=AssertionError("over-budget NAG stream reached structural parser"),
        ):
            self.assert_code(PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT, parse_pgn_text, source)

    def test_many_games_have_a_stable_game_count_failure(self) -> None:
        source = "\n\n".join(
            f'[Event "G{index}"]\n[Result "*"]\n\n1. e4 *' for index in range(3)
        )
        with mock.patch.object(pgn_roundtrip, "MAX_PGN_GAMES", 2):
            self.assert_code(PgnRoundTripErrorCode.GAME_COUNT_LIMIT, parse_pgn_text, source)

    def test_unterminated_tag_string_is_sanitized_malformed_header(self) -> None:
        source = '[Event "PRIVATE_HEADER_SENTINEL]\n[Result "*"]\n\n*\n'
        error = self.assert_code(PgnRoundTripErrorCode.MALFORMED_HEADER, parse_pgn_text, source)
        self.assertNotIn("PRIVATE_HEADER_SENTINEL", str(error))

    def test_unterminated_comment_recovery_does_not_turn_comment_text_into_moves(self) -> None:
        source = '[Result "*"]\n\n1. e4 {Nf3 Qh5 PRIVATE_COMMENT_SENTINEL'
        self.assert_code(PgnRoundTripErrorCode.MALFORMED_PGN, parse_pgn_text, source)
        recovered = parse_pgn_text(source, strict=False)
        self.assertEqual([move.san for move in recovered[0].line.moves], ["e4"])
        self.assertTrue(recovered[0].warnings)
        self.assertIn("Nf3 Qh5", recovered[0].line.moves[0].comments_after[0].text)

    def test_nested_braces_are_recovery_only_and_do_not_fabricate_moves(self) -> None:
        source = '[Result "*"]\n\n1. e4 {outer {Nf3} Qh5} e5 *\n'
        self.assert_code(PgnRoundTripErrorCode.MALFORMED_PGN, parse_pgn_text, source)
        recovered = parse_pgn_text(source, strict=False)
        self.assertEqual([move.san for move in recovered[0].line.moves], ["e4", "e5"])
        self.assertEqual(
            recovered[0].line.moves[0].comments_after[0].text,
            "outer (Nf3) Qh5",
        )

    def test_attached_symbolic_nag_is_normalized_without_san_fabrication(self) -> None:
        source = '[Result "*"]\n\n1. Nf3!? d5 *\n'
        game = parse_pgn_text(source)[0]
        self.assertEqual(game.line.moves[0].san, "Nf3")
        self.assertEqual(game.line.moves[0].nags, ["!?"])

    def test_invalid_utf8_is_sanitized_and_never_replaced_by_codec(self) -> None:
        payload = b'[Event "PRIVATE_BYTE_SENTINEL"]\n[Result "*"]\n\n1. e4\xff *\n'
        error = self.assert_code(PgnRoundTripErrorCode.INVALID_ENCODING, parse_pgn_bytes, payload)
        self.assertNotIn("PRIVATE_BYTE_SENTINEL", str(error))
        self.assertNotIn("xff", str(error).lower())

    def test_pathological_whitespace_is_linear_on_a_small_fixed_payload(self) -> None:
        spaces = 200_000
        source = '[Result "*"]\n\n' + (' ' * spaces) + '1. e4 *\n'
        started = time.perf_counter()
        games = parse_pgn_text(source)
        elapsed = time.perf_counter() - started
        self.assertEqual([move.san for move in games[0].line.moves], ["e4"])
        self.assertLess(elapsed, 5.0)
        print(f"D06_METRIC pathological_whitespace_chars={spaces} elapsed_seconds={elapsed:.6f}")

    def test_malformed_san_fails_in_strict_and_recovery_without_echo(self) -> None:
        source = '[Result "*"]\n\n1. PRIVATE_BAD_SAN *\n'
        for strict in (True, False):
            with self.subTest(strict=strict):
                error = self.assert_code(
                    PgnRoundTripErrorCode.INVALID_SAN,
                    parse_pgn_text,
                    source,
                    strict=strict,
                )
                self.assertNotIn("PRIVATE_BAD_SAN", str(error))

    def test_oversized_programmatic_result_is_bounded_before_serializer(self) -> None:
        game = _game()
        game.line.result = "x" * 9
        with mock.patch.object(pgn_roundtrip, "MAX_PGN_TOKEN_CHARS", 8), mock.patch.object(
            pgn_roundtrip,
            "serialize_games",
            side_effect=AssertionError("oversized result reached payload serializer"),
        ):
            self.assert_code(PgnRoundTripErrorCode.INVALID_MODEL, serialize_pgn_text, (game,))

    def test_serializer_deep_rav_model_has_stable_depth_limit(self) -> None:
        root = VariationLine(result="*")
        current = root
        for _ in range(4):
            node = MoveNode("e4", move_number="1.")
            child = VariationLine(moves=[MoveNode("e5", move_number="1...")])
            node.variations.append(child)
            current.moves.append(node)
            current = child
        game = PgnGame(tags={"Result": "*"}, line=root)
        with mock.patch.object(pgn_roundtrip, "MAX_VARIATION_DEPTH", 2):
            self.assert_code(PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT, serialize_pgn_text, (game,))

    def test_red_parser_deep_rav_must_not_leak_gametree_contract_error(self) -> None:
        # Reduced structural depth keeps the oracle tiny while exercising the
        # same public parse_pgn_text exception boundary as hostile deep RAV.
        source = '[Result "*"]\n\n1. e4 (1... e5 (2. Nf3 (2... Nc6))) *\n'
        with mock.patch("acs.gametree.MAX_VARIATION_DEPTH", 1), mock.patch.object(
            pgn_roundtrip, "MAX_VARIATION_DEPTH", 1
        ):
            self.assert_code(PgnRoundTripErrorCode.TOKEN_COUNT_LIMIT, parse_pgn_text, source)

    def test_red_hostile_iterable_exception_must_be_sanitized_by_codec(self) -> None:
        source = _HostileIterator(fail_after=1)
        error = self.assert_code(PgnRoundTripErrorCode.INVALID_MODEL, serialize_pgn_text, source)
        self.assertEqual(source.iter_calls, 1)
        self.assertEqual(source.pulls, 1)
        self.assertNotIn("HOSTILE_PRIVATE_SENTINEL", str(error))

    def test_hostile_streaming_producer_never_partially_publishes(self) -> None:
        source = _HostileIterator(fail_after=1)
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            destination = directory / "existing.pgn"
            original = b"ORIGINAL_USER_BYTES\n"
            destination.write_bytes(original)
            with self.assertRaises(RuntimeError):
                save_pgn_atomic(destination, source, overwrite=True)
            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(list(directory.glob(destination.name + ".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
