from __future__ import annotations

import unittest

from acs.gametree import Comment
from acs.pgn_roundtrip import (
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    parse_pgn_text,
    serialize_pgn_bytes,
    serialize_pgn_text,
)


class PgnUnicodeScalarSafetyTests(unittest.TestCase):
    def _game_with_comment(self, text: str):
        game = parse_pgn_text("1. e4 *", strict=True)[0]
        game.line.moves[0].comments_after = [Comment(text)]
        return game

    def test_text_serializer_rejects_lone_high_surrogate(self) -> None:
        game = self._game_with_comment("\ud800")
        with self.assertRaises(PgnRoundTripError) as raised:
            serialize_pgn_text((game,))
        self.assertEqual(PgnRoundTripErrorCode.INVALID_MODEL, raised.exception.code)

    def test_text_serializer_rejects_lone_low_surrogate(self) -> None:
        game = self._game_with_comment("\udfff")
        with self.assertRaises(PgnRoundTripError) as raised:
            serialize_pgn_text((game,))
        self.assertEqual(PgnRoundTripErrorCode.INVALID_MODEL, raised.exception.code)

    def test_byte_serializer_uses_same_stable_failure(self) -> None:
        game = self._game_with_comment("before\ud800after")
        with self.assertRaises(PgnRoundTripError) as raised:
            serialize_pgn_bytes((game,))
        self.assertEqual(PgnRoundTripErrorCode.INVALID_MODEL, raised.exception.code)

    def test_valid_non_bmp_unicode_remains_round_trip_safe(self) -> None:
        game = self._game_with_comment("Valid emoji 😀 and text")
        text = serialize_pgn_text((game,))
        encoded = serialize_pgn_bytes((game,))
        self.assertIn("😀", text)
        self.assertEqual(text.encode("utf-8"), encoded)


if __name__ == "__main__":
    unittest.main()
