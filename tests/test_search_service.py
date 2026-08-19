from __future__ import annotations

from dataclasses import replace
import unittest

from acs.acsdb import AcsDatabase
from acs.search_service import (
    GameSearchPage,
    GameSearchQuery,
    GameSearchService,
)


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

    def test_query_scalars_reject_python_coercion(self) -> None:
        invalid = (
            {"limit": True},
            {"limit": "2"},
            {"limit": 2.0},
            {"source_id": True},
            {"source_id": "1"},
            {"after_game_id": False},
            {"after_game_id": "0"},
            {"player": True},
            {"event": ["Kyiv"]},
            {"eco": b"C20"},
            {"source_name": 7},
            {"result": True},
        )
        for values in invalid:
            with self.subTest(query=values):
                with self.assertRaises((TypeError, ValueError)):
                    GameSearchQuery(**values).normalized()

        normalized = GameSearchQuery(
            player="  Alpha\n Player  ",
            event="   ",
            source_name=" tournament   2026 ",
        ).normalized()
        self.assertEqual(normalized.player, "Alpha Player")
        self.assertIsNone(normalized.event)
        self.assertEqual(normalized.source_name, "tournament 2026")

    def test_service_requires_database_and_query_dtos_without_truthiness_fallback(self) -> None:
        with self.assertRaisesRegex(TypeError, "AcsDatabase"):
            GameSearchService(object())
        for query in (False, 0, "", object()):
            with self.subTest(query=query):
                with self.assertRaisesRegex(TypeError, "GameSearchQuery"):
                    self.service.search(query)

        class FalseyQuery(GameSearchQuery):
            def __bool__(self):
                return False

        page = self.service.search(FalseyQuery(player="Alpha"))
        self.assertEqual(len(page.items), 2)

    def test_like_wildcards_and_escape_marker_are_literal_text(self) -> None:
        literal = '''[White "Percent"]
[Black "Under"]
[Result "*"]

1. d4 d5 *
'''
        self.db.import_pgn_text(literal, source_name="100%_literal!.pgn")

        for needle in ("%", "_", "!"):
            with self.subTest(needle=needle):
                page = self.service.search(GameSearchQuery(source_name=needle))
                self.assertEqual(len(page.items), 1)
                self.assertEqual(page.items[0].source_name, "100%_literal!.pgn")

        self.assertEqual(
            len(self.service.search(GameSearchQuery(source_name="100%_literal!")).items),
            1,
        )

    def test_item_and_page_dtos_reject_coerced_or_inconsistent_shapes(self) -> None:
        page = self.service.search(GameSearchQuery(limit=2))
        item = page.items[0]
        for changes in (
            {"game_id": True},
            {"source_id": 0},
            {"source_index": False},
            {"source_name": ""},
            {"source_format": True},
            {"import_status": "unknown"},
            {"white": True},
            {"result": "abandoned"},
        ):
            with self.subTest(item=changes):
                with self.assertRaises((TypeError, ValueError)):
                    replace(item, **changes)

        with self.assertRaisesRegex(TypeError, "tuple"):
            GameSearchPage(list(page.items), page.next_after_game_id, True)
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            GameSearchPage((item, item), None, False)
        with self.assertRaisesRegex(ValueError, "final visible"):
            GameSearchPage((item,), item.game_id + 1, True)
        with self.assertRaisesRegex(ValueError, "final search page"):
            GameSearchPage((item,), item.game_id, False)
        with self.assertRaisesRegex(TypeError, "has_more"):
            GameSearchPage((item,), None, 0)

    def test_invalid_database_scalar_is_not_silently_stringified(self) -> None:
        source_id = self.db.conn.execute("SELECT id FROM sources LIMIT 1").fetchone()[0]
        self.db.conn.execute(
            "UPDATE sources SET source_name=? WHERE id=?",
            (b"binary-name", source_id),
        )
        with self.assertRaisesRegex(TypeError, "source_name"):
            self.service.search()


if __name__ == "__main__":
    unittest.main()
