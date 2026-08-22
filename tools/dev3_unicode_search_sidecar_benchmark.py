from __future__ import annotations

"""DEV3 design evidence for a normalized Unicode-search sidecar table.

The benchmark mutates only its disposable in-memory ACSDB.  It compares the
current public GameSearchService result ids/timings with a candidate v4 schema
shape that stores folded game metadata in a separate one-to-one table keyed by
canonical game_id.  This avoids exposing cache columns through existing g.*
projections while still removing per-row Python Unicode folding from searches.
It is evidence only: no Product schema or search behavior is changed here.
"""

from dataclasses import dataclass
from statistics import median
from time import perf_counter

from acs.acsdb import AcsDatabase
from acs.search_service import (
    GameSearchQuery,
    GameSearchService,
    _escape_like,
    _search_fold,
)
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


def _materialize_sidecar(db: AcsDatabase) -> None:
    with db.conn:
        db.conn.execute(
            """
            CREATE TABLE dev3_probe_game_search_fold (
                game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
                white_fold TEXT,
                black_fold TEXT,
                event_fold TEXT,
                eco_fold TEXT,
                opening_fold TEXT
            )
            """
        )

        last_id = 0
        while True:
            rows = db.conn.execute(
                """SELECT id, white, black, event, eco, opening
                   FROM games WHERE id>? ORDER BY id LIMIT 1000""",
                (last_id,),
            ).fetchall()
            if not rows:
                break
            db.conn.executemany(
                """INSERT INTO dev3_probe_game_search_fold(
                       game_id, white_fold, black_fold, event_fold, eco_fold, opening_fold
                   ) VALUES(?,?,?,?,?,?)""",
                [
                    (
                        int(row["id"]),
                        _search_fold(row["white"]),
                        _search_fold(row["black"]),
                        _search_fold(row["event"]),
                        _search_fold(row["eco"]),
                        _search_fold(row["opening"]),
                    )
                    for row in rows
                ],
            )
            last_id = int(rows[-1]["id"])


def _sidecar_sql(query: GameSearchQuery) -> tuple[str, list[object]]:
    q = query.normalized()
    clauses: list[str] = []
    params: list[object] = []

    if q.player:
        needle = _folded_pattern(q.player)
        clauses.append("(f.white_fold LIKE ? ESCAPE '\\' OR f.black_fold LIKE ? ESCAPE '\\')")
        params.extend((needle, needle))
    if q.event:
        clauses.append("f.event_fold LIKE ? ESCAPE '\\'")
        params.append(_folded_pattern(q.event))
    if q.eco:
        clauses.append("f.eco_fold LIKE ? ESCAPE '\\'")
        params.append(_folded_pattern(q.eco, prefix=True))
    if q.opening:
        clauses.append("f.opening_fold LIKE ? ESCAPE '\\'")
        params.append(_folded_pattern(q.opening))
    if q.result:
        clauses.append("g.result=?")
        params.append(q.result)
    if q.source_id is not None:
        clauses.append("g.source_id=?")
        params.append(q.source_id)
    if q.source_name:
        # Source-name folding is intentionally left on the existing public path;
        # the prior 100k benchmark showed no material gain from shadowing it.
        clauses.append("ACS_SEARCH_FOLD(s.source_name) LIKE ? ESCAPE '\\'")
        params.append(_folded_pattern(q.source_name))
    if q.after_game_id is not None:
        clauses.append("g.id>?")
        params.append(q.after_game_id)

    sql = (
        "SELECT g.id FROM games g "
        "JOIN dev3_probe_game_search_fold f ON f.game_id=g.id "
        "JOIN sources s ON s.id=g.source_id"
    )
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY g.id LIMIT ?"
    params.append(q.limit + 1)
    return sql, params


def _public_ids(service: GameSearchService, query: GameSearchQuery) -> tuple[int, ...]:
    return tuple(item.game_id for item in service.search(query).items)


def _sidecar_ids(db: AcsDatabase, query: GameSearchQuery) -> tuple[int, ...]:
    sql, params = _sidecar_sql(query)
    q = query.normalized()
    rows = db.conn.execute(sql, params).fetchall()
    return tuple(int(row[0]) for row in rows[: q.limit])


def _timed(callable_) -> list[float]:
    samples: list[float] = []
    for _ in range(REPETITIONS):
        started = perf_counter()
        callable_()
        samples.append((perf_counter() - started) * 1000.0)
    return samples


def _run_case(db: AcsDatabase, service: GameSearchService, case: _Case) -> None:
    baseline_ids = _public_ids(service, case.query)
    candidate_ids = _sidecar_ids(db, case.query)
    if baseline_ids != candidate_ids:
        raise AssertionError(
            f"{case.label}: candidate ids diverged: "
            f"baseline={baseline_ids[:10]!r} candidate={candidate_ids[:10]!r}"
        )

    sql, params = _sidecar_sql(case.query)
    plan = [
        str(row[3])
        for row in db.conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    ]
    temp_sort = any("USE TEMP B-TREE" in detail for detail in plan)
    if temp_sort:
        raise AssertionError(f"{case.label}: sidecar unexpectedly requires temp ORDER BY sort")

    baseline_ms = _timed(lambda: _public_ids(service, case.query))
    candidate_ms = _timed(lambda: _sidecar_ids(db, case.query))
    baseline_median = median(baseline_ms)
    candidate_median = median(candidate_ms)
    ratio = candidate_median / baseline_median if baseline_median else 0.0

    print(f"CASE={case.label}")
    print(f"ROWS={GAME_COUNT}")
    print(f"RESULT_COUNT={len(baseline_ids)}")
    print("SIDECAR_PLAN=" + " | ".join(plan))
    print("SIDECAR_TEMP_SORT=NO")
    print(f"BASELINE_MEDIAN_MS={baseline_median:.3f}")
    print(f"SIDECAR_MEDIAN_MS={candidate_median:.3f}")
    print(f"SIDECAR_TO_BASELINE_RATIO={ratio:.3f}")


def main() -> None:
    cases = (
        _Case("player_no_hit", GameSearchQuery(player="ZZZZ-NOT-PRESENT", limit=50)),
        _Case("event_no_hit", GameSearchQuery(event="ZZZZ-NOT-PRESENT", limit=50)),
        _Case("eco_prefix_no_hit", GameSearchQuery(eco="Z99", limit=50)),
        _Case("opening_no_hit", GameSearchQuery(opening="ZZZZ-NOT-PRESENT", limit=50)),
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
        _materialize_sidecar(db)
        for case in cases:
            _run_case(db, service, case)


if __name__ == "__main__":
    main()
