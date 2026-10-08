import unittest

from acs.notation import (
    MAX_SAN_CHARS,
    NotationError,
    format_accessible_compact_san,
    format_san,
    parse_san,
)


class NotationFormatterTests(unittest.TestCase):
    def test_san_profile_preserves_san_and_normalises_zero_castling(self):
        self.assertEqual(format_san("Nf3", "san"), "Nf3")
        self.assertEqual(format_san("0-0+", "san"), "O-O+")
        self.assertEqual(format_san("0-0-0#", "san"), "O-O-O#")

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

    def test_mixed_zero_letter_castling_is_not_san(self):
        for token in ("0-O", "O-0", "0-O-O", "O-0-O", "O-O-0", "0-0-O"):
            with self.subTest(token=token):
                with self.assertRaises(NotationError):
                    format_san(token, "san")
                with self.assertRaises(NotationError):
                    format_san(token, "uk_literal")
                with self.assertRaises(NotationError):
                    format_accessible_compact_san(token, "en")

    def test_compact_accessible_profile_spaces_piece_file_rank(self):
        self.assertEqual(format_accessible_compact_san("Nf3", "en"), "N f 3")
        self.assertEqual(format_accessible_compact_san("Nc6", "uk"), "N c 6")
        self.assertEqual(format_accessible_compact_san("Rxe7+", "en"), "R captures e 7, check")
        self.assertEqual(format_accessible_compact_san("exd5", "uk"), "e б’є d 5")
        self.assertEqual(format_accessible_compact_san("O-O#", "uk"), "коротка рокіровка, мат")

    def test_compact_accessible_profile_separates_disambiguation(self):
        self.assertEqual(format_accessible_compact_san("Nbd2", "en"), "N b d 2")
        self.assertEqual(format_accessible_compact_san("R1e2", "en"), "R 1 e 2")
        self.assertEqual(format_accessible_compact_san("Qh4e1", "uk"), "Q h 4 e 1")
        self.assertEqual(
            format_accessible_compact_san("exd8=Q+", "en"),
            "e captures d 8=Q, check",
        )

    def test_compact_language_is_passive_before_comparison(self):
        class ActiveLanguage(str):
            def __eq__(self, other):
                raise AssertionError("language equality hook must not run")

        with self.assertRaisesRegex(NotationError, "language must be text"):
            format_accessible_compact_san("Nf3", ActiveLanguage("en"))

        # Preserve the historical built-in-string fallback policy: only exact
        # "en" selects English; other passive built-in strings use Ukrainian.
        self.assertEqual(format_accessible_compact_san("Nf3", "unknown"), "N f 3")

    def test_coordinate_like_pawn_text_is_not_san(self):
        for token in ("e2e4", "ee4", "1e4"):
            with self.subTest(token=token):
                with self.assertRaisesRegex(NotationError, "pawn move SAN"):
                    parse_san(token)
                with self.assertRaises(NotationError):
                    format_san(token, "san")

    def test_promotion_is_pawn_only_and_requires_last_rank(self):
        invalid = ("Ne8=Q", "Nxe8=Q", "e4=Q", "exd4=N", "e8", "exd8")
        for token in invalid:
            with self.subTest(token=token):
                with self.assertRaises(NotationError):
                    parse_san(token)
                with self.assertRaises(NotationError):
                    format_accessible_compact_san(token, "en")

        self.assertEqual(format_san("e8=Q", "san"), "e8=Q")
        self.assertEqual(format_san("exd1=N+", "san"), "exd1=N+")

    def test_two_character_piece_disambiguation_must_be_source_square(self):
        for token in ("Nabe4", "N12e4", "N1ae4"):
            with self.subTest(token=token):
                with self.assertRaises(NotationError):
                    parse_san(token)
        self.assertEqual(parse_san("Qh4e1").disambiguation, "h4")

    def test_king_disambiguation_is_not_san_grammar(self):
        for token in ("Kae2", "K1e2", "Ka1e2", "Kaxd2", "K1xd2"):
            with self.subTest(token=token):
                with self.assertRaisesRegex(NotationError, "king SAN cannot be disambiguated"):
                    parse_san(token)
                with self.assertRaises(NotationError):
                    format_san(token, "san")
                with self.assertRaises(NotationError):
                    format_accessible_compact_san(token, "en")

        self.assertEqual(format_san("Ke2", "san"), "Ke2")
        self.assertEqual(format_san("Kxe2+", "en_literal"), "king takes e 2, check")

    def test_san_representation_is_bounded_before_normalization(self):
        # The budget applies to raw input, before strip()/regex work.  A token
        # at the ceiling may contain harmless surrounding whitespace, but one
        # extra raw character fails closed on every public SAN formatter path.
        padded = "e4".center(MAX_SAN_CHARS)
        self.assertEqual(parse_san(padded).destination, "e4")
        self.assertEqual(format_san(padded, "san"), "e4")

        oversized = " " * (MAX_SAN_CHARS - 1) + "e4"
        self.assertGreater(len(oversized), MAX_SAN_CHARS)
        for operation in (
            parse_san,
            lambda value: format_san(value, "san"),
            lambda value: format_san(value, "uk_literal"),
            lambda value: format_accessible_compact_san(value, "en"),
        ):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(NotationError, "too long"):
                    operation(oversized)

    def test_san_boundary_rejects_active_text_subclasses(self):
        class ActiveText(str):
            def __str__(self):
                raise AssertionError("__str__ must not run")

            def strip(self, *args, **kwargs):
                raise AssertionError("strip must not run")

            def __hash__(self):
                raise AssertionError("hash must not run")

        with self.assertRaisesRegex(NotationError, "SAN token must be text"):
            parse_san(ActiveText("e4"))
        with self.assertRaisesRegex(NotationError, "SAN token must be text"):
            format_san(ActiveText("e4"), "san")
        with self.assertRaisesRegex(NotationError, "unknown notation profile"):
            format_san("e4", ActiveText("san"))

    def test_invalid_profile_or_token_fails_precisely(self):
        with self.assertRaisesRegex(NotationError, "unknown notation profile"):
            format_san("e4", "robot")
        with self.assertRaisesRegex(NotationError, "unsupported SAN token"):
            format_san("not-a-move", "uk_literal")
        with self.assertRaisesRegex(NotationError, "unsupported SAN token"):
            format_san("not-a-move", "san")


if __name__ == "__main__":
    unittest.main()
