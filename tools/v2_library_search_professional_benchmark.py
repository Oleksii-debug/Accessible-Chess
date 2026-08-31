from __future__ import annotations

"""Deterministic 100k ACSDB professional-search evidence.

The corpus is synthetic metadata so this benchmark isolates database/search cost.
Real lawful Lichess acceptance is a separate workflow gate. Timing is reported,
not used as a brittle wall-clock release threshold; correctness, query shape and
stable paging are mandatory.
"""

import argparse
import json
import statistics
import time

from acs.acsdb import AcsDatabase
from acs.search_service import GameSearchQuery, GameSearchService


INSERT_GAME = """INSERT INTO games(
    source_id, source_index, import_status, warnings_json,
    event, site, game_date, round, white, black, result,
    eco, opening, start_fen, pgn_text
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def _row(source_id: int, index: int) -> tuple[object, ...]:
    year = 2000 + (index % 27)
    month = 1 + (index % 12)
    day = 1 + (index % 28)
    site = f"Site {index % 500}"
    if index == 17:
        site = "Košice%_\\ Arena"
    elif index == 23:
        site = "Ｋｙｉｖ"
    game_date: str | None = f"{year:04d}.{month:02d}.{day:02d}"
    if index % 1000 == 0:
        game_date = f"{year:04d}.??.??"
    return (
        source_id,
        index,
        "full",
        "[]",
        f"Event {index % 200}",
        site,
        game_date,
        str(index),
        f"Player {index % 5000}",
        f"Opponent {index % 7000}",
        "1-0" if index % 3 == 0 else "1/2-1/2",
        f"C{index % 100:02d}",
        f"Opening {index % 300}",
        None,
        "*",
    )


def _seed(database: AcsDatabase, games: int, batch: int = 5000) -> float:
    source_id = database.add_source("search-professional-100k.pgn", "pgn")
    started = time.perf_counter()
    next_index = 1
    while next_index <= games:
        end = min(games + 1, next_index + batch)
        with database.conn:
            database.conn.executemany(
                INSERT_GAME,
                (_row(source_id, index) for index in range(next_index, end)),
            )
        next_index = end
    return (time.perf_counter() - started) * 1000.0


def _median(call, repeats: int):
    samples: list[float] = []
    expected = None
    for _ in range(repeats):
        started = time.perf_counter()
        current = call()
        samples.append((time.perf_counter() - started) * 1000.0)
        identity = tuple(item["id"] if isinstance(item, dict) else item.game_id for item in current)
        if expected is None:
            expected = identity
        elif identity != expected:
            raise AssertionError("benchmark query became nondeterministic")
    return expected or (), statistics.median(samples)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=100_000)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.games < 10_000:
        raise SystemExit("--games must be at least 10000")
    if args.repeats < 3:
        raise SystemExit("--repeats must be at least 3")

    with AcsDatabase() as database:
        seed_ms = _seed(database, args.games)
        if database.verify_integrity() != database.schema_version:
            raise AssertionError("integrity verification failed")
        if int(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]) != args.games:
            raise AssertionError("seed count mismatch")

        cases = {
            "site_literal_unicode": lambda: database.search_games(site="KOŠICE%_\\", limit=200),
            "year_2013": lambda: database.search_games(year_from=2013, year_to=2013, limit=200),
            "combined": lambda: database.search_games(
                event="Event 17",
                site="Site 17",
                year_from=2005,
                year_to=2020,
                result="1/2-1/2",
                eco="C",
                opening="Opening",
                limit=200,
            ),
            "tail_keyset": lambda: database.search_games(after_id=max(0, args.games - 1000), limit=200),
        }
        results: dict[str, object] = {}
        for name, call in cases.items():
            ids, median_ms = _median(call, args.repeats)
            results[name] = {"matches": len(ids), "median_ms": round(median_ms, 3)}

        service = GameSearchService(database)
        service_ids, service_ms = _median(
            lambda: service.search(
                GameSearchQuery(site="site 17", year_from=2005, year_to=2020, limit=200)
            ).items,
            args.repeats,
        )
        direct_ids = tuple(
            row["id"]
            for row in database.search_games(site="site 17", year_from=2005, year_to=2020, limit=200)
        )
        if service_ids != direct_ids:
            raise AssertionError("GameSearchService diverged from AcsDatabase search truth")
        results["service_equivalence"] = {
            "matches": len(service_ids),
            "median_ms": round(service_ms, 3),
        }

        year_plan = [
            str(row[3])
            for row in database.conn.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM games "
                "WHERE ACS_SEARCH_DATE_KEY(game_date)>=? AND ACS_SEARCH_DATE_KEY(game_date)<=? "
                "ORDER BY id LIMIT 200",
                ("2013.01.01", "2013.12.31"),
            ).fetchall()
        ]
        if not any("idx_games_search_date_key" in line for line in year_plan):
            raise AssertionError(f"year-range query lost date index: {year_plan}")

        literal_ids = [row["id"] for row in database.search_games(site="%_\\")]
        if literal_ids != [17]:
            raise AssertionError(f"literal site metacharacters changed semantics: {literal_ids}")

        payload = {
            "status": "PASS",
            "schema_version": database.schema_version,
            "games": args.games,
            "seed_ms": round(seed_ms, 3),
            "integrity": "PASS",
            "year_query_plan": year_plan,
            "cases": results,
            "claim": "100k measured evidence only; real lawful corpus is a separate gate; no million-game claim",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
