from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase


_SOURCE_ID = 17
_GAME_ID = 101
_POSITION_PLY = 1
_SOURCE_SHA = "a" * 64
_SOURCE_TIME = "2026-08-31T00:00:00+00:00"
_PGN = '[Event "Migration Matrix"]\n[White "Alpha"]\n[Black "Beta"]\n[Result "*"]\n\n1. e4 *\n'
_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"


def _raw_version(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        connection.close()


def _raw_object_names(path: Path, object_type: str) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type=? ORDER BY name",
                (object_type,),
            ).fetchall()
            if not str(row[0]).startswith("sqlite_")
        }
    finally:
        connection.close()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_truth(database: AcsDatabase) -> None:
    with database.conn:
        database.conn.execute(
            "INSERT INTO sources(id,source_name,source_format,sha256,imported_at) VALUES(?,?,?,?,?)",
            (_SOURCE_ID, "legacy-source.pgn", "pgn", _SOURCE_SHA, _SOURCE_TIME),
        )
        database.conn.execute(
            """INSERT INTO games(
                id,source_id,source_index,import_status,warnings_json,
                event,site,game_date,round,white,black,result,eco,opening,start_fen,pgn_text
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                _GAME_ID,
                _SOURCE_ID,
                7,
                "full",
                "[]",
                "Migration Matrix",
                "Kyiv",
                "2026.08.31",
                "7",
                "Alpha",
                "Beta",
                "*",
                "A00",
                "Migration Test",
                None,
                _PGN,
            ),
        )
        database.conn.execute(
            "INSERT INTO positions(game_id,ply,fen,position_key) VALUES(?,?,?,?)",
            (_GAME_ID, _POSITION_PLY, _FEN, AcsDatabase.position_key(_FEN)),
        )


def _create_fixture(path: Path, version: int, *, seed: bool = True) -> None:
    if version == 0:
        sqlite3.connect(path).close()
        return
    if not 1 <= version <= ACSDB_SCHEMA_VERSION:
        raise ValueError(version)
    with patch("acs.acsdb.ACSDB_SCHEMA_VERSION", version):
        with AcsDatabase(path) as database:
            if seed:
                _seed_truth(database)
            if database.schema_version != version:
                raise AssertionError((database.schema_version, version))


def _truth_snapshot(path: Path) -> tuple[tuple[object, ...], tuple[object, ...], tuple[object, ...]]:
    connection = sqlite3.connect(path)
    try:
        source = tuple(
            connection.execute(
                "SELECT id,source_name,source_format,sha256,imported_at FROM sources WHERE id=?",
                (_SOURCE_ID,),
            ).fetchone()
        )
        game = tuple(
            connection.execute(
                "SELECT id,source_id,source_index,event,white,black,result,pgn_text FROM games WHERE id=?",
                (_GAME_ID,),
            ).fetchone()
        )
        position = tuple(
            connection.execute(
                "SELECT game_id,ply,fen,position_key FROM positions WHERE game_id=? AND ply=?",
                (_GAME_ID, _POSITION_PLY),
            ).fetchone()
        )
        return source, game, position
    finally:
        connection.close()


def _failing_database(target: int) -> type[AcsDatabase]:
    method_name = f"_migrate_to_v{target}"
    parent = getattr(AcsDatabase, method_name)

    def _fail(self: AcsDatabase) -> None:
        parent(self)
        marker = f"migration_partial_v{target}"
        self.conn.execute(f"CREATE TABLE {marker}(value TEXT NOT NULL)")
        self.conn.execute(f"INSERT INTO {marker}(value) VALUES('must-rollback')")
        raise RuntimeError(f"synthetic v{target} migration interruption")

    return type(f"_FailAfterV{target}", (AcsDatabase,), {method_name: _fail})


class V2AcsdbMigrationMatrixV6Tests(unittest.TestCase):
    def test_forward_matrix_v1_through_v5_preserves_ids_provenance_and_reopens(self) -> None:
        for version in range(1, ACSDB_SCHEMA_VERSION):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / f"v{version}.acsdb"
                _create_fixture(path, version)
                before = _truth_snapshot(path)

                with AcsDatabase(path) as migrated:
                    self.assertEqual(migrated.schema_version, ACSDB_SCHEMA_VERSION)
                    self.assertEqual(migrated.verify_integrity(), ACSDB_SCHEMA_VERSION)
                    self.assertEqual(migrated.get_source(_SOURCE_ID)["sha256"], _SOURCE_SHA)
                    self.assertEqual(migrated.get_game(_GAME_ID)["source_index"], 7)
                self.assertEqual(_truth_snapshot(path), before)

                with AcsDatabase(path) as reopened:
                    self.assertEqual(reopened.schema_version, ACSDB_SCHEMA_VERSION)
                    self.assertEqual(reopened.verify_integrity(), ACSDB_SCHEMA_VERSION)
                self.assertEqual(_truth_snapshot(path), before)

    def test_interrupted_migration_matrix_rolls_back_each_step_then_recovers(self) -> None:
        for target in range(1, ACSDB_SCHEMA_VERSION + 1):
            previous = target - 1
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / f"interrupt-v{target}.acsdb"
                _create_fixture(path, previous, seed=previous > 0)
                before = _truth_snapshot(path) if previous > 0 else None
                failing_type = _failing_database(target)

                with self.assertRaisesRegex(RuntimeError, f"synthetic v{target} migration interruption"):
                    failing_type(path)

                self.assertEqual(_raw_version(path), previous)
                self.assertNotIn(f"migration_partial_v{target}", _raw_object_names(path, "table"))
                if before is not None:
                    self.assertEqual(_truth_snapshot(path), before)

                with AcsDatabase(path) as recovered:
                    self.assertEqual(recovered.schema_version, ACSDB_SCHEMA_VERSION)
                    self.assertEqual(recovered.verify_integrity(), ACSDB_SCHEMA_VERSION)

    def test_nonempty_schema0_is_rejected_without_reinterpreting_foreign_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "foreign-schema0.sqlite"
            connection = sqlite3.connect(path)
            try:
                connection.execute("CREATE TABLE notes(id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
                connection.execute("INSERT INTO notes(body) VALUES('foreign user bytes')")
                connection.commit()
            finally:
                connection.close()
            before_hash = _file_sha256(path)

            with self.assertRaisesRegex(RuntimeError, "schema 0|non-empty|existing"):
                AcsDatabase(path)

            self.assertEqual(_raw_version(path), 0)
            self.assertEqual(_file_sha256(path), before_hash)
            self.assertEqual(_raw_object_names(path, "table"), {"notes"})
            raw = sqlite3.connect(path)
            try:
                self.assertEqual(raw.execute("SELECT body FROM notes").fetchone()[0], "foreign user bytes")
            finally:
                raw.close()

    def test_corrupt_v1_missing_canonical_table_fails_before_advancing_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "corrupt-v1.acsdb"
            _create_fixture(path, 1, seed=False)
            raw = sqlite3.connect(path)
            try:
                raw.execute("DROP TABLE games")
                raw.commit()
            finally:
                raw.close()

            with self.assertRaisesRegex(RuntimeError, "schema identity"):
                AcsDatabase(path)

            self.assertEqual(_raw_version(path), 1)
            self.assertNotIn("import_attempts", _raw_object_names(path, "table"))

    def test_v4_v5_missing_or_malformed_derivative_projection_rebuilds_from_games(self) -> None:
        for version in (4, 5):
            for mode in ("missing", "malformed"):
                with self.subTest(version=version, mode=mode), tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / f"v{version}-{mode}.acsdb"
                    _create_fixture(path, version)
                    before = _truth_snapshot(path)
                    raw = sqlite3.connect(path)
                    try:
                        raw.execute("DROP TABLE game_search_fold")
                        if mode == "malformed":
                            raw.execute(
                                "CREATE TABLE game_search_fold(game_id INTEGER PRIMARY KEY, broken TEXT)"
                            )
                        raw.commit()
                    finally:
                        raw.close()

                    with AcsDatabase(path) as migrated:
                        self.assertEqual(migrated.schema_version, ACSDB_SCHEMA_VERSION)
                        self.assertEqual(migrated.verify_integrity(), ACSDB_SCHEMA_VERSION)
                        self.assertEqual(
                            [row["id"] for row in migrated.search_games(player="alpha")],
                            [_GAME_ID],
                        )
                    self.assertEqual(_truth_snapshot(path), before)

    def test_current_v6_missing_canonical_table_or_required_index_fails_on_open(self) -> None:
        for corruption in ("positions-table", "position-index"):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / f"current-{corruption}.acsdb"
                _create_fixture(path, ACSDB_SCHEMA_VERSION)
                raw = sqlite3.connect(path)
                try:
                    if corruption == "positions-table":
                        raw.execute("DROP TABLE positions")
                    else:
                        raw.execute("DROP INDEX idx_positions_key_game_ply")
                    raw.commit()
                finally:
                    raw.close()
                version_before = _raw_version(path)

                with self.assertRaisesRegex(RuntimeError, "schema identity"):
                    AcsDatabase(path)

                self.assertEqual(_raw_version(path), version_before)

    def test_newer_unsupported_version_fails_closed_without_file_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "future.acsdb"
            _create_fixture(path, ACSDB_SCHEMA_VERSION)
            raw = sqlite3.connect(path)
            try:
                raw.execute(f"PRAGMA user_version = {ACSDB_SCHEMA_VERSION + 1}")
                raw.commit()
            finally:
                raw.close()
            before_hash = _file_sha256(path)

            with self.assertRaisesRegex(RuntimeError, "newer than supported"):
                AcsDatabase(path)

            self.assertEqual(_raw_version(path), ACSDB_SCHEMA_VERSION + 1)
            self.assertEqual(_file_sha256(path), before_hash)

    def test_duplicate_current_migration_attempt_is_noop_for_canonical_truth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.acsdb"
            _create_fixture(path, ACSDB_SCHEMA_VERSION)
            before = _truth_snapshot(path)

            for _ in range(3):
                with AcsDatabase(path) as database:
                    self.assertEqual(database.schema_version, ACSDB_SCHEMA_VERSION)
                    self.assertEqual(database.verify_integrity(), ACSDB_SCHEMA_VERSION)
                self.assertEqual(_truth_snapshot(path), before)

    def test_migrated_database_backup_restore_and_reopen_preserve_truth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source-v1.acsdb"
            backup = root / "backup.acsdb"
            restored = root / "restored.acsdb"
            _create_fixture(source, 1)
            before = _truth_snapshot(source)

            with AcsDatabase(source) as migrated:
                self.assertEqual(migrated.schema_version, ACSDB_SCHEMA_VERSION)
                migrated.backup_to(backup)
            self.assertEqual(_truth_snapshot(source), before)

            AcsDatabase.restore_backup(backup, restored)
            with AcsDatabase(restored) as reopened:
                self.assertEqual(reopened.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual(reopened.verify_integrity(), ACSDB_SCHEMA_VERSION)
            self.assertEqual(_truth_snapshot(restored), before)


if __name__ == "__main__":
    unittest.main()
