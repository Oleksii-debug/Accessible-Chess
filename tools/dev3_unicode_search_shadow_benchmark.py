from __future__ import annotations

"""DEV3 evidence benchmark for materialized Unicode-folded ACSDB shadow columns.

This tool intentionally mutates only its disposable in-memory benchmark database.
It compares the current public GameSearchService results/timings with a candidate
schema shape that stores NFKC+casefold shadow values once instead of invoking the
Python ACS_SEARCH_FOLD UDF for every scanned row. It is design evidence, not a
Product migration and not a wall-clock acceptance gate.
"""

from dataclasses import dataclass
from statistics import median
from time import perf_counter

from acs.acsdb import AcsDatabase
from acs.search_service import GameSearchQuery, GameSearchService, _escape_like, _search_fold
from tools.dev3_unicode_search_perf_probe import GAME_COUNT, REPETITIONS, _seed


@dataclass(frozen=True, slots=True)
class _Case:
    label: str
    query: GameSearchQuery


def _folded_pattern(value: str, *, prefix: bool = False) -> str:
    folded = _search_fold(value)
    assert folded is not None
    escaped = _escape_like(folded)
    return f"{escaped}%" if prefix else f"%{escaped}%"


def _materialize_shadow_columns(db: AcsDatabase) -> None:
    with db.conn:
        db.conn.executescript(
            """
            ALTER TABLE games ADD COLUMN white_fold TEXT;
            ALTER TABLE games ADD COLUMN black_fold TEXT;
            ALTER TABLE games ADD COLUMN event_fold TEXT;
            ALTER TABLE games ADD COLUMN eco_fold TEXT;
            ALTER TABLE games ADD COLUMN opening_fold TEXT;
            ALTER TABLE sources ADD COLUMN source_name_fold TEXT;
            """
        )

        game_rows = db.conn.execute(
            "SELECT id, white, black, event, eco, opening FROM games ORDER BY id"
        ).fetchall()
        db.conn.executemany(
            """UPDATE games
               SET white_fold=?, black_fold=?, event_fold=?, eco_fold=?, opening_fold=?
               WHERE id=?""",
            [
                (
                    _search_fold(row["white"]),
                    _search_fold(row["black"]),
                    _search_fold(row["event"]),
                    _search_fold(row["eco"]),
                    _search_fold(row["opening"]),
                    int(row["id"]),
                )
                for row in game_rows
            ],
        )

        source_rows = db.conn.execute(
            "SELECT id, source_name FROM sources ORDER BY id"
        ).fetchall()
        db.conn.executemany(
            "UPDATE sources SET source_name_fold=? WHERE id=?",
            [(_search_fold(row["source_name"]), int(row["id"])) for row in source_rows],
        )

        db.conn.executescript(
            """
            CREATE INDEX idx_probe_games_white_fold ON games(white_fold COLLATE NOCASE);
            CREATE INDEX idx_probe_games_black_fold ON games(black_fold COLLATE NOCASE);
            CREATE INDEX idx_probe_games_event_fold ON games(event_fold COLLATE NOCASE);
            CREATE INDEX idx_probe_games_eco_fold ON games(eco_fold COLLATE NOCASE);
            CREATE INDEX idx_probe_games_opening_fold ON games(opening_fold COLLATE NOCASE);
            CREATE INDEX idx_probe_sources_name_fold ON sources(source_name_fold COLLATE NOCASE);
            ANALYZE;
            """
        )


def _shadow_sql(query: GameSearchQuery) -> tuple[str, list[object]]:
    q = query.normalized()
    clauses: list[str] = []
    params: list[object] = []

    if q.player:
        needle = _folded_pattern(q.player)
        clauses.append(
            "(g.white_fold LIKE ? ESCAPE '\\' OR g.black_fold LIKE ? ESCAPE '\\')"
        )
        params.extend((needle, needle))
    if q.event:
        clauses.append("g.event_fold LIKE ? ESCAPE '\\'")
        params.append(_folded_pattern(q.event))
    if q.eco:
        clauses.append("g.eco_fold LIKE ? ESCAPE '\\'")
        params.append(_folded_pattern(q.eco, prefix=True))
    if q.opening:
        clauses.append("g.opening_fold LIKE ? ESCAPE '\\'")
        params.append(_folded_pattern(q.opening))
    if q.result:
        clauses.append("g.result=?")
        params.append(q.result)
    if q.source_id is not None:
        clauses.append("g.source_id=?")
        params.append(q.source_id)
    if q.source_name:
        clauses.append("s.source_name_fold LIKE ? ESCAPE '\\'")
        params.append(_folded_pattern(q.source_name))
    if q.after_game_id is not None:
        clauses.append("g.id>?")
        params.append(q.after_game_id)

    sql = "SELECT g.id FROM games g JOIN sources s ON s.id=g.source_id"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY g.id LIMIT ?"
    params.append(q.limit + 1)
    return sql, params


def _public_ids(service: GameSearchService, query: GameSearchQuery) -> tuple[int, ...]:
    return tuple(item.game_id for item in service.search(query).items)


def _shadow_ids(db: AcsDatabase, query: GameSearchQuery) -> tuple[int, ...]:
    sql, params = _shadow_sql(query)
    q = query.normalized()
    rows = db.conn.execute(sql, params).fetchall()
    return tuple(int(row[0]) for row in rows[: q.limit])


def _timed(callable_) -> list[float]:
    samples: list[float] = []
    for _ in range(REPETITIONS):
        start = perf_counter()
        callable_()
        samples.append((perf_counter() - start) * 1000.0)
    return samples


def _run_case(db: AcsDatabase, service: GameSearchService, case: _Case) -> None:
    baseline_ids = _public_ids(service, case.query)
    shadow_ids = _shadow_ids(db, case.query)
    if baseline_ids != shadow_ids:
        raise AssertionError(
            f"{case.label}: candidate result ids diverged from public search: "
            f"baseline={baseline_ids[:10]!r} shadow={shadow_ids[:10]!r}"
        )

    sql, params = _shadow_sql(case.query)
    plan = [
        str(row[3])
        for row in db.conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    ]
    uses_temp_sort = any("USE TEMP B-TREE" in detail for detail in plan)

    baseline_ms = _timed(lambda: _public_ids(service, case.query))
    shadow_ms = _timed(lambda: _shadow_ids(db, case.query))
    baseline_median = median(baseline_ms)
    shadow_median = median(shadow_ms)
    ratio = shadow_median / baseline_median if baseline_median else 0.0

    print(f"CASE={case.label}")
    print(f"ROWS={GAME_COUNT}")
    print(f"RESULT_COUNT={len(baseline_ids)}")
    print("SHADOW_PLAN=" + " | ".join(plan))
    print(f"SHADOW_TEMP_SORT={'YES' if uses_temp_sort else 'NO'}")
    print(f"BASELINE_MEDIAN_MS={baseline_median:.3f}")
    print(f"SHADOW_MEDIAN_MS={shadow_median:.3f}")
    print(f"SHADOW_TO_BASELINE_RATIO={ratio:.3f}")


def main() -> None:
    cases = (
        _Case("player_no_hit", GameSearchQuery(player="ZZZZ-NOT-PRESENT", limit=50)),
        _Case("event_no_hit", GameSearchQuery(event="ZZZZ-NOT-PRESENT", limit=50)),
        _Case("eco_prefix_no_hit", GameSearchQuery(eco="Z99", limit=50)),
        _Case("opening_no_hit", GameSearchQuery(opening="ZZZZ-NOT-PRESENT", limit=50)),
        _Case("source_name_no_hit", GameSearchQuery(source_name="ZZZZ-NOT-PRESENT", limit=50)),
        _Case("player_common_hit", GameSearchQuery(player="іваненко", limit=50)),
        _Case("literal_percent_no_hit", GameSearchQuery(player="ZZ%ZZ", limit=50)),
        _Case("literal_underscore_no_hit", GameSearchQuery(event="ZZ_ZZ", limit=50)),
        _Case("literal_backslash_no_hit", GameSearchQuery(opening=r"ZZ\\ZZ", limit=50)),
        _Case(
            "player_keyset_tail_no_hit",
            GameSearchQuery(player="ZZZZ-NOT-PRESENT", after_game_id=90_000, limit=50),
        ),
    )

    with AcsDatabase(":memory:") as db:
        _seed(db)
        service = GameSearchService(db)
        _materialize_shadow_columns(db)
        for case in cases:
            _run_case(db, service, case)


if __name__ == "__main__":
    main()
