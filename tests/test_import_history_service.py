from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.import_history_service import ImportHistoryQuery, ImportHistoryService


PGN = '''[Event "Audit"]
[Site "Kyiv"]
[Date "2026.08.15"]
[Round "1"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 1-0
'''


class ImportHistoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = AcsDatabase(":memory:")
        self.service = ImportHistoryService(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_successful_attempt_exposes_linked_source_provenance(self) -> None:
        report = self.db.import_pgn_text(PGN, "audit.pgn")
        item = self.service.get(report.attempt_id)
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.status, "full")
        self.assertEqual(item.game_count, 1)
        self.assertIsNotNone(item.source)
        assert item.source is not None
        self.assertEqual(item.source.source_id, report.source_id)
        self.assertEqual(item.source.source_name, "audit.pgn")
        self.assertEqual(item.source.sha256, item.sha256)

    def test_failed_attempt_has_no_fabricated_source(self) -> None:
        attempt_id = self.db._create_import_attempt("broken.cbh", "cbh", "a" * 64)
        with self.db.conn:
            self.db._finish_import_attempt(
                attempt_id,
                status="failed",
                error_message="Unsupported component layout",
            )
        item = self.service.get(attempt_id)
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.status, "failed")
        self.assertIsNone(item.source)
        self.assertEqual(item.error_message, "Unsupported component layout")

    def test_search_filters_format_and_status(self) -> None:
        self.db.import_pgn_text(PGN, "one.pgn")
        bad = self.db._create_import_attempt("bad.cbh", "cbh", "b" * 64)
        with self.db.conn:
            self.db._finish_import_attempt(bad, status="damaged", error_message="damaged")

        page = self.service.search(ImportHistoryQuery(status="damaged", source_format="CBH"))
        self.assertEqual(len(page.items), 1)
        self.assertEqual(page.items[0].attempt_id, bad)
        self.assertEqual(page.items[0].source_format, "cbh")

    def test_keyset_pagination_is_stable(self) -> None:
        for index in range(5):
            self.db.import_pgn_text(PGN, f"{index}.pgn")
        first = self.service.search(ImportHistoryQuery(limit=2))
        self.assertEqual(len(first.items), 2)
        self.assertIsNotNone(first.next_after_attempt_id)

        self.db.import_pgn_text(PGN, "newer.pgn")
        second = self.service.search(
            ImportHistoryQuery(limit=2, after_attempt_id=first.next_after_attempt_id)
        )
        first_ids = {item.attempt_id for item in first.items}
        second_ids = {item.attempt_id for item in second.items}
        self.assertTrue(first_ids.isdisjoint(second_ids))
        self.assertTrue(all(i < first.next_after_attempt_id for i in second_ids))

    def test_invalid_bounds_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.search(ImportHistoryQuery(limit=0))
        with self.assertRaises(ValueError):
            self.service.search(ImportHistoryQuery(limit=201))
        with self.assertRaises(ValueError):
            self.service.search(ImportHistoryQuery(after_attempt_id=0))

    def test_attempt_ids_reject_coercion_and_sqlite_integer_overflow(self) -> None:
        sqlite_max = (1 << 63) - 1

        # The exact SQLite upper bound is a valid application scalar and must not
        # fail inside sqlite3 binding even when no matching row exists.
        self.assertIsNone(self.service.get(sqlite_max))
        self.assertEqual(
            self.service.search(ImportHistoryQuery(after_attempt_id=sqlite_max)).items,
            (),
        )

        for bad in (True, 1.0, "1"):
            with self.subTest(api="get", value=bad):
                with self.assertRaises(TypeError):
                    self.service.get(bad)
            with self.subTest(api="search", value=bad):
                with self.assertRaises(TypeError):
                    self.service.search(ImportHistoryQuery(after_attempt_id=bad))

        for bad in (0, -1, sqlite_max + 1):
            with self.subTest(api="get", value=bad):
                with self.assertRaises(ValueError):
                    self.service.get(bad)
            with self.subTest(api="search", value=bad):
                with self.assertRaises(ValueError):
                    self.service.search(ImportHistoryQuery(after_attempt_id=bad))


if __name__ == "__main__":
    unittest.main()