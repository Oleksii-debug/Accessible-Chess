from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.acsdb import AcsDatabase
from acs.search_service import GameSearchQuery, GameSearchService


class D07UnicodeSearchMatrixAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "unicode-search.acsdb"
        self.db = AcsDatabase(self.db_path)
        self.source_id = self.db.add_source("unicode-matrix.pgn", "pgn")
        rows = [
            (self.source_id, 1, "full", "[]", "Cafe\u0301 Cup", "Kyiv", "2026.09.10", "1", "White 1", "Black 1", "1-0", "C42", None, None, "*"),
            (self.source_id, 2, "full", "[]", "Ｆｕｌｌｗｉｄｔｈ Cup", "Kyiv", "2026.09.10", "2", "White 2", "Black 2", "1-0", "C42", None, None, "*"),
            (self.source_id, 3, "full", "[]", "Straße Masters", "Kyiv", "2026.09.10", "3", "White 3", "Black 3", "1-0", "C42", None, None, "*"),
            (self.source_id, 4, "full", "[]", "İstanbul Open", "Kyiv", "2026.09.10", "4", "White 4", "Black 4", "1-0", "C42", None, None, "*"),
            (self.source_id, 5, "full", "[]", "Istanbul Plain", "Kyiv", "2026.09.10", "5", "White 5", "Black 5", "1-0", "C42", None, None, "*"),
            (self.source_id, 6, "full", "[]", "ΟΣ Masters", "Kyiv", "2026.09.10", "6", "White 6", "Black 6", "1-0", "C42", None, None, "*"),
            (self.source_id, 7, "full", "[]", "Олексій Меморіал", "Kyiv", "2026.09.10", "7", "White 7", "Black 7", "1-0", "C42", None, None, "*"),
            (self.source_id, 8, "full", "[]", "東京棋院杯", "Kyiv", "2026.09.10", "8", "White 8", "Black 8", "1-0", "C42", None, None, "*"),
            (self.source_id, 9, "full", "[]", "Resume\u0301 Accent", "Kyiv", "2026.09.10", "9", "White 9", "Black 9", "1-0", "C42", None, None, "*"),
            (self.source_id, 10, "full", "[]", "Chess 😀 Event", "Kyiv", "2026.09.10", "10", "White 10", "Black 10", "1-0", "C42", None, None, "*"),
            (self.source_id, 11, "full", "[]", "Literal%Event", "Kyiv", "2026.09.10", "11", "White 11", "Black 11", "1-0", "C42", None, None, "*"),
            (self.source_id, 12, "full", "[]", "Literal_Event", "Kyiv", "2026.09.10", "12", "White 12", "Black 12", "1-0", "C42", None, None, "*"),
            (self.source_id, 13, "full", "[]", "Literal\\Backslash", "Kyiv", "2026.09.10", "13", "White 13", "Black 13", "1-0", "C42", None, None, "*"),
            (self.source_id, 14, "full", "[]", "SQL ' OR 1=1 -- sentinel", "Kyiv", "2026.09.10", "14", "White 14", "Black 14", "1-0", "C42", None, None, "*"),
            (self.source_id, 15, "full", "[]", "x" * 256, "Kyiv", "2026.09.10", "15", "White 15", "Black 15", "1-0", "C42", None, None, "*"),
        ]
        with self.db.conn:
            self.db.conn.executemany(
                """INSERT INTO games(
                    source_id, source_index, import_status, warnings_json,
                    event, site, game_date, round, white, black, result,
                    eco, opening, start_fen, pgn_text
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
        self.service = GameSearchService(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.tempdir.cleanup()

    def _direct_ids(self, **kwargs) -> list[int]:
        return [int(row["id"]) for row in self.db.search_games(**kwargs)]

    def _service_ids(self, **kwargs) -> list[int]:
        return [
            item.game_id
            for item in self.service.search(GameSearchQuery(**kwargs)).items
        ]

    def _event_snapshot(self) -> dict[str, list[int]]:
        cases = {
            "nfc_from_nfd": ("Café Cup", [1]),
            "nfd_from_nfd": ("Cafe\u0301 Cup", [1]),
            "nfkc_fullwidth": ("Fullwidth Cup", [2]),
            "german_sharp_s": ("STRASSE", [3]),
            "turkish_dotted_i_exact_fold": ("i\u0307stanbul open", [4]),
            "turkish_dotted_i_not_plain_i": ("istanbul open", []),
            "turkish_ascii_i": ("ISTANBUL PLAIN", [5]),
            "greek_final_sigma": ("ος masters", [6]),
            "cyrillic_casefold": ("ОЛЕКСІЙ", [7]),
            "cjk_literal": ("東京", [8]),
            "combining_mark_equivalent": ("Resumé Accent", [9]),
            "combining_mark_significant": ("Resume Accent", []),
            "emoji": ("😀", [10]),
            "literal_percent": ("%", [11]),
            "literal_underscore": ("_", [12]),
            "literal_backslash": ("\\", [13]),
            "sql_injection_text_is_literal": ("' OR 1=1 --", [14]),
            "max_term_256": ("x" * 256, [15]),
        }
        observed: dict[str, list[int]] = {}
        for name, (term, expected) in cases.items():
            with self.subTest(case=name, term=term):
                direct = self._direct_ids(event=term)
                service = self._service_ids(event=term)
                self.assertEqual(direct, expected)
                self.assertEqual(service, expected)
                self.assertEqual(service, direct)
                observed[name] = service
        return observed

    def _assert_bounds(self) -> None:
        with self.assertRaisesRegex(ValueError, "maximum search term length"):
            self.db.search_games(event="x" * 257)
        with self.assertRaisesRegex(ValueError, "maximum search term length"):
            self.service.search(GameSearchQuery(event="x" * 257))
        self.service.search(GameSearchQuery(limit=200))
        with self.assertRaisesRegex(ValueError, "limit"):
            self.service.search(GameSearchQuery(limit=201))

    def _reopen(self) -> None:
        self.db.close()
        self.db = AcsDatabase(self.db_path)
        self.service = GameSearchService(self.db)

    def test_unicode_literal_and_bound_matrix_is_stable_after_reopen(self) -> None:
        before = self._event_snapshot()
        self._assert_bounds()
        self._reopen()
        after = self._event_snapshot()
        self._assert_bounds()
        self.assertEqual(after, before)

    def test_keyset_paging_remains_duplicate_free_across_concurrent_append(self) -> None:
        first = self.service.search(GameSearchQuery(limit=4))
        self.assertEqual([item.game_id for item in first.items], [1, 2, 3, 4])
        self.assertTrue(first.has_more)
        self.assertEqual(first.next_after_game_id, 4)

        writer = AcsDatabase(self.db_path)
        try:
            with writer.conn:
                writer.conn.execute(
                    """INSERT INTO games(
                        source_id, source_index, import_status, warnings_json,
                        event, site, game_date, round, white, black, result,
                        eco, opening, start_fen, pgn_text
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        self.source_id,
                        16,
                        "full",
                        "[]",
                        "Concurrent Append",
                        "Kyiv",
                        "2026.09.10",
                        "16",
                        "White 16",
                        "Black 16",
                        "1-0",
                        "C42",
                        None,
                        None,
                        "*",
                    ),
                )
        finally:
            writer.close()

        seen = [item.game_id for item in first.items]
        cursor = first.next_after_game_id
        while cursor is not None:
            page = self.service.search(
                GameSearchQuery(after_game_id=cursor, limit=4)
            )
            ids = [item.game_id for item in page.items]
            self.assertTrue(set(seen).isdisjoint(ids))
            seen.extend(ids)
            if not page.has_more:
                break
            cursor = page.next_after_game_id

        self.assertEqual(seen, list(range(1, 17)))
        self.assertEqual(len(seen), len(set(seen)))

        self._reopen()
        reopened = self.service.search(GameSearchQuery(limit=50))
        self.assertEqual([item.game_id for item in reopened.items], seen)


if __name__ == "__main__":
    unittest.main()
