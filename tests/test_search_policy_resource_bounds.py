from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.search_policy import (
    MAX_RAW_SEARCH_TERM_CHARS,
    MAX_SEARCH_TERM_CHARS,
    normalize_search_date_bound,
    normalize_search_term,
)
from acs.search_service import GameSearchQuery


class SearchPolicyResourceBoundsTests(unittest.TestCase):
    def test_raw_term_is_bounded_before_whitespace_normalization(self) -> None:
        oversized = " " * (MAX_RAW_SEARCH_TERM_CHARS + 1)

        with self.assertRaisesRegex(ValueError, "maximum raw search term length"):
            normalize_search_term(oversized, name="event")
        with self.assertRaisesRegex(ValueError, "maximum raw search term length"):
            GameSearchQuery(event=oversized).normalized()
        with AcsDatabase() as database:
            with self.assertRaisesRegex(ValueError, "maximum raw search term length"):
                database.search_games(event=oversized)

    def test_raw_date_bound_is_bounded_before_unicode_normalization(self) -> None:
        oversized = " " * (MAX_RAW_SEARCH_TERM_CHARS + 1)

        with self.assertRaisesRegex(ValueError, "maximum raw search term length"):
            normalize_search_date_bound(oversized, name="date_from")
        with self.assertRaisesRegex(ValueError, "maximum raw search term length"):
            GameSearchQuery(date_from=oversized).normalized()
        with AcsDatabase() as database:
            with self.assertRaisesRegex(ValueError, "maximum raw search term length"):
                database.search_games(date_from=oversized)

    def test_raw_limit_preserves_existing_normalized_semantics(self) -> None:
        self.assertIsNone(
            normalize_search_term(" " * MAX_RAW_SEARCH_TERM_CHARS, name="event")
        )

        with self.assertRaisesRegex(ValueError, "maximum search term length"):
            normalize_search_term("x" * (MAX_SEARCH_TERM_CHARS + 1), name="event")

        self.assertEqual(
            normalize_search_term("  Open   file\tstrategy  ", name="event"),
            "Open file strategy",
        )
        self.assertEqual(
            normalize_search_date_bound(" 2026.10.04 ", name="date_from"),
            "2026.10.04",
        )


if __name__ == "__main__":
    unittest.main()
