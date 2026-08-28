from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.search_policy import search_date_key
from acs.search_service import GameSearchQuery, GameSearchService


INSERT_GAME = """INSERT INTO games(
    source_id, source_index, import_status, warnings_json,
    event, site, game_date, round, white, black, result,
    eco, opening, start_fen, pgn_text
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def _row(source_id: int, source_index: int, game_date: str) -> tuple[object, ...]:
    return (
        source_id,
        source_index,
        "full",
        "[]",
        "Date Filter",
        "Kyiv",
        game_date,
        str(source_index),
        f"White {source_index}",
        f"Black {source_index}",
        "*",
        "A00",
        "Date Test",
        None,
        "*",
    )


def _drop_v5(database: AcsDatabase) -> None:
    database.conn.execute("DROP INDEX IF EXISTS idx_games_search_date_key")
    database.conn.execute("DROP INDEX IF EXISTS idx_games_game_date")
    database.conn.execute("PRAGMA user_version = 4")
    database.conn.commit()


class _FailAfterV5(AcsDatabase):
    def _migrate_to_v5(self) -> None:
        super()._migrate_to_v5()
        self.conn.execute("CREATE TABLE v5_partial_marker(value TEXT NOT NULL)")
        self.conn.execute("INSERT INTO v5_partial_marker(value) VALUES('must-rollback')")
        raise RuntimeError("synthetic v5 migration failure")


class V2LibraryDateFilterV5Tests(unittest.TestCase):
    def test_complete_date_key_is_calendar_strict_and_partial_dates_have_no_key(self) -> None:
        self.assertEqual(search_date_key("2026.08.28"), "2026.08.28")
        self.assertEqual(search_date_key("２０２６．０８．２８"), "2026.08.28")
        self.assertIsNone(search_date_key("2026.??.??"))
        self.assertIsNone(search_date_key("????.??.??"))
        self.assertIsNone(search_date_key("2026.02.30"))
        self.assertIsNone(search_date_key("2026.8.28"))
        self.assertIsNone(search_date_key(" 2026.08.28 "))

    def test_v4_to_v5_migration_is_atomic_preserves_rows_and_installs_date_indexes(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        try:
            with AcsDatabase(path) as current:
                source_id = current.add_source("legacy-v4.pgn", "pgn")
                with current.conn:
                    current.conn.execute(INSERT_GAME, _row(source_id, 1, "2024.??.??"))
                    current.conn.execute(INSERT_GAME, _row(source_id, 2, "2024.06.15"))
                _drop_v5(current)

            raw = sqlite3.connect(path)
            try:
                self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], 4)
                before = raw.execute(
                    "SELECT id, game_date, pgn_text FROM games ORDER BY id"
                ).fetchall()
            finally:
                raw.close()

            with AcsDatabase(path) as migrated:
                self.assertEqual(migrated.schema_version, 5)
                self.assertEqual(ACSDB_SCHEMA_VERSION, 5)
                after = migrated.conn.execute(
                    "SELECT id, game_date, pgn_text FROM games ORDER BY id"
                ).fetchall()
                self.assertEqual([tuple(row) for row in after], before)
                index_names = {
                    str(row[1])
                    for row in migrated.conn.execute("PRAGMA index_list(games)").fetchall()
                }
                self.assertIn("idx_games_game_date", index_names)
                self.assertIn("idx_games_search_date_key", index_names)
                self.assertEqual(migrated.verify_integrity(), 5)

            with AcsDatabase(path) as reopened:
                self.assertEqual(
                    [row["id"] for row in reopened.search_games(
                        date_from="2024.01.01", date_to="2024.12.31"
                    )],
                    [2],
                )
                self.assertEqual(
                    [row["id"] for row in reopened.search_games(game_date="2024.??.??")],
                    [1],
                )
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_failed_v5_migration_rolls_back_indexes_marker_and_user_version(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        try:
            with AcsDatabase(path) as current:
                source_id = current.add_source("rollback-v4.pgn", "pgn")
                with current.conn:
                    current.conn.execute(INSERT_GAME, _row(source_id, 1, "2025.01.01"))
                _drop_v5(current)

            with self.assertRaisesRegex(RuntimeError, "synthetic v5 migration failure"):
                _FailAfterV5(path)

            raw = sqlite3.connect(path)
            try:
                self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], 4)
                names = {
                    str(row[0])
                    for row in raw.execute(
                        "SELECT name FROM sqlite_master WHERE type IN ('table','index')"
                    ).fetchall()
                }
                self.assertNotIn("idx_games_game_date", names)
                self.assertNotIn("idx_games_search_date_key", names)
                self.assertNotIn("v5_partial_marker", names)
                self.assertEqual(raw.execute("SELECT game_date FROM games").fetchone()[0], "2025.01.01")
            finally:
                raw.close()

            with AcsDatabase(path) as recovered:
                self.assertEqual(recovered.schema_version, 5)
                self.assertEqual(
                    [row["id"] for row in recovered.search_games(
                        date_from="2025.01.01", date_to="2025.01.01"
                    )],
                    [1],
                )
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_exact_partial_and_invalid_raw_dates_remain_searchable_but_range_excludes_them(self) -> None:
        with AcsDatabase() as database:
            source_id = database.add_source("dates.pgn", "pgn")
            dates = (
                "2024.01.01",
                "2024.??.??",
                "2024.02.30",
                "2024.06.15",
                "????.??.??",
                "2025.01.01",
            )
            with database.conn:
                database.conn.executemany(
                    INSERT_GAME,
                    [_row(source_id, index, value) for index, value in enumerate(dates, 1)],
                )

            self.assertEqual(
                [row["id"] for row in database.search_games(game_date="2024.??.??")],
                [2],
            )
            self.assertEqual(
                [row["id"] for row in database.search_games(game_date="2024.02.30")],
                [3],
            )
            self.assertEqual(
                [row["id"] for row in database.search_games(game_date="????.??.??")],
                [5],
            )
            self.assertEqual(
                [row["id"] for row in database.search_games(
                    date_from="2024.01.01", date_to="2024.12.31"
                )],
                [1, 4],
            )
            self.assertEqual(
                [row["id"] for row in database.search_games(date_from="2024.06.15")],
                [4, 6],
            )
            self.assertEqual(
                [row["id"] for row in database.search_games(date_to="2024.06.15")],
                [1, 4],
            )

    def test_date_bounds_reject_partial_invalid_nontext_and_reversed_ranges(self) -> None:
        with AcsDatabase() as database:
            service = GameSearchService(database)
            for kwargs in (
                {"date_from": "2024.??.??"},
                {"date_to": "2024.02.30"},
                {"date_from": "2024-01-01"},
                {"date_from": 20240101},
            ):
                with self.subTest(kwargs=kwargs):
                    with self.assertRaises((TypeError, ValueError)):
                        database.search_games(**kwargs)
                    with self.assertRaises((TypeError, ValueError)):
                        service.search(GameSearchQuery(**kwargs))

            with self.assertRaisesRegex(ValueError, "date_from must not be later"):
                database.search_games(date_from="2025.01.01", date_to="2024.12.31")
            with self.assertRaisesRegex(ValueError, "date_from must not be later"):
                service.search(GameSearchQuery(date_from="2025.01.01", date_to="2024.12.31"))

    def test_service_and_direct_date_filters_are_equivalent_and_keyset_stable(self) -> None:
        with AcsDatabase() as database:
            source_id = database.add_source("service-dates.pgn", "pgn")
            with database.conn:
                database.conn.executemany(
                    INSERT_GAME,
                    (
                        _row(source_id, 1, "2024.01.01"),
                        _row(source_id, 2, "2024.??.??"),
                        _row(source_id, 3, "2024.06.15"),
                        _row(source_id, 4, "2025.01.01"),
                    ),
                )
            service = GameSearchService(database)

            for query, direct_kwargs in (
                (GameSearchQuery(game_date="2024.??.??"), {"game_date": "2024.??.??"}),
                (
                    GameSearchQuery(date_from="2024.01.01", date_to="2024.12.31"),
                    {"date_from": "2024.01.01", "date_to": "2024.12.31"},
                ),
                (GameSearchQuery(date_from="２０２４．０６．１５"), {"date_from": "２０２４．０６．１５"}),
            ):
                with self.subTest(query=query):
                    direct_ids = [row["id"] for row in database.search_games(**direct_kwargs)]
                    service_ids = [item.game_id for item in service.search(query).items]
                    self.assertEqual(service_ids, direct_ids)

            first = service.search(
                GameSearchQuery(date_from="2024.01.01", date_to="2024.12.31", limit=1)
            )
            self.assertEqual([item.game_id for item in first.items], [1])
            self.assertTrue(first.has_more)
            self.assertEqual(first.next_after_game_id, 1)

            second = service.search(
                GameSearchQuery(
                    date_from="2024.01.01",
                    date_to="2024.12.31",
                    after_game_id=first.next_after_game_id,
                    limit=1,
                )
            )
            self.assertEqual([item.game_id for item in second.items], [3])
            self.assertFalse(second.has_more)
            self.assertIsNone(second.next_after_game_id)

    def test_import_path_preserves_source_date_text_and_range_does_not_invent_unknown_parts(self) -> None:
        pgn = '''[Event "Known"]
[Date "2024.03.04"]
[White "A"]
[Black "B"]
[Result "*"]

1. e4 *

[Event "Partial"]
[Date "2024.??.??"]
[White "C"]
[Black "D"]
[Result "*"]

1. d4 *

[Event "Invalid"]
[Date "2024.02.30"]
[White "E"]
[Black "F"]
[Result "*"]

1. c4 *
'''
        with AcsDatabase() as database:
            report = database.import_pgn_text(pgn, "date-source.pgn")
            self.assertEqual(report.total, 3)
            self.assertEqual(
                [row["game_date"] for row in database.conn.execute(
                    "SELECT game_date FROM games ORDER BY id"
                ).fetchall()],
                ["2024.03.04", "2024.??.??", "2024.02.30"],
            )
            self.assertEqual(
                [row["event"] for row in database.search_games(
                    date_from="2024.01.01", date_to="2024.12.31"
                )],
                ["Known"],
            )
            self.assertEqual(
                [row["event"] for row in database.search_games(game_date="2024.??.??")],
                ["Partial"],
            )
            self.assertEqual(database.verify_integrity(), 5)

    def test_raw_and_expression_date_indexes_are_usable_by_sqlite_query_planner(self) -> None:
        with AcsDatabase() as database:
            source_id = database.add_source("plan.pgn", "pgn")
            with database.conn:
                database.conn.executemany(
                    INSERT_GAME,
                    [_row(source_id, index, f"2024.01.{index:02d}") for index in range(1, 29)],
                )

            exact_plan = " ".join(
                str(row[3])
                for row in database.conn.execute(
                    "EXPLAIN QUERY PLAN SELECT id FROM games WHERE game_date=?",
                    ("2024.01.15",),
                ).fetchall()
            )
            range_plan = " ".join(
                str(row[3])
                for row in database.conn.execute(
                    "EXPLAIN QUERY PLAN SELECT id FROM games "
                    "WHERE ACS_SEARCH_DATE_KEY(game_date)>=? "
                    "AND ACS_SEARCH_DATE_KEY(game_date)<=?",
                    ("2024.01.10", "2024.01.20"),
                ).fetchall()
            )
            self.assertIn("idx_games_game_date", exact_plan)
            self.assertIn("idx_games_search_date_key", range_plan)


if __name__ == "__main__":
    unittest.main()
