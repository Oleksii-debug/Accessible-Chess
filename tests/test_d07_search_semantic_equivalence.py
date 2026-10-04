from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.search_service import GameSearchQuery, GameSearchService


class D07SearchSemanticEquivalenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = AcsDatabase()
        self.source_id = self.db.add_source("КОЛЕКЦІЯ%_\\.pgn", "pgn")
        rows = [
            (self.source_id, 1, "full", "[]", "Ｃａｆｅ\u0301 Cup", "Kyiv", "2026.08.23", "1", "Олексій", "Straße", "1-0", "C42", "Французький \\ Варіант", None, "*"),
            (self.source_id, 2, "full", "[]", "Literal% Event", "Kyiv", "2026.08.23", "2", "Literal%Name", "Other", "1-0", "C42", "Literal% Opening", None, "*"),
            (self.source_id, 3, "full", "[]", "LiteralX Event", "Kyiv", "2026.08.23", "3", "LiteralXName", "Other", "1-0", "C42", "LiteralX Opening", None, "*"),
            (self.source_id, 4, "full", "[]", "Under_score", "Kyiv", "2026.08.23", "4", "Under_score", "Other", "1-0", "C42", "Under_score", None, "*"),
            (self.source_id, 5, "full", "[]", "UnderXscore", "Kyiv", "2026.08.23", "5", "UnderXscore", "Other", "1-0", "C42", "UnderXscore", None, "*"),
            (self.source_id, 6, "full", "[]", "Back\\slash", "Kyiv", "2026.08.23", "6", "Back\\slash", "Other", "1-0", "C42", "Back\\slash", None, "*"),
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

    def _direct_ids(self, **kwargs) -> list[int]:
        return [int(row["id"]) for row in self.db.search_games(**kwargs)]

    def _service_ids(self, **kwargs) -> list[int]:
        query = GameSearchQuery(**kwargs)
        return [item.game_id for item in self.service.search(query).items]

    def test_cyrillic_and_multichar_casefold_match_identically(self) -> None:
        self.assertEqual(self._direct_ids(player="олексій"), [1])
        self.assertEqual(self._direct_ids(player="олексій"), self._service_ids(player="олексій"))
        self.assertEqual(self._direct_ids(player="STRASSE"), [1])
        self.assertEqual(self._direct_ids(player="STRASSE"), self._service_ids(player="STRASSE"))

    def test_nfkc_equivalence_is_shared_by_direct_and_service_search(self) -> None:
        direct = self._direct_ids(event="Café Cup")
        service = self._service_ids(event="Café Cup")
        self.assertEqual(direct, [1])
        self.assertEqual(direct, service)

    def test_percent_underscore_and_backslash_are_literal_on_both_surfaces(self) -> None:
        cases = [
            ("%", [2]),
            ("_", [4]),
            ("\\", [6]),
        ]
        for term, expected in cases:
            with self.subTest(term=term):
                direct = self._direct_ids(player=term)
                service = self._service_ids(player=term)
                self.assertEqual(direct, expected)
                self.assertEqual(direct, service)

    def test_source_name_and_opening_share_nfkc_casefold_literal_policy(self) -> None:
        direct_source = self._direct_ids(source_name="колекція%_\\")
        service_source = self._service_ids(source_name="колекція%_\\")
        self.assertEqual(direct_source, list(range(1, 7)))
        self.assertEqual(direct_source, service_source)

        direct_opening = self._direct_ids(opening="французький \\ варіант")
        service_opening = self._service_ids(opening="французький \\ варіант")
        self.assertEqual(direct_opening, [1])
        self.assertEqual(direct_opening, service_opening)

    def test_keyset_pages_have_identical_ids_without_duplicates(self) -> None:
        first_direct = self._direct_ids(limit=2)
        first_service_page = self.service.search(GameSearchQuery(limit=2))
        first_service = [item.game_id for item in first_service_page.items]
        self.assertEqual(first_direct, first_service)
        self.assertEqual(first_direct, [1, 2])

        second_direct = self._direct_ids(after_id=first_direct[-1], limit=2)
        second_service_page = self.service.search(
            GameSearchQuery(after_game_id=first_service_page.next_after_game_id, limit=2)
        )
        second_service = [item.game_id for item in second_service_page.items]
        self.assertEqual(second_direct, second_service)
        self.assertEqual(second_direct, [3, 4])
        self.assertTrue(set(first_direct).isdisjoint(second_direct))

    def test_direct_text_filters_share_service_resource_bounds_and_types(self) -> None:
        with self.assertRaisesRegex(ValueError, "maximum search term length"):
            self.db.search_games(player="x" * 257)
        with self.assertRaisesRegex(TypeError, "player must be text"):
            self.db.search_games(player=123)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
