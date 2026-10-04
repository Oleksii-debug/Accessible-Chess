from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
import statistics
import time

from acs.acsdb import AcsDatabase


INSERT_GAME = """INSERT INTO games(
    source_id, source_index, import_status, warnings_json,
    event, site, game_date, round, white, black, result,
    eco, opening, start_fen, pgn_text
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def _build_rows(source_id: int, games: int) -> list[tuple[object, ...]]:
    start = date(2000, 1, 1)
    rows: list[tuple[object, ...]] = []
    for index in range(1, games + 1):
        if index % 20 == 0:
            game_date = "????.??.??"
        elif index % 20 == 1:
            game_date = "2024.??.??"
        elif index % 20 == 2:
            game_date = "2024.02.30"
        else:
            current = start + timedelta(days=index % 9000)
            game_date = f"{current.year:04d}.{current.month:02d}.{current.day:02d}"
        rows.append(
            (
                source_id,
                index,
                "full",
                "[]",
                "Benchmark",
                "Kyiv",
                game_date,
                str(index),
                f"White {index}",
                f"Black {index}",
                "*",
                "A00",
                "Benchmark",
                None,
                "*",
            )
        )
    return rows


def _median_ms(callable_, repeats: int) -> float:
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        callable_()
        samples.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(samples)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=100_000)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.games < 1 or args.repeats < 1:
        raise SystemExit("games and repeats must be positive")

    with AcsDatabase() as database:
        source_id = database.add_source("date-benchmark.pgn", "pgn")
        with database.conn:
            database.conn.executemany(INSERT_GAME, _build_rows(source_id, args.games))

        lower = "2024.01.01"
        upper = "2024.12.31"
        indexed_sql = (
            "SELECT COUNT(*) FROM games INDEXED BY idx_games_search_date_key "
            "WHERE ACS_SEARCH_DATE_KEY(game_date)>=? AND ACS_SEARCH_DATE_KEY(game_date)<=?"
        )
        scan_sql = (
            "SELECT COUNT(*) FROM games NOT INDEXED "
            "WHERE ACS_SEARCH_DATE_KEY(game_date)>=? AND ACS_SEARCH_DATE_KEY(game_date)<=?"
        )
        params = (lower, upper)
        indexed_count = int(database.conn.execute(indexed_sql, params).fetchone()[0])
        scan_count = int(database.conn.execute(scan_sql, params).fetchone()[0])
        if indexed_count != scan_count:
            raise RuntimeError("indexed and scan date-range counts diverged")

        actual_rows = database.search_games(date_from=lower, date_to=upper, limit=1000)
        if not actual_rows:
            raise RuntimeError("canonical date-range search returned no rows")

        indexed_ms = _median_ms(
            lambda: database.conn.execute(indexed_sql, params).fetchone(),
            args.repeats,
        )
        scan_ms = _median_ms(
            lambda: database.conn.execute(scan_sql, params).fetchone(),
            args.repeats,
        )
        canonical_ms = _median_ms(
            lambda: database.search_games(date_from=lower, date_to=upper, limit=1000),
            args.repeats,
        )

        plan = [
            str(row[3])
            for row in database.conn.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM games "
                "WHERE ACS_SEARCH_DATE_KEY(game_date)>=? "
                "AND ACS_SEARCH_DATE_KEY(game_date)<=?",
                params,
            ).fetchall()
        ]
        if not any("idx_games_search_date_key" in detail for detail in plan):
            raise RuntimeError("date expression index is absent from query plan")

        payload = {
            "games": args.games,
            "repeats": args.repeats,
            "range": [lower, upper],
            "matching_complete_dates": indexed_count,
            "canonical_page_rows": len(actual_rows),
            "indexed_count_median_ms": round(indexed_ms, 3),
            "forced_scan_count_median_ms": round(scan_ms, 3),
            "canonical_search_median_ms": round(canonical_ms, 3),
            "forced_scan_over_indexed_ratio": round(scan_ms / indexed_ms, 3) if indexed_ms else None,
            "query_plan": plan,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
