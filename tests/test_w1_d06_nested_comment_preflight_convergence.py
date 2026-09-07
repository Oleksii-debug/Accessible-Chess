from __future__ import annotations

import unittest

from acs.pgn_roundtrip import (
    MAX_PGN_TOKEN_CHARS,
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    PgnSourceBudget,
    PgnSourceLimits,
    parse_pgn_text,
    serialize_pgn_text,
)


class W1D06NestedCommentPreflightConvergenceTests(unittest.TestCase):
    def test_recovery_preflight_does_not_reinterpret_long_nested_comment_tail_as_san(self) -> None:
        tail = "x" * (MAX_PGN_TOKEN_CHARS + 64)
        source = (
            '[Event "Nested preflight convergence"]\n'
            '[Result "*"]\n\n'
            f'1. e4 {{outer {{K. B.}} {tail}}} e5 *\n'
        )

        recovered = parse_pgn_text(source, strict=False)
        self.assertEqual(len(recovered), 1)
        game = recovered[0]
        self.assertEqual(
            game.warnings,
            ["nested brace comment delimiters normalized to parentheses"],
        )
        comment = game.line.moves[0].comments_after[0].text
        self.assertIn("(K. B.)", comment)
        self.assertTrue(comment.endswith(tail))

        canonical = serialize_pgn_text(recovered)
        reopened = parse_pgn_text(canonical, strict=True)
        self.assertEqual(reopened[0].tags, game.tags)
        self.assertEqual(reopened[0].line, game.line)
        self.assertFalse(reopened[0].warnings)

    def test_nested_comment_tail_counts_as_comment_not_many_source_tokens(self) -> None:
        tail = " ".join(f"word{i}" for i in range(40))
        source = f'[Result "*"]\n\n1. e4 {{outer {{K. B.}} {tail}}} e5 *\n'
        budget = PgnSourceBudget(
            PgnSourceLimits(
                max_source_bytes=1_000_000,
                max_text_chars=1_000_000,
                max_lexical_tokens=12,
                max_games=4,
            )
        )

        games = parse_pgn_text(source, strict=False, source_budget=budget)
        self.assertEqual(len(games), 1)
        self.assertLessEqual(budget.lexical_tokens, 12)
        self.assertEqual(budget.games, 1)

    def test_nested_recovery_remains_strict_mode_malformed(self) -> None:
        source = '[Result "*"]\n\n1. e4 {outer {K. B.} tail} e5 *\n'
        with self.assertRaises(PgnRoundTripError) as caught:
            parse_pgn_text(source, strict=True)
        self.assertEqual(caught.exception.code, PgnRoundTripErrorCode.MALFORMED_PGN)


if __name__ == "__main__":
    unittest.main()
