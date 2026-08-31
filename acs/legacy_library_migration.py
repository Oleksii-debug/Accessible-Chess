from __future__ import annotations

"""Preservation-first conversion of the shipped legacy Library into ACSDB.

Stage 1 shipped an unversioned SQLite ``Library`` with exactly one table::

    games(id INTEGER PRIMARY KEY, title TEXT, pgn TEXT, created_at TEXT)

This module recognizes only that closed-world schema.  It never guesses that an
arbitrary ``PRAGMA user_version=0`` database belongs to Accessible Chess.  The
legacy file is opened read-only and remains untouched; conversion is built in a
peer temporary current ACSDB and is published only after canonical PGN parsing,
current-schema integrity validation and successful close.

Upgrade orchestration, backup/rollback journals and replacement of the user's
canonical data path belong to V2-DATA-RELEASE.  This module owns only the D07
domain conversion boundary.
"""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile

from .acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from .gametree import parse_games


class LegacyLibraryMigrationError(RuntimeError):
    """Base failure for preservation-first legacy Library conversion."""


class LegacyLibrarySchemaError(LegacyLibraryMigrationError):
    """Raised when an unversioned SQLite file is not the exact shipped schema."""


class LegacyLibraryDataError(LegacyLibraryMigrationError):
    """Raised when legacy rows cannot be represented canonically without loss."""


@dataclass(frozen=True, slots=True)
class LegacyLibraryMigrationResult:
    legacy_rows: int
    sources: int
    games: int
    warning_games: int
    import_attempts: int
    schema_version: int

    def __post_init__(self) -> None:
        for name, value in (
            ("legacy_rows", self.legacy_rows),
            ("sources", self.sources),
            ("games", self.games),
            ("warning_games", self.warning_games),
            ("import_attempts", self.import_attempts),
            ("schema_version", self.schema_version),
        ):
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.sources != self.legacy_rows:
            raise ValueError("each legacy row must retain one source provenance record")
        if self.import_attempts != self.legacy_rows:
            raise ValueError("each legacy row must retain one migration attempt record")
        if self.warning_games > self.games:
            raise ValueError("warning_games cannot exceed games")
        if self.schema_version != ACSDB_SCHEMA_VERSION:
            raise ValueError("migration result must identify the current ACSDB schema")


_EXPECTED_LEGACY_COLUMNS = (
    (0, "id", "INTEGER", 0, None, 1),
    (1, "title", "TEXT", 0, None, 0),
    (2, "pgn", "TEXT", 0, None, 0),
    (3, "created_at", "TEXT", 0, None, 0),
)


def _path(value: str | Path, *, name: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise TypeError(f"{name} must be a filesystem path")
    path = Path(value).expanduser()
    if str(path) in {"", ":memory:"}:
        raise ValueError(f"{name} must be a file path")
    return path


def _same_target(first: Path, second: Path) -> bool:
    try:
        return first.resolve(strict=False) == second.resolve(strict=False)
    except OSError:
        return os.path.abspath(first) == os.path.abspath(second)


def _temporary_peer(destination: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.legacy-migrate-",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return path


def _cleanup_sqlite_family(path: Path) -> None:
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # Cleanup after a failed, unpublished conversion is best effort here;
            # V2-DATA-RELEASE owns directory-level recovery/journal policy.
            pass


def _check_legacy_schema(connection: sqlite3.Connection) -> None:
    quick = connection.execute("PRAGMA quick_check").fetchone()
    if quick is None or str(quick[0]).lower() != "ok":
        raise LegacyLibrarySchemaError("legacy Library failed SQLite integrity validation")

    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version != 0:
        raise LegacyLibrarySchemaError("source is not the unversioned legacy Library schema")

    objects = [
        (str(row[0]), str(row[1]))
        for row in connection.execute(
            """SELECT type, name FROM sqlite_master
               WHERE name NOT LIKE 'sqlite_%'
               ORDER BY type, name"""
        ).fetchall()
    ]
    if objects != [("table", "games")]:
        raise LegacyLibrarySchemaError("unversioned SQLite schema is not the shipped legacy Library")

    columns = tuple(
        (int(row[0]), str(row[1]), str(row[2]).upper(), int(row[3]), row[4], int(row[5]))
        for row in connection.execute('PRAGMA table_info("games")').fetchall()
    )
    if columns != _EXPECTED_LEGACY_COLUMNS:
        raise LegacyLibrarySchemaError("legacy Library games table identity does not match the shipped schema")


def _legacy_row(row: sqlite3.Row) -> tuple[int, str, str, str]:
    legacy_id = row["id"]
    title = row["title"]
    pgn = row["pgn"]
    created_at = row["created_at"]

    if type(legacy_id) is not int or legacy_id < 1:
        raise LegacyLibraryDataError("legacy Library contains an invalid row identity")
    if type(title) is not str:
        raise LegacyLibraryDataError("legacy Library contains a non-text title")
    if type(pgn) is not str:
        raise LegacyLibraryDataError("legacy Library contains non-text PGN data")
    if type(created_at) is not str or not created_at.strip():
        raise LegacyLibraryDataError("legacy Library contains invalid creation provenance")
    return legacy_id, title, pgn, created_at


def migrate_legacy_library(
    source: str | Path,
    destination: str | Path,
) -> LegacyLibraryMigrationResult:
    """Convert one exact shipped legacy Library into a new current ACSDB file.

    The destination must not already exist.  No caller-visible destination is
    published until the full conversion passes canonical parsing and current
    ACSDB integrity checks.  The source database is held in a read transaction
    through the conversion and opened ``mode=ro`` so this operation cannot repair,
    rewrite or partially consume legacy user data.
    """

    source_path = _path(source, name="source")
    destination_path = _path(destination, name="destination")
    if _same_target(source_path, destination_path):
        raise ValueError("legacy source and ACSDB destination must differ")
    if source_path.is_symlink() or not source_path.is_file():
        raise LegacyLibraryMigrationError("legacy Library source is unavailable or indirect")
    if destination_path.exists() or destination_path.is_symlink():
        raise FileExistsError("ACSDB migration destination already exists")
    if not destination_path.parent.is_dir():
        raise LegacyLibraryMigrationError("ACSDB migration destination directory is unavailable")

    temporary = _temporary_peer(destination_path)
    legacy: sqlite3.Connection | None = None
    target: AcsDatabase | None = None
    published = False
    try:
        try:
            legacy = sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)
            legacy.row_factory = sqlite3.Row
            legacy.execute("BEGIN")
            _check_legacy_schema(legacy)

            target = AcsDatabase(temporary)
            # The migration target is private and unpublished. DELETE journaling
            # avoids carrying a WAL sidecar across the final one-file publication.
            target.conn.execute("PRAGMA journal_mode = DELETE")

            migrated_rows = 0
            migrated_games = 0
            warning_games = 0
            attempt_rows: list[tuple[str, str, int, int, int]] = []

            target.conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = legacy.execute(
                    "SELECT id, title, pgn, created_at FROM games ORDER BY id"
                )
                for raw_row in cursor:
                    _legacy_id, title, pgn, created_at = _legacy_row(raw_row)
                    games = parse_games(pgn)
                    if not games:
                        raise LegacyLibraryDataError(
                            "legacy Library row contains no canonically representable game"
                        )

                    digest = hashlib.sha256(pgn.encode("utf-8")).hexdigest()
                    source_id = target._insert_source(title, "pgn", digest)
                    target.conn.execute(
                        "UPDATE sources SET imported_at=? WHERE id=?",
                        (created_at, source_id),
                    )

                    row_warning_count = 0
                    for game in games:
                        target._insert_game(game, source_id)
                        migrated_games += 1
                        if game.warnings:
                            warning_games += 1
                            row_warning_count += len(game.warnings)

                    migrated_rows += 1
                    attempt_rows.append(
                        (title, digest, source_id, len(games), row_warning_count)
                    )
                target.conn.commit()
            except Exception:
                if target.conn.in_transaction:
                    target.conn.rollback()
                raise

            # The legacy store had no attempt table. Create one explicit migration
            # attempt per original row after canonical publication into the private
            # target so import history does not fabricate a pre-existing runtime
            # attempt while still recording the migration provenance.
            for title, digest, source_id, game_count, row_warning_count in attempt_rows:
                attempt_id = target._create_import_attempt(title, "pgn", digest)
                with target.conn:
                    target._finish_import_attempt(
                        attempt_id,
                        status="warning" if row_warning_count else "full",
                        source_id=source_id,
                        game_count=game_count,
                        warning_count=row_warning_count,
                    )

            integrity = target.verify_integrity()
            if not integrity.get("ok"):
                raise LegacyLibraryMigrationError("converted ACSDB failed canonical integrity validation")
            if target.schema_version != ACSDB_SCHEMA_VERSION:
                raise LegacyLibraryMigrationError("converted ACSDB did not reach the current schema")

            source_count = int(target.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
            game_count = int(target.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
            attempt_count = int(
                target.conn.execute("SELECT COUNT(*) FROM import_attempts").fetchone()[0]
            )
            if source_count != migrated_rows or game_count != migrated_games:
                raise LegacyLibraryMigrationError("converted ACSDB row counts are inconsistent")
            if attempt_count != migrated_rows:
                raise LegacyLibraryMigrationError("converted ACSDB provenance counts are inconsistent")

            result = LegacyLibraryMigrationResult(
                legacy_rows=migrated_rows,
                sources=source_count,
                games=game_count,
                warning_games=warning_games,
                import_attempts=attempt_count,
                schema_version=target.schema_version,
            )
            legacy.commit()
            legacy.close()
            legacy = None
            target.close()
            target = None

            if Path(str(temporary) + "-wal").exists() or Path(str(temporary) + "-shm").exists():
                raise LegacyLibraryMigrationError("converted ACSDB retained unpublished SQLite sidecars")

            # Same-directory hard-link publication is atomic and no-clobber.  It
            # refuses a destination created by a racing writer instead of replacing
            # it.  The peer temporary is then only redundant cleanup evidence.
            os.link(temporary, destination_path)
            published = True
            try:
                temporary.unlink()
            except OSError:
                # Do not report a false migration failure after valid data has been
                # atomically published. V2-DATA-RELEASE can clean stale peer files
                # during its directory-level recovery pass.
                pass
            return result
        except (LegacyLibraryMigrationError, FileExistsError, ValueError, TypeError):
            raise
        except (sqlite3.Error, OSError, UnicodeError) as exc:
            raise LegacyLibraryMigrationError("legacy Library conversion failed") from exc
    finally:
        if target is not None:
            try:
                target.close()
            except Exception:
                pass
        if legacy is not None:
            try:
                if legacy.in_transaction:
                    legacy.rollback()
                legacy.close()
            except Exception:
                pass
        if not published:
            _cleanup_sqlite_family(temporary)
