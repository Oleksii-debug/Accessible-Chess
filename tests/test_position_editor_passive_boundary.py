from __future__ import annotations

import unittest

from acs.position_editor import (
    MAX_FEN_CHARS,
    PositionState,
    PositionValidationError,
    empty_position,
)


class PositionEditorPassiveBoundaryTests(unittest.TestCase):
    def test_hostile_fen_subclass_is_rejected_before_text_hooks(self) -> None:
        class HostileText(str):
            touched = False

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile FEN strip hook must not execute")

            def split(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile FEN split hook must not execute")

            def __len__(self):
                type(self).touched = True
                raise AssertionError("hostile FEN length hook must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("hostile FEN iterator hook must not execute")

        hostile = HostileText("8/8/8/8/8/8/8/K6k w - - 0 1")
        with self.assertRaisesRegex(PositionValidationError, "FEN must be text"):
            PositionState.from_fen(hostile)
        self.assertFalse(HostileText.touched)

    def test_direct_fen_has_a_bounded_preparse_envelope(self) -> None:
        oversized = "8" * (MAX_FEN_CHARS + 1)
        with self.assertRaisesRegex(PositionValidationError, "FEN is too long"):
            PositionState.from_fen(oversized)

    def test_hostile_castling_text_is_rejected_before_text_hooks(self) -> None:
        class HostileText(str):
            touched = False

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile castling strip hook must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("hostile castling iterator hook must not execute")

            def __eq__(self, other):
                type(self).touched = True
                raise AssertionError("hostile castling equality hook must not execute")

            def __hash__(self):
                type(self).touched = True
                raise AssertionError("hostile castling hash hook must not execute")

        hostile = HostileText("KQ")
        with self.assertRaisesRegex(
            PositionValidationError, "castling rights text must be exact built-in text"
        ):
            empty_position().with_castling(hostile)
        self.assertFalse(HostileText.touched)

    def test_exact_builtin_inputs_keep_existing_semantics(self) -> None:
        fen = "8/8/8/8/8/8/8/K6k w - - 0 1"
        self.assertEqual(PositionState.from_fen(fen).to_fen(), fen)

        position = (
            empty_position()
            .with_piece("e1", "K")
            .with_piece("e8", "k")
            .with_castling("qK")
        )
        self.assertEqual(position.castling, "Kq")

        iterable = position.with_castling(("Q", "k"))
        self.assertEqual(iterable.castling, "Qk")


if __name__ == "__main__":
    unittest.main()
