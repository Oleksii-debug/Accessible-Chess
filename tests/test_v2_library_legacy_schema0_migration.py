from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.gametree import parse_games
from acs.legacy_library_migration import (
    LegacyLibraryDataError,
    LegacyLibraryMigrationError,
    LegacyLibrarySchemaError,
    migrate_legacy_library,
)
from acs.search_service import GameSearchQuery, GameSearchService


PGN_UNICODE = '''[Event "Київський турнір"]
[Site "Ужгород"]
[Date "2026.08.28"]
[Round "1"]
[White "Олексій"]
[Black "Šachista"]
[Result "1-0"]

1. e4 {центр} e5 (1... c5 $5 {Сицилійський захист}) 2. Nf3 Nc6 3. Bb5 a6 1-0
'''

PGN_TWO_GAMES = '''[Event "Legacy A"]
[White "Alpha"]
[Black "Beta"]
[Result "1/2-1/2"]

1. d4 d5 2. c4 e6 1/2-1/2

[Event "Legacy B"]
[White "Gamma"]
[Black "Delta"]
[Result "*"]

1. Nf3 Nf6 2. g3 g6 *
'''


def _make_legacy(path: Path, rows: list[tuple[int, object, object, object]]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS games(id INTEGER PRIMARY KEY, title TEXT, pgn TEXT, created_at TEXT)"
        )
        connection.executemany(
            "INSERT INTO games(id,title,pgn,created_at) VALUES(?,?,?,?)",
            rows,
        )
        connection.commit()
    finally:
        connection.close()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class V2LibraryLegacySchema0MigrationTests(unittest.TestCase):
    def test_exact_shipped_schema_migrates_unicode_variations_multigame_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = root / "legacy.db"
            current = root / "library.acsdb"
            _make_legacy(
                legacy,
                [
                    (1, "Українська партія", PGN_UNICODE, "2026-08-20T10:11:12"),
                    (7, "", PGN_TWO_GAMES, "2026-08-21T12:13:14"),
                ],
            )
            before = _digest(legacy)

            result = migrate_legacy_library(legacy, current)

            self.assertEqual(before, _digest(legacy))
            self.assertEqual(result.legacy_rows, 2)
            self.assertEqual(result.sources, 2)
            self.assertEqual(result.games, 3)
            self.assertEqual(result.import_attempts, 2)
            self.assertEqual(result.schema_version, ACSDB_SCHEMA_VERSION)
            self.assertTrue(current.is_file())
            self.assertFalse(any(root.glob(".library.acsdb.legacy-migrate-*.tmp*")))

            with AcsDatabase(current) as database:
                self.assertEqual(database.schema_version, ACSDB_SCHEMA_VERSION)
                self.assertEqual(database.verify_integrity(), ACSDB_SCHEMA_VERSION)
                sources = database.conn.execute(
                    "SELECT id, source_name, source_format, sha256, imported_at FROM sources ORDER BY id"
                ).fetchall()
                self.assertEqual([row["source_name"] for row in sources], ["Українська партія", ""])
                self.assertEqual([row["source_format"] for row in sources], ["pgn", "pgn"])
                self.assertEqual(
                    [row["imported_at"] for row in sources],
                    ["2026-08-20T10:11:12", "2026-08-21T12:13:14"],
                )
                self.assertEqual(sources[0]["sha256"], hashlib.sha256(PGN_UNICODE.encode("utf-8")).hexdigest())
                self.assertEqual(sources[1]["sha256"], hashlib.sha256(PGN_TWO_GAMES.encode("utf-8")).hexdigest())

                attempts = database.conn.execute(
                    "SELECT source_name,status,source_id,game_count FROM import_attempts ORDER BY id"
                ).fetchall()
                self.assertEqual([row["source_name"] for row in attempts], ["Українська партія", ""])
                self.assertEqual([row["game_count"] for row in attempts], [1, 2])
                self.assertTrue(all(row["status"] in {"full", "warning"} for row in attempts))

                search = GameSearchService(database).search(GameSearchQuery(player="ОЛЕКСІЙ", limit=20))
                self.assertEqual(len(search.items), 1)
                stored = database.get_game(search.items[0].game_id)
                self.assertIsNotNone(stored)
                reparsed = parse_games(stored["pgn_text"])
                self.assertEqual(len(reparsed), 1)
                self.assertIn("центр", stored["pgn_text"])
                self.assertIn("c5", stored["pgn_text"])

            with AcsDatabase(current) as reopened:
                self.assertEqual(reopened.verify_integrity(), ACSDB_SCHEMA_VERSION)
                self.assertEqual(
                    reopened.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0],
                    3,
                )

    def test_empty_exact_legacy_library_becomes_empty_current_acsdb(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = root / "legacy.db"
            current = root / "current.acsdb"
            _make_legacy(legacy, [])
            before = _digest(legacy)

            result = migrate_legacy_library(legacy, current)

            self.assertEqual(result.legacy_rows, 0)
            self.assertEqual(result.games, 0)
            self.assertEqual(before, _digest(legacy))
            with AcsDatabase(current) as database:
                self.assertEqual(database.verify_integrity(), ACSDB_SCHEMA_VERSION)
                self.assertEqual(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)

    def test_arbitrary_unversioned_sqlite_never_gets_guessed_as_legacy_library(self) -> None:
        variants = (
            "CREATE TABLE games(id INTEGER PRIMARY KEY, pgn TEXT)",
            "CREATE TABLE games(id INTEGER PRIMARY KEY, title TEXT, pgn TEXT, created_at TEXT); CREATE TABLE notes(id INTEGER)",
            "CREATE TABLE games(id INTEGER PRIMARY KEY, title TEXT, pgn TEXT, created_at TEXT); CREATE INDEX extra_idx ON games(title)",
        )
        for script in variants:
            with self.subTest(script=script), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "not-legacy.db"
                destination = root / "current.acsdb"
                connection = sqlite3.connect(source)
                try:
                    connection.executescript(script)
                    connection.commit()
                finally:
                    connection.close()
                before = _digest(source)

                with self.assertRaises(LegacyLibrarySchemaError):
                    migrate_legacy_library(source, destination)

                self.assertFalse(destination.exists())
                self.assertEqual(before, _digest(source))
                self.assertFalse(any(root.glob(".current.acsdb.legacy-migrate-*.tmp*")))

    def test_nonzero_user_version_fails_closed_even_with_legacy_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "not-schema0.db"
            destination = root / "current.acsdb"
            _make_legacy(source, [(1, "x", PGN_UNICODE, "2026-08-20T10:11:12")])
            connection = sqlite3.connect(source)
            try:
                connection.execute("PRAGMA user_version = 1")
                connection.commit()
            finally:
                connection.close()
            before = _digest(source)

            with self.assertRaises(LegacyLibrarySchemaError):
                migrate_legacy_library(source, destination)

            self.assertFalse(destination.exists())
            self.assertEqual(before, _digest(source))

    def test_nontext_or_empty_unrepresentable_legacy_data_publishes_nothing(self) -> None:
        rows = (
            [(1, "ok", PGN_UNICODE, "2026-08-20T10:11:12"), (2, "bad", b"blob", "2026-08-20T10:11:13")],
            [(1, "ok", PGN_UNICODE, "2026-08-20T10:11:12"), (2, "bad", "", "2026-08-20T10:11:13")],
            [(1, "ok", PGN_UNICODE, "2026-08-20T10:11:12"), (2, None, PGN_UNICODE, "2026-08-20T10:11:13")],
            [(1, "ok", PGN_UNICODE, "2026-08-20T10:11:12"), (2, "bad", PGN_UNICODE, None)],
        )
        for legacy_rows in rows:
            with self.subTest(legacy_rows=legacy_rows), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "legacy.db"
                destination = root / "current.acsdb"
                _make_legacy(source, legacy_rows)
                before = _digest(source)

                with self.assertRaises((LegacyLibraryDataError, LegacyLibraryMigrationError)):
                    migrate_legacy_library(source, destination)

                self.assertFalse(destination.exists())
                self.assertEqual(before, _digest(source))
                self.assertFalse(any(root.glob(".current.acsdb.legacy-migrate-*.tmp*")))

    def test_late_storage_failure_rolls_back_private_target_and_preserves_legacy_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "legacy.db"
            destination = root / "current.acsdb"
            _make_legacy(
                source,
                [
                    (1, "first", PGN_UNICODE, "2026-08-20T10:11:12"),
                    (2, "second", PGN_TWO_GAMES, "2026-08-20T10:11:13"),
                ],
            )
            before = _digest(source)
            original = AcsDatabase._insert_game
            calls = 0

            def fail_second(database: AcsDatabase, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise sqlite3.OperationalError("injected storage failure")
                return original(database, *args, **kwargs)

            with mock.patch.object(AcsDatabase, "_insert_game", fail_second):
                with self.assertRaises(LegacyLibraryMigrationError):
                    migrate_legacy_library(source, destination)

            self.assertFalse(destination.exists())
            self.assertEqual(before, _digest(source))
            self.assertFalse(any(root.glob(".current.acsdb.legacy-migrate-*.tmp*")))

    def test_existing_destination_same_path_and_symlink_source_are_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "legacy.db"
            destination = root / "current.acsdb"
            _make_legacy(source, [(1, "one", PGN_UNICODE, "2026-08-20T10:11:12")])
            destination.write_bytes(b"do-not-overwrite")
            before_source = _digest(source)
            before_destination = destination.read_bytes()

            with self.assertRaises(FileExistsError):
                migrate_legacy_library(source, destination)
            with self.assertRaises(ValueError):
                migrate_legacy_library(source, source)

            self.assertEqual(before_source, _digest(source))
            self.assertEqual(before_destination, destination.read_bytes())

            link = root / "legacy-link.db"
            try:
                link.symlink_to(source)
            except OSError:
                return
            fresh_destination = root / "from-link.acsdb"
            with self.assertRaises(LegacyLibraryMigrationError):
                migrate_legacy_library(link, fresh_destination)
            self.assertFalse(fresh_destination.exists())


if __name__ == "__main__":
    unittest.main()
