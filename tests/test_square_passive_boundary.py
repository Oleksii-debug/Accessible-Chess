from __future__ import annotations

import unittest

from acs.squares import normalize_square, parse_square, square_name


class SquarePassiveBoundaryTests(unittest.TestCase):
    def test_hostile_text_subclass_is_rejected_before_text_hooks(self) -> None:
        class HostileText(str):
            touched = False

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile square strip hook must not execute")

            def lower(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile square lower hook must not execute")

            def __eq__(self, other):
                type(self).touched = True
                raise AssertionError("hostile square equality hook must not execute")

            def __hash__(self):
                type(self).touched = True
                raise AssertionError("hostile square hash hook must not execute")

        hostile = HostileText("e4")
        with self.assertRaisesRegex(ValueError, "square must be canonical text"):
            parse_square(hostile)
        with self.assertRaisesRegex(ValueError, "square must be canonical text"):
            normalize_square(hostile)
        self.assertFalse(HostileText.touched)

    def test_hostile_integer_subclass_is_rejected_before_numeric_hooks(self) -> None:
        class HostileInt(int):
            touched = False

            def __le__(self, other):
                type(self).touched = True
                raise AssertionError("hostile square comparison hook must not execute")

            def __lt__(self, other):
                type(self).touched = True
                raise AssertionError("hostile square comparison hook must not execute")

            def __mod__(self, other):
                type(self).touched = True
                raise AssertionError("hostile square modulo hook must not execute")

            def __floordiv__(self, other):
                type(self).touched = True
                raise AssertionError("hostile square division hook must not execute")

        hostile = HostileInt(28)
        with self.assertRaisesRegex(ValueError, "square must be canonical text"):
            parse_square(hostile)
        with self.assertRaisesRegex(ValueError, "square index must be an integer"):
            square_name(hostile)
        with self.assertRaisesRegex(ValueError, "square must be canonical text"):
            normalize_square(hostile)
        self.assertFalse(HostileInt.touched)

    def test_even_passive_subclasses_are_not_canonical_square_scalars(self) -> None:
        class TextSubclass(str):
            pass

        class IntSubclass(int):
            pass

        for value in (TextSubclass("e4"), IntSubclass(28)):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(ValueError):
                    parse_square(value)
                with self.assertRaises(ValueError):
                    normalize_square(value)
        with self.assertRaises(ValueError):
            square_name(IntSubclass(28))

    def test_exact_builtin_square_inputs_keep_existing_semantics(self) -> None:
        self.assertEqual(parse_square(" E4 "), 28)
        self.assertEqual(parse_square(28), 28)
        self.assertEqual(square_name(28), "e4")
        self.assertEqual(normalize_square(" H8 "), "h8")
        self.assertEqual(normalize_square(0), "a1")

    def test_boolean_values_remain_rejected(self) -> None:
        for value in (True, False):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_square(value)
                with self.assertRaises(ValueError):
                    square_name(value)


if __name__ == "__main__":
    unittest.main()
