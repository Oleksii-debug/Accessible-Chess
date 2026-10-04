from __future__ import annotations

import unittest

from acs.position_editor import (
    PositionState,
    PositionValidationError,
    standard_position,
)


class PositionEditorPassiveBoundaryTests(unittest.TestCase):
    def test_from_fen_rejects_text_subclass_before_text_hooks(self) -> None:
        class HostileText(str):
            touched = False

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile FEN strip hook must not execute")

            def split(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile FEN split hook must not execute")

            def __eq__(self, other):
                type(self).touched = True
                raise AssertionError("hostile FEN equality hook must not execute")

        hostile = HostileText(
            "8/8/8/8/8/8/8/K6k w - - 0 1"
        )

        with self.assertRaisesRegex(PositionValidationError, "FEN must be text"):
            PositionState.from_fen(hostile)

        self.assertFalse(HostileText.touched)

    def test_with_castling_rejects_string_subclass_before_scalar_or_iteration_hooks(self) -> None:
        class HostileText(str):
            touched = False

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile castling strip hook must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("hostile castling iteration hook must not execute")

            def __eq__(self, other):
                type(self).touched = True
                raise AssertionError("hostile castling equality hook must not execute")

            def __hash__(self):
                type(self).touched = True
                raise AssertionError("hostile castling hash hook must not execute")

        position = standard_position()

        with self.assertRaisesRegex(
            PositionValidationError,
            "castling rights must be text or an iterable of text symbols",
        ):
            position.with_castling(HostileText("KQ"))

        self.assertFalse(HostileText.touched)

    def test_even_passive_text_subclasses_are_not_canonical_position_scalars(self) -> None:
        class PassiveText(str):
            pass

        with self.assertRaises(PositionValidationError):
            PositionState.from_fen(
                PassiveText("8/8/8/8/8/8/8/K6k w - - 0 1")
            )

        with self.assertRaises(PositionValidationError):
            standard_position().with_castling(PassiveText("KQ"))

    def test_rejected_piece_and_square_values_do_not_execute_repr(self) -> None:
        class HostileValue:
            touched = False

            def __repr__(self):
                type(self).touched = True
                raise AssertionError("hostile repr hook must not execute")

        position = standard_position()
        hostile = HostileValue()

        with self.assertRaisesRegex(PositionValidationError, "invalid piece symbol"):
            position.with_piece("a1", hostile)  # type: ignore[arg-type]
        with self.assertRaisesRegex(PositionValidationError, "invalid square"):
            position.piece_at(hostile)  # type: ignore[arg-type]
        with self.assertRaisesRegex(PositionValidationError, "invalid square"):
            position.with_piece(hostile, "Q")  # type: ignore[arg-type]

        self.assertFalse(HostileValue.touched)

    def test_oversized_integer_square_stays_in_position_error_domain(self) -> None:
        position = standard_position()
        oversized = 10 ** 5000

        with self.assertRaisesRegex(PositionValidationError, "invalid square"):
            position.piece_at(oversized)  # type: ignore[arg-type]
        with self.assertRaisesRegex(PositionValidationError, "invalid square"):
            position.with_piece(oversized, "Q")  # type: ignore[arg-type]

    def test_exact_builtin_fen_and_castling_inputs_keep_existing_semantics(self) -> None:
        fen = "8/8/8/8/8/8/8/K6k b - - 7 42"
        position = PositionState.from_fen(fen)

        self.assertEqual(position.to_fen(), fen)
        self.assertEqual(standard_position().with_castling("qK").castling, "Kq")
        self.assertEqual(
            standard_position().with_castling(("q", "K")).castling,
            "Kq",
        )


if __name__ == "__main__":
    unittest.main()
