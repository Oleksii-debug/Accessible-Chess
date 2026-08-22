from __future__ import annotations

"""Reproducible DEV3 query-plan/performance probe for Unicode ACSDB search.

This is evidence tooling, not a wall-clock product gate. It seeds a realistic large
in-memory ACSDB, exercises the public GameSearchService, captures the exact SELECT
through SQLite tracing, prints EXPLAIN QUERY PLAN, and reports repeated latency.
No threshold is asserted because shared CI runner timing is not a stable contract.
"""

from statistics import median
from time import perf_counter

from acs.acsdb import AcsDatabase
from acs.search_service import GameSearchQuery, GameSearchService

GAME_COUNT = 100_000
REPETITIONS = 5


def _seed(db: AcsDatabase) -> None:
    source_ids = [
        db.add_source(f"archive-{index}.pgn", "pgn", f"{index:064x}"[-64:])
        for index in range(1, 11)
    ]
    names = (
        "Іваненко",
        "ПЕТРЕНКО",
        "Šimko",
        "Straße",
        "Müller",
        "Kováč",
        "Сидоренко",
        "Novák",
        "García",
        "Łukasz",
    )
    events = (
        "Київ Open",
        "Bratislava Open",
        "Straße Cup",
        "Žilina",
        "Львів Masters",
        "Nitra Open",
    )
    openings = (
        "Sicilian Defense",
        "Французький захист",
        "Caro-Kann",
        "Queen's Gambit",
        "Nimzo-Indian",
    )
    rows = []
    for index in range(GAME_COUNT):
        rows.append(
            (
                source_ids[index % len(source_ids)],
                index,
                "full",
                "[]",
                events[index % len(events)],
                names[index % len(names)],
                names[(index * 7) % len(names)],
                ("1-0", "0-1", "1/2-1/2", "*")[index % 4],
                ("B12", "C45", "E60", "A40")[index % 4],
                openings[index % len(openings)],
                "*",
            )
        )
    with db.conn:
        db.conn.executemany(
            """INSERT INTO games(
                   source_id, source_index, import_status, warnings_json,
                   event, white, black, result, eco, opening, pgn_text
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )


def _capture_select(db: AcsDatabase, service: GameSearchService, query: GameSearchQuery) -> str:
    statements: list[str] = []

    def trace(sql: str) -> None:
        if sql.lstrip().upper().startswith("SELECT"):
            statements.append(sql)

    db.conn.set_trace_callback(trace)
    try:
        service.search(query)
    finally:
        db.conn.set_trace_callback(None)
    if not statements:
        raise AssertionError("search probe did not observe a SELECT")
    return statements[-1]


def _run_case(
    db: AcsDatabase,
    service: GameSearchService,
    *,
    label: str,
    query: GameSearchQuery,
    expected_items: int | None = None,
) -> None:
    traced = _capture_select(db, service, query)
    plan = [row[3] for row in db.conn.execute("EXPLAIN QUERY PLAN " + traced).fetchall()]

    samples_ms: list[float] = []
    last_items = None
    for _ in range(REPETITIONS):
        start = perf_counter()
        page = service.search(query)
        samples_ms.append((perf_counter() - start) * 1000.0)
        last_items = len(page.items)

    if expected_items is not None and last_items != expected_items:
        raise AssertionError(
            f"{label}: expected {expected_items} visible items, observed {last_items}"
        )
    if any("USE TEMP B-TREE" in detail for detail in plan):
        raise AssertionError(f"{label}: query unexpectedly materialized a temp sort: {plan!r}")

    print(f"CASE={label}")
    print(f"ROWS={GAME_COUNT}")
    print("PLAN=" + " | ".join(plan))
    print(f"MEDIAN_MS={median(samples_ms):.3f}")
    print(f"MIN_MS={min(samples_ms):.3f}")
    print(f"MAX_MS={max(samples_ms):.3f}")


def main() -> None:
    with AcsDatabase(":memory:") as db:
        _seed(db)
        service = GameSearchService(db)
        _run_case(
            db,
            service,
            label="unicode_player_no_hit",
            query=GameSearchQuery(player="ZZZZ-NOT-PRESENT", limit=50),
            expected_items=0,
        )
        _run_case(
            db,
            service,
            label="unicode_event_no_hit",
            query=GameSearchQuery(event="ZZZZ-NOT-PRESENT", limit=50),
            expected_items=0,
        )
        _run_case(
            db,
            service,
            label="unicode_eco_prefix_no_hit",
            query=GameSearchQuery(eco="Z99", limit=50),
            expected_items=0,
        )
        _run_case(
            db,
            service,
            label="unicode_player_common_hit",
            query=GameSearchQuery(player="іваненко", limit=50),
            expected_items=50,
        )
        _run_case(
            db,
            service,
            label="unicode_player_keyset_tail_no_hit",
            query=GameSearchQuery(
                player="ZZZZ-NOT-PRESENT",
                after_game_id=90_000,
                limit=50,
            ),
            expected_items=0,
        )


if __name__ == "__main__":
    main()
