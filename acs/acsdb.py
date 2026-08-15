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
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        try:
            self._migrate_schema()
        except Exception:
            # SQLite keeps an open file handle on Windows. A failed schema
            # preflight must not leave the database locked merely because
            # construction did not return a usable AcsDatabase instance.
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
        if status not in IMPORT_ATTEMPT_STATUSES:
            raise ValueError(f"Unsupported import attempt status: {status}")
        with self.conn:
            self.conn.execute(
                "UPDATE import_attempts SET finished_at=?, status=?, source_id=?, game_count=?, warning_count=?, error_message=? WHERE id=?",
                (self._now(), status, source_id, game_count, warning_count, error_message, attempt_id),
            )

    def import_pgn(self, source_name: str, pgn_text: str, source_format: str = "pgn") -> ImportReport:
        raw = pgn_text.encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        attempt_id = self._create_import_attempt(source_name, source_format, digest)
        try:
            games = parse_games(pgn_text)
            if not games:
                self._finish_import_attempt(attempt_id, status="damaged", error_message="No PGN game found")
                return ImportReport(source_id=0, attempt_id=attempt_id, damaged=1)
            with self.conn:
                source_id = self._insert_source(source_name, source_format, digest)
                report = ImportReport(source_id=source_id, attempt_id=attempt_id)
                for index, game in enumerate(games):
                    warnings = list(game.warnings)
                    status = "warning" if warnings else "full"
                    game_id = self._insert_game(source_id, index, game, status=status, warnings=warnings)
                    report.game_ids.append(game_id)
                    if status == "warning":
                        report.warning += 1
                    else:
                        report.full += 1
            self._finish_import_attempt(
                attempt_id,
                status="warning" if report.warning else "full",
                source_id=source_id,
                game_count=len(report.game_ids),
                warning_count=report.warning,
            )
            return report
        except Exception as exc:
            self._finish_import_attempt(attempt_id, status="failed", error_message=str(exc))
            raise

    def _insert_game(self, source_id: int, source_index: int, game: PgnGame, *, status: str,
                     warnings: Iterable[str]) -> int:
        if status not in IMPORT_STATUSES:
            raise ValueError(f"Unsupported import status: {status}")
        tags = game.tags
        cur = self.conn.execute(
            """
            INSERT INTO games(source_id, source_index, import_status, warnings_json,
                              event, site, game_date, round, white, black, result, eco, opening,
                              start_fen, pgn_text)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                source_id, source_index, status, json.dumps(list(warnings), ensure_ascii=False),
                tags.get("Event"), tags.get("Site"), tags.get("Date"), tags.get("Round"),
                tags.get("White"), tags.get("Black"), tags.get("Result"), tags.get("ECO"),
                tags.get("Opening"), tags.get("FEN"), serialize_game(game),
            ),
        )
        return int(cur.lastrowid)

    def add_position(self, game_id: int, ply: int, fen: str) -> None:
        self.add_positions([(game_id, ply, fen)])

    def add_positions(self, rows: Iterable[tuple[int, int, str]]) -> None:
        prepared = [(int(game_id), int(ply), fen, self.position_key(fen)) for game_id, ply, fen in rows]
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO positions(game_id, ply, fen, position_key) VALUES(?,?,?,?)",
                prepared,
            )

    def search_games(self, *, player: str | None = None, event: str | None = None,
                     eco: str | None = None, result: str | None = None,
                     tag: str | None = None) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[str] = []
        if player:
            clauses.append("(white LIKE ? COLLATE NOCASE OR black LIKE ? COLLATE NOCASE)")
            params.extend([f"%{player}%", f"%{player}%"])
        if event:
            clauses.append("event LIKE ? COLLATE NOCASE")
            params.append(f"%{event}%")
        if eco:
            clauses.append("eco = ? COLLATE NOCASE")
            params.append(eco)
        if result:
            clauses.append("result = ?")
            params.append(result)
        if tag:
            clauses.append("pgn_text LIKE ? COLLATE NOCASE")
            params.append(f"%{tag}%")
        query = "SELECT * FROM games"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id"
        return list(self.conn.execute(query, params))

    def find_position(self, fen: str) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM positions WHERE position_key=? ORDER BY game_id, ply",
            (self.position_key(fen),),
        ))
