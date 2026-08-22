from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.search_service import GameSearchQuery, GameSearchService


class SearchResourceBoundsTests(unittest.TestCase):
    def test_all_text_filters_reject_pathological_oversize_terms_before_sql(self) -> None:
        oversized = "x" * 257
        for field in ("player", "event", "eco", "opening", "source_name"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "maximum search term length of 256"):
                    GameSearchQuery(**{field: oversized}).normalized()

    def test_256_character_term_remains_valid_and_literal(self) -> None:
        term = "%_\\" + ("a" * 253)
        normalized = GameSearchQuery(player=term).normalized()
        self.assertEqual(normalized.player, term)

    def test_whitespace_normalization_happens_before_resource_bound(self) -> None:
        raw = (" word " * 80)
        normalized = GameSearchQuery(event=raw).normalized()
        self.assertLessEqual(len(normalized.event or ""), 256)
        self.assertNotIn("  ", normalized.event or "")

    def test_oversize_filter_is_rejected_without_executing_database_query(self) -> None:
        db = AcsDatabase()
        try:
            service = GameSearchService(db)
            before = db.conn.total_changes
            with self.assertRaisesRegex(ValueError, "maximum search term length of 256"):
                service.search(GameSearchQuery(opening="z" * 257))
            self.assertEqual(db.conn.total_changes, before)
        finally:
            db.close()

    def test_non_text_filter_types_still_fail_closed(self) -> None:
        for field in ("player", "event", "eco", "opening", "source_name"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(TypeError, f"{field} must be text"):
                    GameSearchQuery(**{field: 123}).normalized()


if __name__ == "__main__":
    unittest.main()
