from __future__ import annotations

"""Deterministic ACSDB v4 search benchmark with semantic equivalence checks.

This is engineering evidence, not a million-game readiness claim. It seeds a
synthetic legal metadata corpus directly through the owned ACSDB connection so
schema/trigger/search cost can be measured without conflating PGN parser cost.
"""

import argparse
import json
import statistics
import time

from acs.acsdb import AcsDatabase
from acs.search_policy import SEARCH_FOLD_SQL_FUNCTION, install_search_fold, literal_like_pattern


INSERT_GAME = """INSERT INTO games(
    source_id, source_index, import_status, warnings_json,
    event, site, game_date, round, white, black, result,
    eco, opening, start_fen, pgn_text
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def _row(source_id: int, index: int) -> tuple[object, ...]:
    white = f"Player {index % 5000}"
    event = f"Event {index % 200}"
    opening = f"Opening {index % 300}"
    if index == 17:
        white = "Straße"
    elif index == 23:
        white = "Literal%Name"
    elif index == 29:
        white = "Under_score"
    elif index == 31:
        white = "Back\\slash"
    if index == 37:
        event = "Ｃａｆｅ\u0301 Cup"
    if index == 41:
        opening = "Французький \\ Варіант"
    return (
        source_id,
        index,
        "full",
        "[]",
        event,
        "Kyiv",
        "2026.08.28",
        str(index),
        white,
        f"Opponent {index % 7000}",
        "1-0" if index % 3 == 0 else "1/2-1/2",
        f"C{index % 100:02d}",
        opening,
        None,
        "*",
    )


def _seed(database: AcsDatabase, games: int, batch: int = 5000) -> float:
    source_id = database.add_source("synthetic-legal-metadata.pgn", "pgn")
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


def _measure(database: AcsDatabase, sql: str, params: tuple[object, ...], repeats: int) -> tuple[list[int], float]:
    expected = [int(row[0]) for row in database.conn.execute(sql, params).fetchall()]
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        actual = [int(row[0]) for row in database.conn.execute(sql, params).fetchall()]
        elapsed = (time.perf_counter() - started) * 1000.0
        if actual != expected:
            raise AssertionError("benchmark query became nondeterministic")
        samples.append(elapsed)
    return expected, statistics.median(samples)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=100_000)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.games < 10_000:
        raise SystemExit("--games must be at least 10000 for large-library evidence")
    if args.repeats < 3:
        raise SystemExit("--repeats must be at least 3")

    with AcsDatabase() as database:
        install_search_fold(database.conn)
        seed_ms = _seed(database, args.games)
        if database.verify_integrity() != 4:
            raise AssertionError("unexpected schema version")

        cases = {
            "player_no_hit": ("player-does-not-exist", False, "player"),
            "event_contains": ("Event 137", False, "event"),
            "eco_prefix": ("C42", True, "eco"),
            "opening_contains": ("Opening 211", False, "opening"),
            "literal_percent": ("%", False, "player"),
            "literal_underscore": ("_", False, "player"),
            "literal_backslash": ("\\", False, "player"),
        }
        results: dict[str, object] = {}
        for name, (term, prefix, field) in cases.items():
            pattern = literal_like_pattern(term, prefix=prefix)
            if field == "player":
                old_predicate = (
                    f"({SEARCH_FOLD_SQL_FUNCTION}(g.white) LIKE ? ESCAPE '\\' OR "
                    f"{SEARCH_FOLD_SQL_FUNCTION}(g.black) LIKE ? ESCAPE '\\')"
                )
                new_predicate = "(sf.white_fold LIKE ? ESCAPE '\\' OR sf.black_fold LIKE ? ESCAPE '\\')"
                params = (pattern, pattern, 100)
            else:
                old_predicate = f"{SEARCH_FOLD_SQL_FUNCTION}(g.{field}) LIKE ? ESCAPE '\\'"
                new_predicate = f"sf.{field}_fold LIKE ? ESCAPE '\\'"
                params = (pattern, 100)
            old_sql = f"SELECT g.id FROM games g WHERE {old_predicate} ORDER BY g.id LIMIT ?"
            new_sql = (
                "SELECT g.id FROM games g JOIN game_search_fold sf ON sf.game_id=g.id "
                f"WHERE {new_predicate} ORDER BY g.id LIMIT ?"
            )
            old_ids, old_ms = _measure(database, old_sql, params, args.repeats)
            new_ids, new_ms = _measure(database, new_sql, params, args.repeats)
            if old_ids != new_ids:
                raise AssertionError(f"semantic mismatch for {name}")
            results[name] = {
                "matches": len(new_ids),
                "legacy_udf_median_ms": round(old_ms, 3),
                "v4_sidecar_median_ms": round(new_ms, 3),
                "speedup": round(old_ms / new_ms, 3) if new_ms else None,
            }

        after_id = max(0, args.games - 1000)
        old_tail = "SELECT g.id FROM games g WHERE g.id>? ORDER BY g.id LIMIT 100"
        new_tail = (
            "SELECT g.id FROM games g JOIN game_search_fold sf ON sf.game_id=g.id "
            "WHERE g.id>? ORDER BY g.id LIMIT 100"
        )
        old_ids, old_ms = _measure(database, old_tail, (after_id,), args.repeats)
        new_ids, new_ms = _measure(database, new_tail, (after_id,), args.repeats)
        if old_ids != new_ids:
            raise AssertionError("keyset tail semantic mismatch")
        results["keyset_tail"] = {
            "matches": len(new_ids),
            "legacy_median_ms": round(old_ms, 3),
            "v4_sidecar_median_ms": round(new_ms, 3),
            "ratio": round(new_ms / old_ms, 3) if old_ms else None,
        }

        plan = [
            str(row[3])
            for row in database.conn.execute(
                "EXPLAIN QUERY PLAN SELECT g.id FROM games g "
                "JOIN game_search_fold sf ON sf.game_id=g.id "
                "WHERE sf.event_fold LIKE ? ESCAPE '\\' ORDER BY g.id LIMIT 100",
                (literal_like_pattern("Event 137"),),
            ).fetchall()
        ]
        payload = {
            "schema_version": database.schema_version,
            "games": args.games,
            "seed_ms": round(seed_ms, 3),
            "integrity": "PASS",
            "query_plan": plan,
            "cases": results,
            "claim": "100k measured evidence only; not a million-game readiness claim",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
