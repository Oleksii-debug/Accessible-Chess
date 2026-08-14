import unittest

from acs.notation import NotationError, format_san


class NotationFormatterTests(unittest.TestCase):
    def test_san_profile_preserves_san_and_normalises_zero_castling(self):
        self.assertEqual(format_san("Nf3", "san"), "Nf3")
        self.assertEqual(format_san("0-0+", "san"), "O-O+")

    def test_ukrainian_piece_names_replace_san_letters(self):
        self.assertEqual(format_san("Nf3", "uk_literal"), "кінь f 3")
        self.assertEqual(format_san("Bb5+", "uk_literal"), "слон b 5, шах")
        self.assertEqual(format_san("Qh5#", "uk_literal"), "ферзь h 5, мат")

    def test_english_literal_piece_names(self):
        self.assertEqual(format_san("Nf3", "en_literal"), "knight f 3")
        self.assertEqual(format_san("Rxe7+", "en_literal"), "rook takes e 7, check")

    def test_pawn_moves_captures_and_promotion(self):
        self.assertEqual(format_san("e4", "uk_literal"), "пішак e 4")
        self.assertEqual(format_san("exd5", "uk_literal"), "пішак e бере d 5")
        self.assertEqual(
            format_san("exd8=Q+", "uk_literal"),
            "пішак e бере d 8 перетворення на ферзь, шах",
        )
        self.assertEqual(
            format_san("a8=N", "en_literal"),
            "pawn a 8 promotes to knight",
        )

    def test_disambiguation_is_spoken_explicitly(self):
        self.assertEqual(
            format_san("Nbd2", "uk_literal"),
            "кінь з вертикалі b d 2",
        )
        self.assertEqual(
            format_san("R1e2", "en_literal"),
            "rook from rank 1 e 2",
        )
        self.assertEqual(
            format_san("Qh4e1", "en_literal"),
            "queen from square h 4 e 1",
        )

    def test_castling_and_suffixes(self):
        self.assertEqual(format_san("O-O", "uk_literal"), "коротка рокіровка")
        self.assertEqual(format_san("O-O-O+", "uk_literal"), "довга рокіровка, шах")
        self.assertEqual(format_san("0-0#", "en_literal"), "kingside castling, checkmate")

    def test_invalid_profile_or_token_fails_precisely(self):
        with self.assertRaisesRegex(NotationError, "unknown notation profile"):
            format_san("e4", "robot")
        with self.assertRaisesRegex(NotationError, "unsupported SAN token"):
            format_san("not-a-move", "uk_literal")


if __name__ == "__main__":
    unittest.main()
