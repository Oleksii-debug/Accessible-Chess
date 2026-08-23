from __future__ import annotations

"""SQLite data core for Accessible Chess Stage 2.

The database layer is presentation-neutral. It stores source provenance,
loss-preserving PGN text, import quality status and exact-position references.
It never modifies source files in place.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Iterable

from .gametree import PgnGame, parse_games, serialize_game
from .search_policy import (
    SEARCH_FOLD_SQL_FUNCTION,
    install_search_fold,
    literal_like_pattern,
    normalize_search_term,
)

IMPORT_STATUSES = {"full", "partial", "damaged", "warning"}
IMPORT_ATTEMPT_STATUSES = {"pending", "full", "warning", "damaged", "failed"}
ACSDB_SCHEMA_VERSION = 3
_SQLITE_INTEGER_MAX = (1 << 63) - 1


@dataclass(slots=True)
class ImportReport:
    source_id: int
    attempt_id: int | None = None
    game_ids: list[int] = field(default_factory=list)
    full: int = 0
    partial: int = 0
    damaged: int = 0
    warning: int = 0

    @property
    def total(self) -> int:
        return self.full + self.partial + self.damaged + self.warning


class AcsDatabase:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        try:
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA busy_timeout = 5000")
            install_search_fold(self.conn)
            self._migrate_schema()
            if self.path != ":memory:":
                self.conn.execute("PRAGMA journal_mode = WAL")
        except Exception:
            self.conn.close()
            raise

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "AcsDatabase":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def _migrate_schema(self) -> None:
        current = self.schema_version
        if current > ACSDB_SCHEMA_VERSION:
            raise RuntimeError(
                f"ACSDB schema {current} is newer than supported schema {ACSDB_SCHEMA_VERSION}"
            )
        while current < ACSDB_SCHEMA_VERSION:
            target = current + 1
            migration = getattr(self, f"_migrate_to_v{target}", None)
            if migration is None:
                raise RuntimeError(f"Missing ACSDB migration from {current} to {target}")
            try:
                migration()
                if not self.conn.in_transaction:
                    raise RuntimeError(
                        f"ACSDB migration to schema {target} did not open a transaction"
                    )
                self.conn.execute(f"PRAGMA user_version = {target}")
                self.conn.commit()
            except Exception:
                if self.conn.in_transaction:
                    self.conn.rollback()
                raise
            current = target

    def _migration_script(self, script: str) -> None:
        """Execute one schema migration inside an explicit SQLite transaction.

        ``sqlite3.Connection`` context managers do not start a transaction for
        DDL, and ``executescript`` commits a pending transaction before running
        its script. Starting ``BEGIN IMMEDIATE`` inside the script keeps every
        schema statement, data backfill and the later ``user_version`` update in
        one fail-closed transaction that the caller can roll back.
        """
        if self.conn.in_transaction:
            raise RuntimeError("ACSDB migration cannot start inside another transaction")
        self.conn.executescript("BEGIN IMMEDIATE;\n" + script)

    def _migrate_to_v1(self) -> None:
        self._migration_script(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY,
                source_name TEXT NOT NULL,
                source_format TEXT NOT NULL,
                sha256 TEXT,
                imported_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY,
                source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                source_index INTEGER NOT NULL,
                import_status TEXT NOT NULL CHECK(import_status IN ('full','partial','damaged','warning')),
                warnings_json TEXT NOT NULL DEFAULT '[]',
                event TEXT,
                site TEXT,
                game_date TEXT,
                round TEXT,
                white TEXT,
                black TEXT,
                result TEXT,
                eco TEXT,
                opening TEXT,
                start_fen TEXT,
                pgn_text TEXT NOT NULL,
                UNIQUE(source_id, source_index)
            );
            CREATE TABLE IF NOT EXISTS positions (
                game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                ply INTEGER NOT NULL,
                fen TEXT NOT NULL,
                position_key TEXT NOT NULL,
                PRIMARY KEY(game_id, ply)
            );
            CREATE INDEX IF NOT EXISTS idx_sources_name ON sources(source_name);
            CREATE INDEX IF NOT EXISTS idx_sources_sha256 ON sources(sha256);
            CREATE INDEX IF NOT EXISTS idx_games_white ON games(white);
            CREATE INDEX IF NOT EXISTS idx_games_black ON games(black);
            CREATE INDEX IF NOT EXISTS idx_games_event ON games(event);
            CREATE INDEX IF NOT EXISTS idx_games_eco ON games(eco);
            CREATE INDEX IF NOT EXISTS idx_games_opening ON games(opening);
            CREATE INDEX IF NOT EXISTS idx_games_result ON games(result);
            CREATE INDEX IF NOT EXISTS idx_games_source ON games(source_id);
            CREATE INDEX IF NOT EXISTS idx_positions_key ON positions(position_key);
            """
        )

    def _migrate_to_v2(self) -> None:
        self._migration_script(
            """
            CREATE TABLE IF NOT EXISTS import_attempts (
                id INTEGER PRIMARY KEY,
                source_name TEXT NOT NULL,
                source_format TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL CHECK(status IN ('pending','full','warning','damaged','failed')),
                source_id INTEGER,
                game_count INTEGER NOT NULL DEFAULT 0,
                warning_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_import_attempts_sha256 ON import_attempts(sha256);
            CREATE INDEX IF NOT EXISTS idx_import_attempts_status ON import_attempts(status);
            CREATE INDEX IF NOT EXISTS idx_import_attempts_source ON import_attempts(source_id);
            """
        )

    def _migrate_to_v3(self) -> None:
        self._migration_script(
            """
            CREATE INDEX IF NOT EXISTS idx_positions_key_game_ply
            ON positions(position_key, game_id, ply);
            """
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _bounded_limit(limit: int) -> int:
        """Return the public query limit without coercing non-integer scalars."""
        if type(limit) is not int:
            raise TypeError("limit must be an integer")
        return max(1, min(limit, 1000))

    @staticmethod
    def _positive_cursor(value: int | None, *, name: str) -> int | None:
        """Validate an optional SQLite integer keyset cursor without coercion."""
        if value is None:
            return None
        if type(value) is not int:
            raise TypeError(f"{name} must be an integer")
        if value < 0:
            raise ValueError(f"{name} must be non-negative")
        if value > _SQLITE_INTEGER_MAX:
            raise ValueError(f"{name} exceeds SQLite integer range")
        return value

    @classmethod
    def _position_cursor(
        cls,
        after_game_id: int | None,
        after_ply: int | None,
    ) -> tuple[int, int] | None:
        """Validate the composite keyset cursor used by exact-position search."""
        if after_game_id is None and after_ply is None:
            return None
        if after_game_id is None or after_ply is None:
            raise ValueError("after_game_id and after_ply must be provided together")
        game_id = cls._positive_cursor(after_game_id, name="after_game_id")
        ply = cls._positive_cursor(after_ply, name="after_ply")
        assert game_id is not None and ply is not None
        return game_id, ply

    @staticmethod
    def _validate_overwrite(overwrite: bool) -> bool:
        if type(overwrite) is not bool:
            raise TypeError("overwrite must be a boolean")
        return overwrite

    @staticmethod
    def _normalized_file_path(value: str | Path, *, name: str) -> Path:
        if not isinstance(value, (str, Path)):
            raise TypeError(f"{name} must be a filesystem path")
        path = Path(value).expanduser()
        if str(path) in {"", ":memory:"}:
            raise ValueError(f"{name} must be a file path")
        return path

    @staticmethod
    def _same_file_target(first: Path, second: Path) -> bool:
        try:
            return first.resolve(strict=False) == second.resolve(strict=False)
        except OSError:
            return os.path.abspath(first) == os.path.abspath(second)

    @staticmethod
    def _schema_columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}

    @classmethod
    def _check_acsdb_schema_identity(cls, conn: sqlite3.Connection, version: int) -> None:
        """Reject healthy SQLite files that are not a supported ACSDB schema."""
        if version < 1:
            raise RuntimeError("backup is not a supported ACSDB database")

        required_tables: dict[str, set[str]] = {
            "sources": {"id", "source_name", "source_format", "sha256", "imported_at"},
            "games": {
                "id", "source_id", "source_index", "import_status", "warnings_json",
                "event", "site", "game_date", "round", "white", "black", "result",
                "eco", "opening", "start_fen", "pgn_text",
            },
            "positions": {"game_id", "ply", "fen", "position_key"},
        }
        if version >= 2:
            required_tables["import_attempts"] = {
                "id", "source_name", "source_format", "sha256", "started_at",
                "finished_at", "status", "source_id", "game_count", "warning_count",
                "error_message",
            }

        for table, required_columns in required_tables.items():
            if not required_columns.issubset(cls._schema_columns(conn, table)):
                raise RuntimeError("ACSDB schema identity check failed")

        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError("ACSDB foreign-key integrity check failed")

        if version >= 3:
            index_columns = [
                str(row[2])
                for row in conn.execute(
                    'PRAGMA index_info("idx_positions_key_game_ply")'
                ).fetchall()
            ]
            if index_columns != ["position_key", "game_id", "ply"]:
                raise RuntimeError("ACSDB schema identity check failed")

    @classmethod
    def _check_sqlite_integrity(cls, conn: sqlite3.Connection) -> int:
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
            if row is None or str(row[0]).lower() != "ok":
                raise RuntimeError("ACSDB integrity check failed")
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        except sqlite3.DatabaseError as exc:
            raise RuntimeError("ACSDB integrity check failed") from exc
        if version > ACSDB_SCHEMA_VERSION:
            raise RuntimeError(
                f"ACSDB schema {version} is newer than supported schema {ACSDB_SCHEMA_VERSION}"
            )
        cls._check_acsdb_schema_identity(conn, version)
        return version

    @staticmethod
    def _temporary_peer(destination: Path) -> Path:
        fd, raw_path = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=str(destination.parent),
        )
        os.close(fd)
        return Path(raw_path)

    def backup_to(self, destination: str | Path, *, overwrite: bool = False) -> Path:
        """Write a consistent SQLite backup and atomically publish it.

        The source database is never rewritten. The backup is first created as a
        peer temporary file, validated with SQLite ``quick_check`` and only then
        moved into place. Existing destinations require explicit ``overwrite``.
        """
        overwrite = self._validate_overwrite(overwrite)
        destination_path = self._normalized_file_path(destination, name="destination")
        if self.path != ":memory:":
            source_path = Path(self.path)
            if self._same_file_target(source_path, destination_path):
                raise ValueError("backup destination must differ from the live database")
        if destination_path.exists() or destination_path.is_symlink():
            if destination_path.is_dir():
                raise IsADirectoryError(destination_path)
            if not overwrite:
                raise FileExistsError(destination_path)

        temporary = self._temporary_peer(destination_path)
        try:
            target = sqlite3.connect(str(temporary))
            try:
                self.conn.backup(target)
                self._check_sqlite_integrity(target)
            finally:
                target.close()
            if overwrite:
                os.replace(temporary, destination_path)
            else:
                os.link(temporary, destination_path)
            return destination_path
        finally:
            if temporary.exists():
                temporary.unlink()

    @classmethod
    def restore_backup(
        cls,
        backup: str | Path,
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        """Validate an ACSDB backup and atomically restore it to a file path."""
        overwrite = cls._validate_overwrite(overwrite)
        backup_path = cls._normalized_file_path(backup, name="backup")
        destination_path = cls._normalized_file_path(destination, name="destination")
        if not backup_path.is_file():
            raise FileNotFoundError(backup_path)
        if cls._same_file_target(backup_path, destination_path):
            raise ValueError("restore destination must differ from the backup source")
        if destination_path.exists() or destination_path.is_symlink():
            if destination_path.is_dir():
                raise IsADirectoryError(destination_path)
            if not overwrite:
                raise FileExistsError(destination_path)

        temporary = cls._temporary_peer(destination_path)
        source: sqlite3.Connection | None = None
        target: sqlite3.Connection | None = None
        try:
            try:
                source = sqlite3.connect(backup_path.resolve().as_uri() + "?mode=ro", uri=True)
                cls._check_sqlite_integrity(source)
                target = sqlite3.connect(str(temporary))
                source.backup(target)
                cls._check_sqlite_integrity(target)
            except sqlite3.DatabaseError as exc:
                raise RuntimeError("ACSDB backup restore failed integrity validation") from exc
            finally:
                if target is not None:
                    target.close()
                if source is not None:
                    source.close()
            if overwrite:
                os.replace(temporary, destination_path)
            else:
                os.link(temporary, destination_path)
            return destination_path
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def position_key(fen: str) -> str:
        parts = (fen or "").strip().split()
        if len(parts) < 4:
            raise ValueError("FEN must contain at least placement, turn, castling and en-passant fields")
        return " ".join(parts[:4])

    def _insert_source(self, source_name: str, source_format: str, sha256: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO sources(source_name, source_format, sha256, imported_at) VALUES(?,?,?,?)",
            (source_name, source_format.lower(), sha256, self._now()),
        )
        return int(cur.lastrowid)

    def add_source(self, source_name: str, source_format: str, sha256: str | None = None) -> int:
        with self.conn:
            return self._insert_source(source_name, source_format, sha256)

    def _create_import_attempt(self, source_name: str, source_format: str, sha256: str) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO import_attempts(source_name, source_format, sha256, started_at, status) VALUES(?,?,?,?,?)",
                (source_name, source_format.lower(), sha256, self._now(), "pending"),
            )
            return int(cur.lastrowid)

    def _finish_import_attempt(self, attempt_id: int, *, status: str, source_id: int | None = None,
                               game_count: int = 0, warning_count: int = 0,
                               error_message: str | None = None) -> None:
        if status not in IMPORT_ATTEMPT_STATUSES - {"pending"}:
            raise ValueError(f"Unsupported import attempt status: {status}")
        self.conn.execute(
            """UPDATE import_attempts
               SET finished_at=?, status=?, source_id=?, game_count=?, warning_count=?, error_message=?
               WHERE id=?""",
            (self._now(), status, source_id, int(game_count), int(warning_count), error_message, int(attempt_id)),
        )

    def _insert_game(self, game: PgnGame, source_id: int, *, raw_pgn: str | None = None,
                     import_status: str | None = None) -> int:
        status = import_status or ("warning" if game.warnings else "full")
        if status not in IMPORT_STATUSES:
            raise ValueError(f"Unsupported import status: {status}")
        tags = game.tags
        pgn_text = raw_pgn if raw_pgn is not None else serialize_game(game)
        cur = self.conn.execute(
            """INSERT INTO games(source_id, source_index, import_status, warnings_json,
               event, site, game_date, round, white, black, result, eco, opening, start_fen, pgn_text)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (source_id, game.source_index, status, json.dumps(game.warnings, ensure_ascii=False),
             tags.get("Event"), tags.get("Site"), tags.get("Date"), tags.get("Round"),
             tags.get("White"), tags.get("Black"), game.result, tags.get("ECO"), tags.get("Opening"),
             tags.get("FEN") if tags.get("SetUp") == "1" else None, pgn_text),
        )
        return int(cur.lastrowid)

    def store_game(self, game: PgnGame, source_id: int, *, raw_pgn: str | None = None,
                   import_status: str | None = None) -> int:
        with self.conn:
            return self._insert_game(game, source_id, raw_pgn=raw_pgn, import_status=import_status)

    def import_pgn_text(self, text: str, source_name: str = "memory.pgn") -> ImportReport:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        attempt_id = self._create_import_attempt(source_name, "pgn", digest)
        try:
            games = parse_games(text)
            if not games:
                with self.conn:
                    source_id = self._insert_source(source_name, "pgn", digest)
                    self._finish_import_attempt(attempt_id, status="damaged", source_id=source_id)
                return ImportReport(source_id=source_id, attempt_id=attempt_id, damaged=1)
            report = ImportReport(source_id=-1, attempt_id=attempt_id)
            with self.conn:
                source_id = self._insert_source(source_name, "pgn", digest)
                report.source_id = source_id
                for game in games:
                    status = "warning" if game.warnings else "full"
                    game_id = self._insert_game(game, source_id, import_status=status)
                    report.game_ids.append(game_id)
                    setattr(report, status, getattr(report, status) + 1)
                self._finish_import_attempt(
                    attempt_id,
                    status="warning" if report.warning else "full",
                    source_id=source_id,
                    game_count=len(report.game_ids),
                    warning_count=report.warning,
                )
            return report
        except Exception as exc:
            with self.conn:
                self._finish_import_attempt(
                    attempt_id,
                    status="failed",
                    error_message=f"{type(exc).__name__}: {exc}",
                )
            raise

    def get_game(self, game_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        return dict(row) if row else None

    def get_source(self, source_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        return dict(row) if row else None

    def get_import_attempt(self, attempt_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM import_attempts WHERE id=?", (int(attempt_id),)).fetchone()
        return dict(row) if row else None

    def list_import_attempts(self, *, status: str | None = None, sha256: str | None = None,
                             before_id: int | None = None, limit: int = 100) -> list[dict]:
        """List import attempts newest-first using a stable keyset cursor.

        ``before_id`` is the last row id from the previous page.  Using the
        primary key as the cursor avoids OFFSET drift if another import starts
        between page requests.
        """
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            if status not in IMPORT_ATTEMPT_STATUSES:
                raise ValueError(f"Unsupported import attempt status: {status}")
            clauses.append("status=?")
            params.append(status)
        if sha256:
            clauses.append("sha256=?")
            params.append(sha256)
        cursor = self._positive_cursor(before_id, name="before_id")
        if cursor is not None:
            clauses.append("id<?")
            params.append(cursor)
        sql = "SELECT * FROM import_attempts"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(self._bounded_limit(limit))
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def search_games(self, *, player: str | None = None, event: str | None = None,
                     eco: str | None = None, opening: str | None = None,
                     result: str | None = None, source_id: int | None = None,
                     source_name: str | None = None, after_id: int | None = None,
                     limit: int = 100) -> list[dict]:
        """Search games with the same Unicode/literal policy as GameSearchService.

        ``after_id`` is intentionally part of the query rather than an OFFSET.
        Once a caller has consumed a page, later inserts cannot cause already
        returned rows to shift into a subsequent page. Search rows include
        source provenance so library surfaces do not need a second lookup.
        """
        player = normalize_search_term(player, name="player")
        event = normalize_search_term(event, name="event")
        eco = normalize_search_term(eco, name="eco")
        opening = normalize_search_term(opening, name="opening")
        source_name = normalize_search_term(source_name, name="source_name")

        clauses: list[str] = []
        params: list[object] = []
        if player:
            clauses.append(
                f"({SEARCH_FOLD_SQL_FUNCTION}(g.white) LIKE ? ESCAPE '\\' OR "
                f"{SEARCH_FOLD_SQL_FUNCTION}(g.black) LIKE ? ESCAPE '\\')"
            )
            needle = literal_like_pattern(player)
            params.extend([needle, needle])
        if event:
            clauses.append(f"{SEARCH_FOLD_SQL_FUNCTION}(g.event) LIKE ? ESCAPE '\\'")
            params.append(literal_like_pattern(event))
        if eco:
            clauses.append(f"{SEARCH_FOLD_SQL_FUNCTION}(g.eco) LIKE ? ESCAPE '\\'")
            params.append(literal_like_pattern(eco, prefix=True))
        if opening:
            clauses.append(f"{SEARCH_FOLD_SQL_FUNCTION}(g.opening) LIKE ? ESCAPE '\\'")
            params.append(literal_like_pattern(opening))
        if result:
            clauses.append("g.result=?")
            params.append(result)
        if source_id is not None:
            clauses.append("g.source_id=?")
            params.append(source_id)
        if source_name:
            clauses.append(f"{SEARCH_FOLD_SQL_FUNCTION}(s.source_name) LIKE ? ESCAPE '\\'")
            params.append(literal_like_pattern(source_name))
        cursor = self._positive_cursor(after_id, name="after_id")
        if cursor is not None:
            clauses.append("g.id>?")
            params.append(cursor)
        sql = (
            "SELECT g.*, s.source_name, s.source_format, s.sha256 AS source_sha256, "
            "s.imported_at AS source_imported_at FROM games g "
            "JOIN sources s ON s.id=g.source_id"
        )
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY g.id LIMIT ?"
        params.append(self._bounded_limit(limit))
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def record_position(self, game_id: int, ply: int, fen: str) -> None:
        key = self.position_key(fen)
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO positions(game_id, ply, fen, position_key) VALUES(?,?,?,?)",
                (game_id, int(ply), fen, key),
            )

    def record_positions(self, game_id: int, positions: Iterable[tuple[int, str]]) -> None:
        rows = [(game_id, int(ply), fen, self.position_key(fen)) for ply, fen in positions]
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO positions(game_id, ply, fen, position_key) VALUES(?,?,?,?)", rows
            )

    def search_position(
        self,
        fen: str,
        limit: int = 100,
        *,
        after_game_id: int | None = None,
        after_ply: int | None = None,
    ) -> list[dict]:
        """Search exact positions with stable composite-key paging and provenance.

        Position identity intentionally ignores only the FEN move counters. The
        cursor is the final ``(game_id, matched_ply)`` from the previous page;
        both cursor components must be supplied together.
        """
        key = self.position_key(fen)
        cursor = self._position_cursor(after_game_id, after_ply)
        clauses = ["p.position_key=?"]
        params: list[object] = [key]
        if cursor is not None:
            game_id, ply = cursor
            clauses.append("(p.game_id>? OR (p.game_id=? AND p.ply>?))")
            params.extend([game_id, game_id, ply])
        sql = (
            "SELECT g.*, p.ply AS matched_ply, p.fen AS matched_fen, "
            "s.source_name, s.source_format, s.sha256 AS source_sha256, "
            "s.imported_at AS source_imported_at "
            "FROM positions p JOIN games g ON g.id=p.game_id "
            "JOIN sources s ON s.id=g.source_id WHERE "
            + " AND ".join(clauses)
            + " ORDER BY p.game_id, p.ply LIMIT ?"
        )
        params.append(self._bounded_limit(limit))
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
