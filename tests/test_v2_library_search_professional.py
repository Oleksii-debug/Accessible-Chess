from __future__ import annotations

import os
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.search_service import GameSearchQuery, GameSearchService


INSERT_GAME = """INSERT INTO games(
    source_id, source_index, import_status, warnings_json,
    event, site, game_date, round, white, black, result,
    eco, opening, start_fen, pgn_text
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def _row(
    source_id: int,
    source_index: int,
    *,
    event: str | None = "Open",
    site: str | None = "Kyiv",
    game_date: str | None = "2024.06.15",
    white: str | None = "White",
    black: str | None = "Black",
    result: str | None = "1-0",
    eco: str | None = "C42",
    opening: str | None = "French Defence",
) -> tuple[object, ...]:
    return (
        source_id,
        source_index,
        "full",
        "[]",
        event,
        site,
        game_date,
        str(source_index),
        white,
        black,
        result,
        eco,
        opening,
        None,
        "*",
    )


class V2LibraryProfessionalSearchTests(unittest.TestCase):
    def test_site_uses_nfkc_casefold_literal_matching_and_keeps_diacritics_significant(self) -> None:
        with AcsDatabase() as database:
            source_id = database.add_source("sites.pgn", "pgn")
            with database.conn:
                database.conn.execute(
                    INSERT_GAME,
                    _row(source_id, 1, site="Košice%_\\ Arena"),
                )
                database.conn.execute(
                    INSERT_GAME,
                    _row(source_id, 2, site="Kosice Arena"),
                )
                database.conn.execute(
                    INSERT_GAME,
                    _row(source_id, 3, site="Ｋｙｉｖ"),
                )

            self.assertEqual(
                [row["id"] for row in database.search_games(site="KOŠICE")],
                [1],
            )
            self.assertEqual(
                [row["id"] for row in database.search_games(site="Kosice")],
                [2],
            )
            self.assertEqual(
                [row["id"] for row in database.search_games(site="%")],
                [1],
            )
            self.assertEqual(
                [row["id"] for row in database.search_games(site="_")],
                [1],
            )
            self.assertEqual(
                [row["id"] for row in database.search_games(site="\\")],
                [1],
            )
            self.assertEqual(
                [row["id"] for row in database.search_games(site="kyiv")],
                [3],
            )

    def test_year_range_matches_only_complete_real_dates_without_repairing_partial_metadata(self) -> None:
        with AcsDatabase() as database:
            source_id = database.add_source("dates.pgn", "pgn")
            dates = (
                "2023.12.31",
                "2024.01.01",
                "2024.06.15",
                "2024.12.31",
                "2025.01.01",
                "2024.??.??",
                "2024.13.01",
                None,
            )
            with database.conn:
                database.conn.executemany(
                    INSERT_GAME,
                    (
                        _row(source_id, index, game_date=value)
                        for index, value in enumerate(dates, start=1)
                    ),
                )

            self.assertEqual(
                [row["id"] for row in database.search_games(year_from=2024, year_to=2024)],
                [2, 3, 4],
            )
            self.assertEqual(
                [
                    row["id"]
                    for row in database.search_games(
                        year_from=2024,
                        year_to=2024,
                        date_from="2024.06.01",
                    )
                ],
                [3, 4],
            )
            self.assertEqual(
                [row["id"] for row in database.search_games(game_date="2024.??.??")],
                [6],
            )

            for value in (True, 2024.0, "2024"):
                with self.subTest(value=value):
                    with self.assertRaises(TypeError):
                        database.search_games(year_from=value)  # type: ignore[arg-type]
            for value in (0, 10_000):
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):
                        database.search_games(year_from=value)
            with self.assertRaises(ValueError):
                database.search_games(year_from=2025, year_to=2024)
            with self.assertRaises(ValueError):
                database.search_games(year_from=2025, date_to="2024.12.31")

    def test_combined_filters_have_one_direct_and_service_truth(self) -> None:
        with AcsDatabase() as database:
            source_a = database.add_source("TWIC%_\\-Kyiv.pgn", "pgn")
            source_b = database.add_source("other.pgn", "pgn")
            with database.conn:
                database.conn.execute(
                    INSERT_GAME,
                    _row(
                        source_a,
                        1,
                        event="Кубок Міста",
                        site="Košice",
                        game_date="2026.08.28",
                        white="Олексій",
                        black="Straße",
                        result="1-0",
                        eco="C42",
                        opening="French Defence",
                    ),
                )
                database.conn.execute(
                    INSERT_GAME,
                    _row(
                        source_b,
                        1,
                        event="Кубок Міста",
                        site="Košice",
                        game_date="2026.08.28",
                        white="Олексій",
                        black="Straße",
                        result="1-0",
                        eco="C42",
                        opening="French Defence",
                    ),
                )

            direct = database.search_games(
                player="ОЛЕКСІЙ",
                event="кубок",
                site="KOŠICE",
                year_from=2026,
                year_to=2026,
                date_from="2026.01.01",
                date_to="2026.12.31",
                result="1-0",
                eco="c42",
                opening="FRENCH",
                source_id=source_a,
                source_name="twic%_\\",
            )
            service = GameSearchService(database).search(
                GameSearchQuery(
                    player="ОЛЕКСІЙ",
                    event="кубок",
                    site="KOŠICE",
                    year_from=2026,
                    year_to=2026,
                    date_from="2026.01.01",
                    date_to="2026.12.31",
                    result="1-0",
                    eco="c42",
                    opening="FRENCH",
                    source_id=source_a,
                    source_name="twic%_\\",
                    limit=20,
                )
            )

            self.assertEqual([row["id"] for row in direct], [1])
            self.assertEqual([item.game_id for item in service.items], [1])
            self.assertEqual(service.items[0].site, "Košice")
            self.assertEqual(service.items[0].source_name, "TWIC%_\\-Kyiv.pgn")

    def test_empty_filters_are_unset_and_missing_metadata_remains_visible_unfiltered(self) -> None:
        with AcsDatabase() as database:
            source_id = database.add_source("missing.pgn", "pgn")
            with database.conn:
                database.conn.execute(
                    INSERT_GAME,
                    _row(
                        source_id,
                        1,
                        event=None,
                        site=None,
                        game_date=None,
                        white=None,
                        black=None,
                        result=None,
                        eco=None,
                        opening=None,
                    ),
                )
                database.conn.execute(INSERT_GAME, _row(source_id, 2, site="Kyiv"))

            page = GameSearchService(database).search(
                GameSearchQuery(player="  ", event="", site=" \t ", source_name="  ", limit=10)
            )
            self.assertEqual([item.game_id for item in page.items], [1, 2])
            self.assertIsNone(page.items[0].site)
            self.assertEqual(
                [item.game_id for item in GameSearchService(database).search(GameSearchQuery(site="kyiv")).items],
                [2],
            )

    def test_keyset_order_and_reopen_are_deterministic_with_site_and_year_filters(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        try:
            with AcsDatabase(path) as database:
                source_id = database.add_source("paging.pgn", "pgn")
                with database.conn:
                    database.conn.executemany(
                        INSERT_GAME,
                        (
                            _row(source_id, index, site="Kyiv", game_date=f"2024.01.{index:02d}")
                            for index in range(1, 7)
                        ),
                    )
                service = GameSearchService(database)
                first = service.search(GameSearchQuery(site="kyiv", year_from=2024, year_to=2024, limit=2))
                second = service.search(
                    GameSearchQuery(
                        site="kyiv",
                        year_from=2024,
                        year_to=2024,
                        after_game_id=first.next_after_game_id,
                        limit=2,
                    )
                )
                third = service.search(
                    GameSearchQuery(
                        site="kyiv",
                        year_from=2024,
                        year_to=2024,
                        after_game_id=second.next_after_game_id,
                        limit=2,
                    )
                )
                ids_before = [
                    *(item.game_id for item in first.items),
                    *(item.game_id for item in second.items),
                    *(item.game_id for item in third.items),
                ]
                self.assertEqual(ids_before, [1, 2, 3, 4, 5, 6])
                self.assertTrue(first.has_more)
                self.assertTrue(second.has_more)
                self.assertFalse(third.has_more)
                self.assertEqual(database.verify_integrity(), database.schema_version)

            with AcsDatabase(path) as reopened:
                page = GameSearchService(reopened).search(
                    GameSearchQuery(site="KYIV", year_from=2024, year_to=2024, limit=20)
                )
                self.assertEqual([item.game_id for item in page.items], [1, 2, 3, 4, 5, 6])
                self.assertEqual(reopened.verify_integrity(), reopened.schema_version)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_year_query_normalization_is_noncoercive_in_service_contract(self) -> None:
        with AcsDatabase() as database:
            service = GameSearchService(database)
            with self.assertRaises(TypeError):
                service.search(GameSearchQuery(year_from="2024"))  # type: ignore[arg-type]
            with self.assertRaises(ValueError):
                service.search(GameSearchQuery(year_from=2025, year_to=2024))


if __name__ == "__main__":
    unittest.main()
