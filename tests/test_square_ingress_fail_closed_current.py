from __future__ import annotations

import unittest

from acs.chesscore import parse_sq
from acs.webapp import AccessibleChessAPI


class SquareIngressFailClosedTests(unittest.TestCase):
    def test_chesscore_rejection_does_not_repr_str_or_coerce_unknown_object(self) -> None:
        class HostileValue:
            touched = False

            @classmethod
            def _touch(cls, hook: str):
                cls.touched = True
                raise AssertionError(f"rejected square must not execute {hook}")

            def __repr__(self):
                type(self)._touch("__repr__")

            def __str__(self):
                type(self)._touch("__str__")

            def __int__(self):
                type(self)._touch("__int__")

        hostile = HostileValue()

        with self.assertRaisesRegex(ValueError, "^Неправильне поле$"):
            parse_sq(hostile)

        self.assertFalse(HostileValue.touched)

    def test_text_subclass_is_rejected_without_text_or_repr_hooks(self) -> None:
        class HostileText(str):
            touched = False

            @classmethod
            def _touch(cls, hook: str):
                cls.touched = True
                raise AssertionError(f"rejected square must not execute {hook}")

            def strip(self, *args, **kwargs):
                type(self)._touch("strip")

            def lower(self, *args, **kwargs):
                type(self)._touch("lower")

            def __eq__(self, other):
                type(self)._touch("__eq__")

            def __hash__(self):
                type(self)._touch("__hash__")

            def __repr__(self):
                type(self)._touch("__repr__")

        hostile = HostileText("e4")

        with self.assertRaisesRegex(ValueError, "^Неправильне поле$"):
            parse_sq(hostile)

        api = AccessibleChessAPI(lang="en")
        with self.assertRaisesRegex(ValueError, "^Неправильне поле$"):
            api.square_label(hostile)

        result = api.activate_square(hostile)
        self.assertFalse(result["ok"])
        self.assertEqual(result["announcement"], "Неправильне поле")
        self.assertIsNone(api.selected_source)
        self.assertFalse(HostileText.touched)

    def test_square_label_rejects_coercible_and_out_of_range_values(self) -> None:
        class HostileIntLike:
            touched = False

            def __int__(self):
                type(self).touched = True
                raise AssertionError("square_label must not coerce with int()")

            def __repr__(self):
                type(self).touched = True
                raise AssertionError("square_label must not repr rejected input")

        api = AccessibleChessAPI(lang="uk")

        with self.assertRaises(ValueError):
            api.square_label(HostileIntLike())
        self.assertFalse(HostileIntLike.touched)

        for value in (-1, 64, True, False, 28.0, b"e4"):
            with self.subTest(type=type(value).__name__):
                with self.assertRaises(ValueError):
                    api.square_label(value)

    def test_exact_builtin_square_forms_keep_spoken_semantics(self) -> None:
        api = AccessibleChessAPI(lang="uk")

        self.assertEqual(parse_sq(" E4 "), 28)
        self.assertEqual(parse_sq(28), 28)
        self.assertEqual(api.square_label(" E4 "), "e 4")
        self.assertEqual(api.square_label(28), "e 4")
        self.assertEqual(api.square_label("e2"), "e 2, білий пішак")


if __name__ == "__main__":
    unittest.main()
