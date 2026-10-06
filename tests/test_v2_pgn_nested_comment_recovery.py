from __future__ import annotations

import unittest
from unittest.mock import patch

from acs.gametree_legality import validate_game_legality
from acs.pgn_roundtrip import (
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    parse_pgn_text,
    serialize_pgn_text,
)


HISTORICAL_NESTED_COMMENT_PGN = '''[Event "Historical editorial notation"]
[Site "?"]
[Date "1854.??.??"]
[White "Pindar"]
[Black "Montgomery, H. P."]
[Result "*"]

1. e4 e6 2. d4 d5 3. exd5 Qxd5 4. Nc3 Bb4 5. Nf3 Nf6
6. Bd3 {A favorite move.} c5 {If White take dxc5, the Black {K. B.}
is brought into play; and if not, the advance c4 is threatened.} *'''


class V2PgnNestedCommentRecoveryTests(unittest.TestCase):
    def test_lawful_historical_nested_comment_is_recovery_only_and_serializable(self) -> None:
        with self.assertRaises(PgnRoundTripError) as strict_failure:
            parse_pgn_text(HISTORICAL_NESTED_COMMENT_PGN, strict=True)
        self.assertEqual(strict_failure.exception.code, PgnRoundTripErrorCode.MALFORMED_PGN)

        recovered = parse_pgn_text(HISTORICAL_NESTED_COMMENT_PGN, strict=False)
        self.assertEqual(len(recovered), 1)
        game = recovered[0]
        self.assertEqual(
            game.warnings,
            ["nested brace comment delimiters normalized to parentheses"],
        )
        comment = game.line.moves[-1].comments_after[-1]
        self.assertIn("Black (K. B.) is brought into play", " ".join(comment.text.split()))
        self.assertNotIn("{K. B.}", comment.text)

        legality = validate_game_legality(game)
        self.assertTrue(legality.complete, legality.issues)
        self.assertFalse(legality.issues)

        canonical = serialize_pgn_text(recovered)
        self.assertIn("Black (K. B.) is brought into play", " ".join(canonical.split()))
        reopened = parse_pgn_text(canonical, strict=True)
        self.assertEqual(len(reopened), 1)
        self.assertFalse(reopened[0].warnings)
        self.assertEqual(reopened[0].line.moves, game.line.moves)

    def test_literal_opening_brace_inside_valid_comment_keeps_legacy_round_trip(self) -> None:
        source = '[Result "*"]\n\n1. e4 {{ editorial opener} e5 *\n'
        games = parse_pgn_text(source, strict=True)
        self.assertEqual(games[0].line.moves[0].comments_after[0].text, "{ editorial opener")
        self.assertEqual(parse_pgn_text(serialize_pgn_text(games), strict=True), games)

    def test_recovered_nested_comment_cannot_bypass_post_parse_comment_limit(self) -> None:
        source = '[Result "*"]\n\n1. e4 {x {y} ' + ('z' * 32) + '} *\n'
        with patch("acs.pgn_roundtrip.MAX_PGN_COMMENT_CHARS", 10), patch(
            "acs.pgn_roundtrip.parse_games"
        ) as historical_parser:
            with self.assertRaises(PgnRoundTripError) as caught:
                parse_pgn_text(source, strict=False)
        self.assertEqual(caught.exception.code, PgnRoundTripErrorCode.COMMENT_SIZE_LIMIT)
        historical_parser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
