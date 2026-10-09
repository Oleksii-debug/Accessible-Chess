import sys
import unittest

from acs.history import HistoryError, HistoryErrorCode, ReviewHistory
from acs.ui_review_adapter import ReviewPresentationAdapter


class ReviewHistoryTargetFailClosedCurrentTests(unittest.TestCase):
    def setUp(self):
        get_limit = getattr(sys, "get_int_max_str_digits", None)
        if get_limit is None:
            self.skipTest("runtime has no integer-string digit safety limit")
        limit = get_limit()
        if limit == 0:
            self.skipTest("runtime integer-string digit safety limit is disabled")
        self.digit_count = limit + 1

    @staticmethod
    def _history():
        history = ReviewHistory("initial")
        history.append("after-e4", san="e4", side="w", last_move="e4")
        history.append("after-e5", san="e5", side="b", last_move="e5")
        return history

    def test_oversized_digit_string_target_is_domain_error_and_cursor_atomic(self):
        history = self._history()
        before = history.current()

        with self.assertRaisesRegex(HistoryError, "too large to represent safely"):
            history.jump("9" * self.digit_count)

        after = history.current()
        self.assertEqual(after, before)

    def test_oversized_exact_integer_target_is_domain_error_and_cursor_atomic(self):
        history = self._history()
        before = history.current()
        target = 10 ** self.digit_count

        with self.assertRaisesRegex(HistoryError, "too large to represent safely"):
            history.jump(target)

        after = history.current()
        self.assertEqual(after, before)

    def test_adapter_contains_runtime_integer_limit_detail(self):
        history = self._history()
        adapter = ReviewPresentationAdapter(history, language="en")
        before = adapter.current()

        result = adapter.jump("9" * self.digit_count)

        self.assertFalse(result.ok)
        self.assertEqual(result.view, before)
        self.assertIn(
            "Could not select the requested history position",
            result.announcement,
        )
        self.assertNotIn("Exceeds the limit", result.announcement)
        self.assertNotIn("integer string conversion", result.announcement)
        self.assertNotIn("sys.set_int_max_str_digits", result.announcement)
        self.assertNotIn(str(self.digit_count), result.announcement)

    def test_adapter_contains_oversized_exact_integer_target(self):
        history = self._history()
        adapter = ReviewPresentationAdapter(history, language="uk")
        before = adapter.current()
        target = 10 ** self.digit_count

        result = adapter.jump(target)

        self.assertFalse(result.ok)
        self.assertEqual(result.view, before)
        self.assertIn("Не вдалося перейти до запитаної позиції", result.announcement)
        self.assertNotIn("Exceeds the limit", result.announcement)
        self.assertNotIn("integer string conversion", result.announcement)
        self.assertNotIn("sys.set_int_max_str_digits", result.announcement)

    def test_snapshot_text_subclasses_are_rejected_before_text_hooks(self):
        class HostileText(str):
            hook_calls = 0

            def strip(self, *args, **kwargs):
                type(self).hook_calls += 1
                raise AssertionError("snapshot strip hook must not run")

            def __eq__(self, other):
                type(self).hook_calls += 1
                raise AssertionError("snapshot equality hook must not run")

        with self.assertRaises(HistoryError) as caught:
            ReviewHistory(HostileText("root"))
        self.assertEqual(caught.exception.code, HistoryErrorCode.INVALID_SNAPSHOT)
        self.assertEqual(HostileText.hook_calls, 0)

        history = self._history()
        before = history.export_tree()
        for field, value in (
            ("san", HostileText("e4")),
            ("last_move", HostileText("e4")),
            ("side", HostileText("w")),
        ):
            with self.subTest(field=field):
                with self.assertRaises(HistoryError) as caught:
                    history.append("candidate", **{field: value})
                self.assertEqual(
                    caught.exception.code,
                    HistoryErrorCode.INVALID_SNAPSHOT,
                )
                self.assertEqual(history.export_tree(), before)
                self.assertEqual(HostileText.hook_calls, 0)

    def test_supported_targets_keep_existing_semantics(self):
        history = self._history()

        self.assertEqual(history.parse_target("0"), 0)
        self.assertEqual(history.parse_target("start"), 0)
        self.assertEqual(history.parse_target("1w"), 1)
        self.assertEqual(history.parse_target("1b"), 2)
        self.assertEqual(history.parse_target("1..."), 2)
        self.assertEqual(history.parse_target("end"), 2)


if __name__ == "__main__":
    unittest.main()
