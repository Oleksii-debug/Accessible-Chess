from __future__ import annotations

"""SQLite data core for Accessible Chess Stage 2.

The database layer is presentation-neutral. It stores source provenance,
loss-preserving PGN text, import quality status and exact-position references.
It never modifies source files in place.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from .gametree import PgnGame, parse_games, serialize_game
from .import_contract import sha256_utf8_text
from .position_editor import PositionState

IMPORT_STATUSES = {"full", "partial", "damaged", "warning"}
IMPORT_ATTEMPT_STATUSES = {"pending", "full", "warning", "damaged", "failed"}
ACSDB_SCHEMA_VERSION = 2


def _require_exact_int(value: object, name: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an exact integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _require_text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be exact text")
    if not allow_empty and not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _require_optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, name, allow_empty=True)


def _bounded_limit(value: object) -> int:
    return max(1, min(_require_exact_int(value, "limit"), 1000))


def _require_id(value: object, name: str) -> int:
    return _require_exact_int(value, name, minimum=1)


def escape_like_literal(value: str) -> str:
    """Escape exact user text for a parameter bound to ``LIKE ... ESCAPE '!'``."""
    value = _require_text(value, "LIKE literal", allow_empty=True)
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


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
    def position_key(fen: str) -> str:
        _require_text(fen, "fen")
        # Reuse the canonical structural FEN parser rather than indexing an
        # arbitrary four-token string. PositionState intentionally validates
        # structure, metadata and exact counters without requiring a playable
        # position, which is appropriate for historical/editor data.
        state = PositionState.from_fen(fen)
        return " ".join(state.to_fen().split()[:4])

    def _insert_source(self, source_name: str, source_format: str, sha256: str | None = None) -> int:
        source_name = _require_text(source_name, "source_name")
        source_format = _require_text(source_format, "source_format")
        sha256 = _require_optional_text(sha256, "sha256")
        cur = self.conn.execute(
            "INSERT INTO sources(source_name, source_format, sha256, imported_at) VALUES(?,?,?,?)",
            (source_name, source_format.lower(), sha256, self._now()),
        )
        return int(cur.lastrowid)

    def add_source(self, source_name: str, source_format: str, sha256: str | None = None) -> int:
        with self.conn:
            return self._insert_source(source_name, source_format, sha256)

    def _create_import_attempt(self, source_name: str, source_format: str, sha256: str) -> int:
        source_name = _require_text(source_name, "source_name")
        source_format = _require_text(source_format, "source_format")
        sha256 = _require_text(sha256, "sha256")
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO import_attempts(source_name, source_format, sha256, started_at, status) VALUES(?,?,?,?,?)",
                (source_name, source_format.lower(), sha256, self._now(), "pending"),
            )
            return int(cur.lastrowid)

    def _finish_import_attempt(self, attempt_id: int, *, status: str, source_id: int | None = None,
                               game_count: int = 0, warning_count: int = 0,
                               error_message: str | None = None) -> None:
        attempt_id = _require_id(attempt_id, "attempt_id")
        status = _require_text(status, "status")
        if status not in IMPORT_ATTEMPT_STATUSES - {"pending"}:
            raise ValueError(f"Unsupported import attempt status: {status}")
        if source_id is not None:
            source_id = _require_id(source_id, "source_id")
        game_count = _require_exact_int(game_count, "game_count", minimum=0)
        warning_count = _require_exact_int(warning_count, "warning_count", minimum=0)
        error_message = _require_optional_text(error_message, "error_message")
        self.conn.execute(
            """UPDATE import_attempts
               SET finished_at=?, status=?, source_id=?, game_count=?, warning_count=?, error_message=?
               WHERE id=?""",
            (self._now(), status, source_id, game_count, warning_count, error_message, attempt_id),
        )

    def _insert_game(self, game: PgnGame, source_id: int, *, raw_pgn: str | None = None,
                     import_status: str | None = None) -> int:
        if not isinstance(game, PgnGame):
            raise TypeError("game must be a PgnGame")
        source_id = _require_id(source_id, "source_id")
        raw_pgn = _require_optional_text(raw_pgn, "raw_pgn")
        if import_status is not None:
            import_status = _require_text(import_status, "import_status")
        status = import_status or ("warning" if game.warnings else "full")
        if status not in IMPORT_STATUSES:
            raise ValueError(f"Unsupported import status: {status}")
        # Validate mutable GameTree state even when caller supplies raw source
        # text. This prevents malformed post-construction DTOs reaching SQLite.
        validated_pgn = serialize_game(game)
        tags = game.tags
        pgn_text = raw_pgn if raw_pgn is not None else validated_pgn
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
        text = _require_text(text, "text", allow_empty=True)
        source_name = _require_text(source_name, "source_name")
        digest = sha256_utf8_text(text)
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
        game_id = _require_id(game_id, "game_id")
        row = self.conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        return dict(row) if row else None

    def get_source(self, source_id: int) -> dict | None:
        source_id = _require_id(source_id, "source_id")
        row = self.conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        return dict(row) if row else None

    def get_import_attempt(self, attempt_id: int) -> dict | None:
        attempt_id = _require_id(attempt_id, "attempt_id")
        row = self.conn.execute("SELECT * FROM import_attempts WHERE id=?", (attempt_id,)).fetchone()
        return dict(row) if row else None

    def list_import_attempts(self, *, status: str | None = None, sha256: str | None = None,
                             limit: int = 100) -> list[dict]:
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            status = _require_text(status, "status")
            if status not in IMPORT_ATTEMPT_STATUSES:
                raise ValueError(f"Unsupported import attempt status: {status}")
            clauses.append("status=?")
            params.append(status)
        sha256 = _require_optional_text(sha256, "sha256")
        if sha256:
            clauses.append("sha256=?")
            params.append(sha256)
        sql = "SELECT * FROM import_attempts"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(_bounded_limit(limit))
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def search_games(self, *, player: str | None = None, event: str | None = None,
                     eco: str | None = None, opening: str | None = None,
                     result: str | None = None, source_id: int | None = None,
                     source_name: str | None = None, limit: int = 100) -> list[dict]:
        player = _require_optional_text(player, "player")
        event = _require_optional_text(event, "event")
        eco = _require_optional_text(eco, "eco")
        opening = _require_optional_text(opening, "opening")
        result = _require_optional_text(result, "result")
        source_name = _require_optional_text(source_name, "source_name")
        if source_id is not None:
            source_id = _require_id(source_id, "source_id")
        clauses: list[str] = []
        params: list[object] = []
        if player:
            clauses.append(
                "(g.white LIKE ? ESCAPE '!' COLLATE NOCASE "
                "OR g.black LIKE ? ESCAPE '!' COLLATE NOCASE)"
            )
            needle = f"%{escape_like_literal(player)}%"
            params.extend([needle, needle])
        if event:
            clauses.append("g.event LIKE ? ESCAPE '!' COLLATE NOCASE")
            params.append(f"%{escape_like_literal(event)}%")
        if eco:
            clauses.append("g.eco LIKE ? ESCAPE '!' COLLATE NOCASE")
            params.append(f"{escape_like_literal(eco)}%")
        if opening:
            clauses.append("g.opening LIKE ? ESCAPE '!' COLLATE NOCASE")
            params.append(f"%{escape_like_literal(opening)}%")
        if result:
            clauses.append("g.result=?")
            params.append(result)
        if source_id is not None:
            clauses.append("g.source_id=?")
            params.append(source_id)
        if source_name:
            clauses.append("s.source_name LIKE ? ESCAPE '!' COLLATE NOCASE")
            params.append(f"%{escape_like_literal(source_name)}%")
        sql = "SELECT g.* FROM games g JOIN sources s ON s.id=g.source_id"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY g.id LIMIT ?"
        params.append(_bounded_limit(limit))
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def record_position(self, game_id: int, ply: int, fen: str) -> None:
        game_id = _require_id(game_id, "game_id")
        ply = _require_exact_int(ply, "ply", minimum=0)
        key = self.position_key(fen)
        canonical_fen = PositionState.from_fen(fen).to_fen()
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO positions(game_id, ply, fen, position_key) VALUES(?,?,?,?)",
                (game_id, ply, canonical_fen, key),
            )

    def record_positions(self, game_id: int, positions: Iterable[tuple[int, str]]) -> None:
        game_id = _require_id(game_id, "game_id")
        try:
            snapshot = tuple(positions)
        except TypeError as exc:
            raise TypeError("positions must be an iterable of (ply, fen) tuples") from exc
        rows: list[tuple[int, int, str, str]] = []
        seen_plies: set[int] = set()
        for item in snapshot:
            if type(item) is not tuple or len(item) != 2:
                raise TypeError("each position must be an exact (ply, fen) tuple")
            ply, fen = item
            ply = _require_exact_int(ply, "ply", minimum=0)
            if ply in seen_plies:
                raise ValueError("positions must not contain duplicate ply values")
            seen_plies.add(ply)
            key = self.position_key(fen)
            canonical_fen = PositionState.from_fen(fen).to_fen()
            rows.append((game_id, ply, canonical_fen, key))
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO positions(game_id, ply, fen, position_key) VALUES(?,?,?,?)", rows
            )

    def search_position(self, fen: str, limit: int = 100) -> list[dict]:
        key = self.position_key(fen)
        rows = self.conn.execute(
            """SELECT g.*, p.ply AS matched_ply, p.fen AS matched_fen
               FROM positions p JOIN games g ON g.id=p.game_id
               WHERE p.position_key=? ORDER BY g.id, p.ply LIMIT ?""",
            (key, _bounded_limit(limit)),
        ).fetchall()
        return [dict(row) for row in rows]
