from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.search_service import GameSearchQuery, GameSearchService


PGN = """[Event \"Kyiv Open\"]
[Site \"Kyiv UKR\"]
[Date \"2026.08.14\"]
[Round \"1\"]
[White \"Alpha\"]
[Black \"Beta\"]
[Result \"1-0\"]
[ECO \"C20\"]
[Opening \"King's Pawn Game\"]

1. e4 e5 2. Nf3 Nc6 1-0

[Event \"Lviv Open\"]
[Site \"Lviv UKR\"]
[Date \"2026.08.14\"]
[Round \"2\"]
[White \"Gamma\"]
[Black \"Alpha\"]
[Result \"1/2-1/2\"]
[ECO \"B12\"]
[Opening \"Caro-Kann Defense\"]

1. e4 c6 2. d4 d5 1/2-1/2

[Event \"Odesa Open\"]
[Site \"Odesa UKR\"]
[Date \"2026.08.14\"]
[Round \"3\"]
[White \"Delta\"]
[Black \"Epsilon\"]
[Result \"0-1\"]
[ECO \"B20\"]
[Opening \"Sicilian Defense\"]

1. e4 c5 2. Nf3 d6 0-1
"""


class SearchServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = AcsDatabase()
        self.db.import_pgn_text(PGN, source_name="tournament-2026.pgn")
        self.service = GameSearchService(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_search_returns_neutral_dtos_with_source_provenance(self) -> None:
        page = self.service.search(GameSearchQuery(player=" alpha "))
        self.assertEqual([item.white for item in page.items], ["Alpha", "Gamma"])
        self.assertEqual([item.black for item in page.items], ["Beta", "Alpha"])
        self.assertTrue(all(item.source_name == "tournament-2026.pgn" for item in page.items))
        self.assertTrue(all(item.source_format == "pgn" for item in page.items))
        self.assertTrue(all(item.source_id > 0 for item in page.items))

    def test_search_combines_filters_without_exposing_sql(self) -> None:
        page = self.service.search(
            GameSearchQuery(event="lviv", eco="B", result="1/2-1/2", source_name="tournament")
        )
        self.assertEqual(len(page.items), 1)
        item = page.items[0]
        self.assertEqual(item.event, "Lviv Open")
        self.assertEqual(item.eco, "B12")
        self.assertEqual(item.opening, "Caro-Kann Defense")

    def test_keyset_paging_is_stable_and_has_no_duplicate_game_ids(self) -> None:
        first = self.service.search(GameSearchQuery(limit=2))
        self.assertEqual(len(first.items), 2)
        self.assertTrue(first.has_more)
        self.assertEqual(first.next_after_game_id, first.items[-1].game_id)

        second = self.service.search(
            GameSearchQuery(limit=2, after_game_id=first.next_after_game_id)
        )
        self.assertEqual(len(second.items), 1)
        self.assertFalse(second.has_more)
        self.assertIsNone(second.next_after_game_id)
        self.assertTrue(
            {item.game_id for item in first.items}.isdisjoint(
                {item.game_id for item in second.items}
            )
        )

    def test_query_validation_rejects_unsafe_or_ambiguous_bounds(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 1 and 200"):
            GameSearchQuery(limit=0).normalized()
        with self.assertRaisesRegex(ValueError, "positive integer"):
            GameSearchQuery(source_id=0).normalized()
        with self.assertRaisesRegex(ValueError, "zero or a positive"):
            GameSearchQuery(after_game_id=-1).normalized()

    def test_search_values_are_parameters_not_sql_fragments(self) -> None:
        page = self.service.search(GameSearchQuery(player="Alpha' OR 1=1 --"))
        self.assertEqual(page.items, ())
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
