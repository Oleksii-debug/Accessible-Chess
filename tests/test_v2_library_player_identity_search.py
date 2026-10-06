from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.search_service import GameSearchQuery, GameSearchService


INSERT_GAME = """INSERT INTO games(
    source_id, source_index, import_status, warnings_json,
    event, site, game_date, round, white, black, result,
    eco, opening, start_fen, pgn_text
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


class V2LibraryPlayerIdentitySearchTests(unittest.TestCase):
    def _seed(self, database: AcsDatabase) -> int:
        source_id = database.add_source("cross-format-names.pgn", "pgn")
        with database.conn:
            database.conn.executemany(
                INSERT_GAME,
                (
                    (
                        source_id,
                        0,
                        "full",
                        "[]",
                        "Cross Format",
                        "Kyiv",
                        "2026.09.07",
                        "1",
                        "José Álvarez",
                        "Opponent A",
                        "1-0",
                        "C42",
                        "French",
                        None,
                        "*",
                    ),
                    (
                        source_id,
                        1,
                        "full",
                        "[]",
                        "Cross Format",
                        "Kyiv",
                        "2026.09.07",
                        "2",
                        "Álvarez, José",
                        "Opponent B",
                        "0-1",
                        "C42",
                        "French",
                        None,
                        "*",
                    ),
                    (
                        source_id,
                        2,
                        "full",
                        "[]",
                        "Cross Format",
                        "Kyiv",
                        "2026.09.07",
                        "3",
                        "José",
                        "Álvarez",
                        "1/2-1/2",
                        "C42",
                        "French",
                        None,
                        "*",
                    ),
                    (
                        source_id,
                        3,
                        "full",
                        "[]",
                        "Literal",
                        "Kyiv",
                        "2026.09.07",
                        "4",
                        "Literal%_;\\Name",
                        "Other",
                        "*",
                        "A00",
                        "Other",
                        None,
                        "*",
                    ),
                    (
                        source_id,
                        4,
                        "full",
                        "[]",
                        "Cross Format",
                        "Kyiv",
                        "2026.09.07",
                        "5",
                        "Anna van der Meer",
                        "Other",
                        "1-0",
                        "C42",
                        "French",
                        None,
                        "*",
                    ),
                    (
                        source_id,
                        5,
                        "full",
                        "[]",
                        "Boundary",
                        "Kyiv",
                        "2026.09.07",
                        "6",
                        "Daniel Collins",
                        "Other",
                        "1-0",
                        "A00",
                        "Other",
                        None,
                        "*",
                    ),
                    (
                        source_id,
                        6,
                        "full",
                        "[]",
                        "Boundary",
                        "Kyiv",
                        "2026.09.07",
                        "7",
                        "An",
                        "Li",
                        "0-1",
                        "A00",
                        "Other",
                        None,
                        "*",
                    ),
                    (
                        source_id,
                        7,
                        "full",
                        "[]",
                        "Punctuation",
                        "Kyiv",
                        "2026.09.07",
                        "8",
                        "María José D’Angelo",
                        "Other",
                        "1-0",
                        "A00",
                        "Other",
                        None,
                        "*",
                    ),
                    (
                        source_id,
                        8,
                        "full",
                        "[]",
                        "Punctuation",
                        "Kyiv",
                        "2026.09.07",
                        "9",
                        "Jean Luc Picard",
                        "Other",
                        "1-0",
                        "A00",
                        "Other",
                        None,
                        "*",
                    ),
                    (
                        source_id,
                        9,
                        "full",
                        "[]",
                        "Unicode",
                        "Kyiv",
                        "2026.09.07",
                        "10",
                        "Іван   Петренко",
                        "Other",
                        "1-0",
                        "A00",
                        "Other",
                        None,
                        "*",
                    ),
                    (
                        source_id,
                        10,
                        "full",
                        "[]",
                        "Unicode",
                        "Kyiv",
                        "2026.09.07",
                        "11",
                        "王 小明",
                        "Other",
                        "1-0",
                        "A00",
                        "Other",
                        None,
                        "*",
                    ),
                ),
            )
        return source_id

    def test_player_components_are_order_independent_across_pgn_and_chessbase_spellings(self) -> None:
        with AcsDatabase() as database:
            source_id = self._seed(database)
            service = GameSearchService(database)

            for player in ("Álvarez, José", "José Álvarez", "álvarez josé"):
                with self.subTest(player=player):
                    direct = database.search_games(
                        player=player,
                        event="Cross Format",
                        source_id=source_id,
                        limit=20,
                    )
                    page = service.search(
                        GameSearchQuery(
                            player=player,
                            event="Cross Format",
                            source_id=source_id,
                            limit=20,
                        )
                    )
                    self.assertEqual([row["source_index"] for row in direct], [0, 1])
                    self.assertEqual([item.source_index for item in page.items], [0, 1])

    def test_all_player_components_must_match_one_side_not_cross_white_and_black(self) -> None:
        with AcsDatabase() as database:
            source_id = self._seed(database)
            rows = database.search_games(
                player="Álvarez, José",
                event="Cross Format",
                source_id=source_id,
                limit=20,
            )
            self.assertEqual([row["source_index"] for row in rows], [0, 1])
            self.assertNotIn(2, [row["source_index"] for row in rows])

            boundary_rows = database.search_games(
                player="An Li",
                event="Boundary",
                source_id=source_id,
                limit=20,
            )
            self.assertEqual(boundary_rows, [])

    def test_multi_component_query_requires_real_components_not_substrings(self) -> None:
        with AcsDatabase() as database:
            source_id = self._seed(database)
            service = GameSearchService(database)

            direct = database.search_games(
                player="An Li",
                event="Boundary",
                source_id=source_id,
                limit=20,
            )
            page = service.search(
                GameSearchQuery(
                    player="An Li",
                    event="Boundary",
                    source_id=source_id,
                    limit=20,
                )
            )
            self.assertEqual(direct, [])
            self.assertEqual([item.source_index for item in page.items], [])

            # Single-token search deliberately retains the established substring policy.
            single = database.search_games(
                player="an",
                event="Boundary",
                source_id=source_id,
                limit=20,
            )
            self.assertEqual([row["source_index"] for row in single], [5, 6])

    def test_multi_component_person_search_handles_particles_and_reversed_order(self) -> None:
        with AcsDatabase() as database:
            source_id = self._seed(database)
            rows = database.search_games(
                player="Meer, Anna van der",
                source_id=source_id,
                limit=20,
            )
            self.assertEqual([row["source_index"] for row in rows], [4])

    def test_apostrophes_hyphens_multiple_spaces_and_non_latin_names_are_canonical(self) -> None:
        with AcsDatabase() as database:
            source_id = self._seed(database)
            service = GameSearchService(database)
            cases = (
                ("D'Angelo, María José", [7]),
                ("María-José DʼAngelo", [7]),
                ("Picard, Jean-Luc", [8]),
                ("петренко,    іван", [9]),
                ("小明, 王", [10]),
            )
            for player, expected in cases:
                with self.subTest(player=player):
                    direct = database.search_games(
                        player=player,
                        source_id=source_id,
                        limit=20,
                    )
                    page = service.search(
                        GameSearchQuery(
                            player=player,
                            source_id=source_id,
                            limit=20,
                        )
                    )
                    self.assertEqual([row["source_index"] for row in direct], expected)
                    self.assertEqual([item.source_index for item in page.items], expected)

    def test_player_search_preserves_diacritic_and_literal_metacharacter_policy(self) -> None:
        with AcsDatabase() as database:
            source_id = self._seed(database)
            self.assertEqual(
                database.search_games(player="Jose Alvarez", source_id=source_id),
                [],
            )
            for literal in ("%", "_", ";", "\\"):
                with self.subTest(literal=literal):
                    rows = database.search_games(player=literal, source_id=source_id)
                    self.assertEqual([row["source_index"] for row in rows], [3])

    def test_order_independent_player_query_keeps_keyset_paging_deterministic(self) -> None:
        with AcsDatabase() as database:
            source_id = self._seed(database)
            service = GameSearchService(database)
            first = service.search(
                GameSearchQuery(
                    player="Álvarez, José",
                    event="Cross Format",
                    source_id=source_id,
                    limit=1,
                )
            )
            self.assertEqual([item.source_index for item in first.items], [0])
            self.assertTrue(first.has_more)
            self.assertIsNotNone(first.next_after_game_id)

            second = service.search(
                GameSearchQuery(
                    player="José Álvarez",
                    event="Cross Format",
                    source_id=source_id,
                    after_game_id=first.next_after_game_id,
                    limit=1,
                )
            )
            self.assertEqual([item.source_index for item in second.items], [1])
            self.assertFalse(second.has_more)
            self.assertIsNone(second.next_after_game_id)


if __name__ == "__main__":
    unittest.main()
