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
from pathlib import Path
import sqlite3
from typing import Iterable

from .gametree import PgnGame, parse_games, serialize_game

IMPORT_STATUSES = {"full", "partial", "damaged", "warning"}
IMPORT_ATTEMPT_STATUSES = {"pending", "full", "warning", "damaged", "failed"}
ACSDB_SCHEMA_VERSION = 2


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
            self._migrate_schema()
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
            with self.conn:
                migration()
                self.conn.execute(f"PRAGMA user_version = {target}")
            current = target

    def _migrate_to_v1(self) -> None:
        self.conn.executescript(
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
        self.conn.executescript(
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

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _bounded_limit(limit: int) -> int:
        """Return the public query limit without accepting booleans or nonsense values."""
        if isinstance(limit, bool):
            raise TypeError("limit must be an integer")
        value = int(limit)
        return max(1, min(value, 1000))

    @staticmethod
    def _positive_cursor(value: int | None, *, name: str) -> int | None:
        """Validate an optional SQLite integer keyset cursor."""
        if value is None:
            return None
        if isinstance(value, bool):
            raise TypeError(f"{name} must be an integer")
        cursor = int(value)
        if cursor < 0:
            raise ValueError(f"{name} must be non-negative")
        return cursor

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
        """Search games in deterministic id order with optional keyset paging.

        ``after_id`` is intentionally part of the query rather than an OFFSET.
        Once a caller has consumed a page, later inserts cannot cause already
        returned rows to shift into a subsequent page. Search rows include
        source provenance so library surfaces do not need a second lookup.
        """
        clauses: list[str] = []
        params: list[object] = []
        if player:
            clauses.append("(g.white LIKE ? COLLATE NOCASE OR g.black LIKE ? COLLATE NOCASE)")
            needle = f"%{player}%"
            params.extend([needle, needle])
        if event:
            clauses.append("g.event LIKE ? COLLATE NOCASE")
            params.append(f"%{event}%")
        if eco:
            clauses.append("g.eco LIKE ? COLLATE NOCASE")
            params.append(f"{eco}%")
        if opening:
            clauses.append("g.opening LIKE ? COLLATE NOCASE")
            params.append(f"%{opening}%")
        if result:
            clauses.append("g.result=?")
            params.append(result)
        if source_id is not None:
            clauses.append("g.source_id=?")
            params.append(source_id)
        if source_name:
            clauses.append("s.source_name LIKE ? COLLATE NOCASE")
            params.append(f"%{source_name}%")
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
