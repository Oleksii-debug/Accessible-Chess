from __future__ import annotations

"""DEV3 evidence oracle for durable Unicode-search sidecar semantics.

This probe uses only disposable SQLite files. It does not change Product schema.
It validates the transaction and persistence properties required before a future
ACSDB schema migration may adopt the sidecar design proven by the 100k benchmark.

Important SQLite/Python boundary: a connection context manager does not itself
start a transaction before DDL. A future schema migration that must make DDL plus
backfill atomic therefore needs an explicit BEGIN before CREATE TABLE/backfill.
"""

from pathlib import Path
import tempfile

from acs.acsdb import AcsDatabase
from acs.search_service import _search_fold
from tools.dev3_unicode_search_sidecar_benchmark import _materialize_sidecar


_SIDECAR = "dev3_probe_game_search_fold"
_ROLLBACK = "dev3_probe_rollback_fold"


def _insert_game(
    db: AcsDatabase,
    *,
    source_id: int,
    source_index: int,
    event: str,
    white: str,
    black: str,
    eco: str,
    opening: str,
) -> int:
    cur = db.conn.execute(
        """INSERT INTO games(
               source_id, source_index, import_status, warnings_json,
               event, white, black, result, eco, opening, pgn_text
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            source_id,
            source_index,
            "full",
            "[]",
            event,
            white,
            black,
            "1-0",
            eco,
            opening,
            "*",
        ),
    )
    return int(cur.lastrowid)


def _insert_sidecar(
    db: AcsDatabase,
    *,
    game_id: int,
    event: str,
    white: str,
    black: str,
    eco: str,
    opening: str,
) -> None:
    db.conn.execute(
        f"""INSERT INTO {_SIDECAR}(
               game_id, white_fold, black_fold, event_fold, eco_fold, opening_fold
           ) VALUES(?,?,?,?,?,?)""",
        (
            game_id,
            _search_fold(white),
            _search_fold(black),
            _search_fold(event),
            _search_fold(eco),
            _search_fold(opening),
        ),
    )


def _table_exists(db: AcsDatabase, table: str) -> bool:
    row = db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _seed(db: AcsDatabase) -> tuple[int, tuple[int, ...]]:
    source_id = db.add_source("Košice-ČESKÝ.pgn", "pgn", "1" * 64)
    rows = (
        (1, "Český Pohár — Café", "Žofia Šachová", "Олексій Дьордяй", "Č42", "Straße Attack"),
        (2, "Львів Masters", "Іваненко", "Šimko", "B12", "Французький захист"),
    )
    game_ids: list[int] = []
    with db.conn:
        for source_index, event, white, black, eco, opening in rows:
            game_ids.append(
                _insert_game(
                    db,
                    source_id=source_id,
                    source_index=source_index,
                    event=event,
                    white=white,
                    black=black,
                    eco=eco,
                    opening=opening,
                )
            )
    return source_id, tuple(game_ids)


def _prove_transactional_migration_rollback(db: AcsDatabase) -> None:
    assert not _table_exists(db, _ROLLBACK)
    assert not db.conn.in_transaction

    db.conn.execute("BEGIN IMMEDIATE")
    assert db.conn.in_transaction, "future DDL migration must explicitly begin a transaction"
    try:
        db.conn.execute(
            f"""CREATE TABLE {_ROLLBACK} (
                   game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
                   white_fold TEXT,
                   black_fold TEXT,
                   event_fold TEXT,
                   eco_fold TEXT,
                   opening_fold TEXT
               )"""
        )
        rows = db.conn.execute(
            "SELECT id, white, black, event, eco, opening FROM games ORDER BY id"
        ).fetchall()
        db.conn.executemany(
            f"""INSERT INTO {_ROLLBACK}(
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
        raise RuntimeError("intentional migration rollback probe")
    except RuntimeError as exc:
        db.conn.rollback()
        if str(exc) != "intentional migration rollback probe":
            raise

    assert not db.conn.in_transaction
    assert not _table_exists(db, _ROLLBACK), "explicit DDL/backfill transaction must roll back atomically"


def _prove_materialized_payload_isolation(db: AcsDatabase, game_ids: tuple[int, ...]) -> None:
    _materialize_sidecar(db)
    count = int(db.conn.execute(f"SELECT COUNT(*) FROM {_SIDECAR}").fetchone()[0])
    assert count == len(game_ids)

    first = db.conn.execute(
        f"SELECT * FROM {_SIDECAR} WHERE game_id=?",
        (game_ids[0],),
    ).fetchone()
    assert first is not None
    assert first["white_fold"] == _search_fold("Žofia Šachová")
    assert first["black_fold"] == _search_fold("Олексій Дьордяй")
    assert first["event_fold"] == _search_fold("Český Pohár — Café")
    assert first["eco_fold"] == _search_fold("Č42")
    assert first["opening_fold"] == _search_fold("Straße Attack")

    public_game = db.get_game(game_ids[0])
    assert public_game is not None
    assert not any(key.endswith("_fold") for key in public_game)
    public_rows = db.search_games(player="Žofia", limit=10)
    assert public_rows
    assert not any(key.endswith("_fold") for key in public_rows[0])


def _prove_write_through_atomicity(db: AcsDatabase, source_id: int) -> int:
    with db.conn:
        committed_id = _insert_game(
            db,
            source_id=source_id,
            source_index=100,
            event="Nitra Open",
            white="Müller",
            black="Kováč",
            eco="E60",
            opening="Nimzo-Indian",
        )
        _insert_sidecar(
            db,
            game_id=committed_id,
            event="Nitra Open",
            white="Müller",
            black="Kováč",
            eco="E60",
            opening="Nimzo-Indian",
        )
    assert db.get_game(committed_id) is not None
    assert db.conn.execute(
        f"SELECT 1 FROM {_SIDECAR} WHERE game_id=?",
        (committed_id,),
    ).fetchone() is not None

    rolled_back_id: int | None = None
    try:
        with db.conn:
            rolled_back_id = _insert_game(
                db,
                source_id=source_id,
                source_index=101,
                event="Rollback Event",
                white="Rollback White",
                black="Rollback Black",
                eco="A00",
                opening="Rollback Opening",
            )
            _insert_sidecar(
                db,
                game_id=rolled_back_id,
                event="Rollback Event",
                white="Rollback White",
                black="Rollback Black",
                eco="A00",
                opening="Rollback Opening",
            )
            raise RuntimeError("intentional write-through rollback probe")
    except RuntimeError as exc:
        if str(exc) != "intentional write-through rollback probe":
            raise
    assert rolled_back_id is not None
    assert db.get_game(rolled_back_id) is None
    assert db.conn.execute(
        f"SELECT 1 FROM {_SIDECAR} WHERE game_id=?",
        (rolled_back_id,),
    ).fetchone() is None
    return committed_id


def _prove_reopen_and_fk_cascade(path: Path, committed_id: int) -> None:
    with AcsDatabase(path) as reopened:
        assert reopened.schema_version == 3, "evidence table must not masquerade as a Product migration"
        assert _table_exists(reopened, _SIDECAR)
        row = reopened.conn.execute(
            f"SELECT white_fold FROM {_SIDECAR} WHERE game_id=?",
            (committed_id,),
        ).fetchone()
        assert row is not None and row["white_fold"] == _search_fold("Müller")

        with reopened.conn:
            reopened.conn.execute("DELETE FROM games WHERE id=?", (committed_id,))
        assert reopened.conn.execute(
            f"SELECT 1 FROM {_SIDECAR} WHERE game_id=?",
            (committed_id,),
        ).fetchone() is None


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="dev3-sidecar-durability-") as raw_dir:
        path = Path(raw_dir) / "library.acsdb"
        with AcsDatabase(path) as db:
            source_id, game_ids = _seed(db)
            _prove_transactional_migration_rollback(db)
            _prove_materialized_payload_isolation(db, game_ids)
            committed_id = _prove_write_through_atomicity(db, source_id)

        _prove_reopen_and_fk_cascade(path, committed_id)

    print("DEV3 UNICODE SEARCH SIDECAR DURABILITY PROBE PASS")
    print("MIGRATION_REQUIRES_EXPLICIT_BEGIN=YES")
    print("DDL_BACKFILL_ROLLBACK=ATOMIC")
    print("SIDECAR_REOPEN=PERSISTENT")
    print("SIDECAR_FK_CASCADE=PASS")
    print("PUBLIC_G_STAR_PAYLOAD=UNCHANGED")
    print("WRITE_THROUGH_ROLLBACK=ATOMIC")


if __name__ == "__main__":
    main()
