from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.search_service import GameSearchQuery, GameSearchService


INSERT_GAME = """INSERT INTO games(
    source_id, source_index, import_status, warnings_json,
    event, site, game_date, round, white, black, result,
    eco, opening, start_fen, pgn_text
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


class V2LibrarySearchServiceV4Tests(unittest.TestCase):
    def test_application_service_uses_canonical_v4_search_projection_and_paging(self) -> None:
        with AcsDatabase() as database:
            source_id = database.add_source("КОЛЕКЦІЯ%_\\.pgn", "pgn")
            with database.conn:
                database.conn.executemany(
                    INSERT_GAME,
                    (
                        (source_id, 1, "full", "[]", "Ｃａｆｅ\u0301 Cup", "Kyiv", "2026.08.28", "1", "Straße", "Олексій", "1-0", "C42", "Французький \\ Варіант", None, "*"),
                        (source_id, 2, "full", "[]", "Other", "Kyiv", "2026.08.28", "2", "Literal%Name", "Other", "0-1", "B01", "Other", None, "*"),
                        (source_id, 3, "full", "[]", "Other", "Kyiv", "2026.08.28", "3", "Under_score", "Other", "1/2-1/2", "A00", "Other", None, "*"),
                    ),
                )

            service = GameSearchService(database)
            traced: list[str] = []
            database.conn.set_trace_callback(traced.append)
            try:
                first = service.search(GameSearchQuery(player="STRASSE", limit=1))
                literal = service.search(GameSearchQuery(player="%", limit=1))
                source = service.search(GameSearchQuery(source_name="колекція%_\\", limit=2))
                second_page = service.search(
                    GameSearchQuery(source_name="колекція%_\\", after_game_id=2, limit=2)
                )
            finally:
                database.conn.set_trace_callback(None)

            self.assertEqual([item.game_id for item in first.items], [1])
            self.assertEqual([item.game_id for item in literal.items], [2])
            self.assertEqual([item.game_id for item in source.items], [1, 2])
            self.assertTrue(source.has_more)
            self.assertEqual(source.next_after_game_id, 2)
            self.assertEqual([item.game_id for item in second_page.items], [3])
            self.assertFalse(second_page.has_more)
            self.assertIsNone(second_page.next_after_game_id)

            search_sql = "\n".join(statement for statement in traced if "SELECT g.*" in statement)
            self.assertIn("game_search_fold", search_sql)
            self.assertNotIn("ACS_SEARCH_FOLD(g.white)", search_sql)
            self.assertNotIn("ACS_SEARCH_FOLD(g.event)", search_sql)
            self.assertNotIn("ACS_SEARCH_FOLD(g.opening)", search_sql)

    def test_service_rejects_malformed_persisted_rows_without_coercion(self) -> None:
        canonical = {
            "id": 1,
            "source_id": 2,
            "source_name": "source.pgn",
            "source_format": "pgn",
            "source_index": 0,
            "import_status": "full",
            "white": "White",
            "black": None,
            "event": "Event",
            "site": None,
            "game_date": "2026.10.03",
            "round": None,
            "result": "*",
            "eco": None,
            "opening": None,
            "start_fen": None,
        }

        class FakeDatabase:
            def __init__(self, row):
                self.row = row

            def search_games(self, **_kwargs):
                return [self.row]

        page = GameSearchService(FakeDatabase(canonical)).search()
        self.assertEqual(page.items[0].game_id, 1)
        self.assertEqual(page.items[0].source_name, "source.pgn")

        malformed = (
            {"id": True},
            {"source_id": "2"},
            {"source_index": 0.0},
            {"source_name": None},
            {"source_format": 7},
            {"import_status": False},
            {"white": True},
            {"event": 1.0},
        )
        for override in malformed:
            with self.subTest(override=override):
                with self.assertRaises(TypeError):
                    GameSearchService(FakeDatabase(canonical | override)).search()

        for override in (
            {"id": 0},
            {"source_id": -1},
            {"source_index": -1},
            {"id": 2**63},
        ):
            with self.subTest(override=override):
                with self.assertRaises(ValueError):
                    GameSearchService(FakeDatabase(canonical | override)).search()

        missing = dict(canonical)
        del missing["source_name"]
        with self.assertRaisesRegex(ValueError, "missing source_name"):
            GameSearchService(FakeDatabase(missing)).search()

        class TextSubclass(str):
            pass

        with self.assertRaises(TypeError):
            GameSearchService(
                FakeDatabase(canonical | {"source_name": TextSubclass("source.pgn")})
            ).search()

        hooks: list[str] = []

        class DictSubclass(dict):
            def __contains__(self, key):
                hooks.append(f"contains:{key}")
                raise AssertionError("row containment hook must not run")

            def __getitem__(self, key):
                hooks.append(f"getitem:{key}")
                raise AssertionError("row item hook must not run")

        with self.assertRaisesRegex(TypeError, "search row must be a dictionary"):
            GameSearchService(FakeDatabase(DictSubclass(canonical))).search()
        self.assertEqual(hooks, [])

        class LookaheadDatabase:
            def search_games(self, **_kwargs):
                return [canonical, canonical | {"id": "2"}]

        with self.assertRaises(TypeError):
            GameSearchService(LookaheadDatabase()).search(GameSearchQuery(limit=1))

        class ListSubclass(list):
            def __len__(self):
                raise AssertionError("result length hook must not run")

            def __iter__(self):
                raise AssertionError("result iteration hook must not run")

        class HostileResultDatabase:
            def search_games(self, **_kwargs):
                return ListSubclass([canonical])

        with self.assertRaisesRegex(TypeError, "search result must be a list"):
            GameSearchService(HostileResultDatabase()).search()

    def test_service_and_direct_api_return_identical_ids_for_unicode_literal_filters(self) -> None:
        with AcsDatabase() as database:
            source_id = database.add_source("equivalence.pgn", "pgn")
            with database.conn:
                database.conn.executemany(
                    INSERT_GAME,
                    (
                        (source_id, 1, "full", "[]", "Київ", "Kyiv", "2026.08.28", "1", "Straße", "A", "1-0", "C42", "Французький", None, "*"),
                        (source_id, 2, "full", "[]", "КИЇВ", "Kyiv", "2026.08.28", "2", "Literal%Name", "B", "1-0", "C42", "Французький", None, "*"),
                    ),
                )
            service = GameSearchService(database)
            for query, direct_kwargs in (
                (GameSearchQuery(player="strasse"), {"player": "strasse"}),
                (GameSearchQuery(player="%"), {"player": "%"}),
                (GameSearchQuery(event="київ"), {"event": "київ"}),
                (GameSearchQuery(eco="c42"), {"eco": "c42"}),
                (GameSearchQuery(opening="ФРАНЦУЗЬКИЙ"), {"opening": "ФРАНЦУЗЬКИЙ"}),
            ):
                with self.subTest(query=query):
                    direct_ids = [row["id"] for row in database.search_games(**direct_kwargs)]
                    service_ids = [item.game_id for item in service.search(query).items]
                    self.assertEqual(service_ids, direct_ids)


if __name__ == "__main__":
    unittest.main()
