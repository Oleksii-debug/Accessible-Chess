import sys
import unittest

from acs.history import HistoryError, ReviewHistory
from acs.ui_review_adapter import ReviewPresentationAdapter


class ReviewHistoryScalarFailClosedTests(unittest.TestCase):
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
        history.append("after-e4", san="e4", side="w", last_move="e2e4")
        history.append("after-e5", san="e5", side="b", last_move="e7e5")
        return history

    def test_oversized_digit_string_target_raises_history_error_atomically(self):
        history = self._history()
        before = history.current()

        with self.assertRaisesRegex(HistoryError, "too large to represent safely"):
            history.jump("9" * self.digit_count)

        after = history.current()
        self.assertEqual(after.node_id, before.node_id)
        self.assertEqual(after.ply, before.ply)
        self.assertEqual(after.snapshot.fen, before.snapshot.fen)

    def test_oversized_exact_integer_target_raises_history_error_atomically(self):
        history = self._history()
        before = history.current()
        target = 10 ** self.digit_count

        with self.assertRaisesRegex(HistoryError, "too large to represent safely"):
            history.jump(target)

        after = history.current()
        self.assertEqual(after.node_id, before.node_id)
        self.assertEqual(after.ply, before.ply)
        self.assertEqual(after.snapshot.fen, before.snapshot.fen)

    def test_presentation_adapter_contains_oversized_target_without_raw_runtime_error(self):
        history = self._history()
        adapter = ReviewPresentationAdapter(history, language="en")
        before = adapter.current()

        result = adapter.jump("9" * self.digit_count)

        self.assertFalse(result.ok)
        self.assertEqual(result.view, before)
        self.assertIn("Could not select the requested history position", result.announcement)
        self.assertNotIn("Exceeds the limit", result.announcement)
        self.assertNotIn(str(self.digit_count), result.announcement)


if __name__ == "__main__":
    unittest.main()
