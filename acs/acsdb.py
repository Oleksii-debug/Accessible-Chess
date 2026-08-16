from __future__ import annotations

"""Versioned SQLite data core for Accessible Chess.

The database is presentation-neutral and source-preserving. It stores exact PGN,
stable provenance, semantic game identities, normalized catalog entities,
position references, import audit records and deterministic search indexes.
Source files are never modified in place.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable, Sequence
import uuid

from .game_identity import IDENTITY_SCHEMA_VERSION, identity_for_game
from .gametree import PgnGame, parse_games, serialize_game
from .gametree_navigation import VariationPath, resolve_line

IMPORT_STATUSES = {"full", "partial", "damaged", "warning"}
IMPORT_ATTEMPT_STATUSES = {"pending", "full", "warning", "damaged", "failed", "duplicate"}
DUPLICATE_POLICIES = {"keep", "skip_exact_source", "skip_record"}
ACSDB_SCHEMA_VERSION = 3


@dataclass(slots=True)
class ImportReport:
    source_id: int | None
    attempt_id: int | None = None
    game_ids: list[int] = field(default_factory=list)
    full: int = 0
    partial: int = 0
    damaged: int = 0
    warning: int = 0
    duplicate: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.full + self.partial + self.damaged + self.warning + self.duplicate


@dataclass(slots=True)
class BatchImportFailure:
    source_name: str
    attempt_id: int
    error: str


@dataclass(slots=True)
class BatchImportReport:
    reports: list[ImportReport] = field(default_factory=list)
    failures: list[BatchImportFailure] = field(default_factory=list)

    @property
    def source_count(self) -> int:
        return len(self.reports) + len(self.failures)

    @property
    def game_count(self) -> int:
        return sum(len(report.game_ids) for report in self.reports)

    @property
    def skipped(self) -> int:
        return sum(report.skipped for report in self.reports)


class AcsDatabase:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        try:
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute(
                "PRAGMA journal_mode = WAL"
                if self.path != ":memory:"
                else "PRAGMA journal_mode = MEMORY"
            )
            self.conn.execute("PRAGMA synchronous = NORMAL")
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

            CREATE INDEX IF NOT EXISTS idx_import_attempts_sha256
                ON import_attempts(sha256);
            CREATE INDEX IF NOT EXISTS idx_import_attempts_status
                ON import_attempts(status);
            CREATE INDEX IF NOT EXISTS idx_import_attempts_source
                ON import_attempts(source_id);
            """
        )

    def _migrate_to_v3(self) -> None:
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(sources)")}
        if "provenance_id" not in columns:
            self.conn.execute("ALTER TABLE sources ADD COLUMN provenance_id TEXT")

        attempt_sql = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='import_attempts'"
        ).fetchone()
        if attempt_sql and "'duplicate'" not in str(attempt_sql[0]):
            self.conn.executescript(
                """
                ALTER TABLE import_attempts RENAME TO import_attempts_v2;
                CREATE TABLE import_attempts (
                    id INTEGER PRIMARY KEY,
                    source_name TEXT NOT NULL,
                    source_format TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL CHECK(status IN ('pending','full','warning','damaged','failed','duplicate')),
                    source_id INTEGER,
                    game_count INTEGER NOT NULL DEFAULT 0,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT
                );
                INSERT INTO import_attempts
                SELECT id, source_name, source_format, sha256, started_at, finished_at,
                       status, source_id, game_count, warning_count, error_message
                FROM import_attempts_v2;
                DROP TABLE import_attempts_v2;
                """
            )

        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE
            );
            CREATE TABLE IF NOT EXISTS annotators (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE
            );
            CREATE TABLE IF NOT EXISTS openings (
                id INTEGER PRIMARY KEY,
                eco TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                UNIQUE(eco, name)
            );
            CREATE TABLE IF NOT EXISTS game_catalog (
                game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
                white_player_id INTEGER REFERENCES players(id),
                black_player_id INTEGER REFERENCES players(id),
                event_id INTEGER REFERENCES events(id),
                annotator_id INTEGER REFERENCES annotators(id),
                opening_id INTEGER REFERENCES openings(id),
                identity_schema_version INTEGER NOT NULL,
                tree_digest TEXT NOT NULL,
                record_digest TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_provenance
                ON sources(provenance_id);
            CREATE INDEX IF NOT EXISTS idx_catalog_white ON game_catalog(white_player_id);
            CREATE INDEX IF NOT EXISTS idx_catalog_black ON game_catalog(black_player_id);
            CREATE INDEX IF NOT EXISTS idx_catalog_event ON game_catalog(event_id);
            CREATE INDEX IF NOT EXISTS idx_catalog_annotator ON game_catalog(annotator_id);
            CREATE INDEX IF NOT EXISTS idx_catalog_opening ON game_catalog(opening_id);
            CREATE INDEX IF NOT EXISTS idx_catalog_record_digest ON game_catalog(record_digest);
            CREATE INDEX IF NOT EXISTS idx_catalog_tree_digest ON game_catalog(tree_digest);
            CREATE INDEX IF NOT EXISTS idx_games_date ON games(game_date);
            """
        )
        self.conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_import_attempts_sha256
                ON import_attempts(sha256);
            CREATE INDEX IF NOT EXISTS idx_import_attempts_status
                ON import_attempts(status);
            CREATE INDEX IF NOT EXISTS idx_import_attempts_source
                ON import_attempts(source_id);
            """
        )

        for row in self.conn.execute(
            "SELECT id FROM sources WHERE provenance_id IS NULL OR provenance_id=''"
        ):
            self.conn.execute(
                "UPDATE sources SET provenance_id=? WHERE id=?",
                (f"legacy-{int(row[0])}-{uuid.uuid4().hex}", int(row[0])),
            )

        existing = {
            int(row[0]) for row in self.conn.execute("SELECT game_id FROM game_catalog")
        }
        rows = self.conn.execute("SELECT id, pgn_text FROM games ORDER BY id").fetchall()
        for row in rows:
            game_id = int(row["id"])
            if game_id in existing:
                continue
            parsed = parse_games(str(row["pgn_text"]))
            if len(parsed) != 1:
                continue
            self._upsert_catalog(game_id, parsed[0])

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def position_key(fen: str) -> str:
        parts = (fen or "").strip().split()
        if len(parts) < 4:
            raise ValueError(
                "FEN must contain at least placement, turn, castling and en-passant fields"
            )
        return " ".join(parts[:4])

    def _insert_source(
        self,
        source_name: str,
        source_format: str,
        sha256: str | None = None,
        provenance_id: str | None = None,
    ) -> int:
        provenance = provenance_id or f"src-{uuid.uuid4().hex}"
        cur = self.conn.execute(
            """
            INSERT INTO sources(source_name, source_format, sha256, imported_at, provenance_id)
            VALUES(?,?,?,?,?)
            """,
            (source_name, source_format.lower(), sha256, self._now(), provenance),
        )
        return int(cur.lastrowid)

    def add_source(
        self,
        source_name: str,
        source_format: str,
        sha256: str | None = None,
        provenance_id: str | None = None,
    ) -> int:
        with self.conn:
            return self._insert_source(source_name, source_format, sha256, provenance_id)

    def _create_import_attempt(self, source_name: str, source_format: str, sha256: str) -> int:
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO import_attempts(
                    source_name, source_format, sha256, started_at, status
                ) VALUES(?,?,?,?,?)
                """,
                (source_name, source_format.lower(), sha256, self._now(), "pending"),
            )
            return int(cur.lastrowid)

    def _finish_import_attempt(
        self,
        attempt_id: int,
        *,
        status: str,
        source_id: int | None = None,
        game_count: int = 0,
        warning_count: int = 0,
        error_message: str | None = None,
    ) -> None:
        if status not in IMPORT_ATTEMPT_STATUSES - {"pending"}:
            raise ValueError(f"Unsupported import attempt status: {status}")
        self.conn.execute(
            """
            UPDATE import_attempts
            SET finished_at=?, status=?, source_id=?, game_count=?, warning_count=?, error_message=?
            WHERE id=?
            """,
            (
                self._now(),
                status,
                source_id,
                int(game_count),
                int(warning_count),
                error_message,
                int(attempt_id),
            ),
        )

    def _entity_id(self, table: str, name: str | None) -> int | None:
        value = (name or "").strip()
        if not value:
            return None
        if table not in {"players", "events", "annotators"}:
            raise ValueError("unsupported entity table")
        self.conn.execute(f"INSERT OR IGNORE INTO {table}(name) VALUES(?)", (value,))
        row = self.conn.execute(
            f"SELECT id FROM {table} WHERE name=? COLLATE NOCASE", (value,)
        ).fetchone()
        return int(row[0])

    def _opening_id(self, eco: str | None, name: str | None) -> int | None:
        eco_value = (eco or "").strip().upper()
        name_value = (name or "").strip()
        if not eco_value and not name_value:
            return None
        self.conn.execute(
            "INSERT OR IGNORE INTO openings(eco, name) VALUES(?,?)",
            (eco_value, name_value),
        )
        row = self.conn.execute(
            "SELECT id FROM openings WHERE eco=? AND name=?", (eco_value, name_value)
        ).fetchone()
        return int(row[0])

    def _upsert_catalog(self, game_id: int, game: PgnGame) -> None:
        tags = game.tags
        identity = identity_for_game(game)
        self.conn.execute(
            """
            INSERT OR REPLACE INTO game_catalog(
                game_id, white_player_id, black_player_id, event_id, annotator_id,
                opening_id, identity_schema_version, tree_digest, record_digest
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                game_id,
                self._entity_id("players", tags.get("White")),
                self._entity_id("players", tags.get("Black")),
                self._entity_id("events", tags.get("Event")),
                self._entity_id("annotators", tags.get("Annotator")),
                self._opening_id(tags.get("ECO"), tags.get("Opening")),
                identity.schema_version,
                identity.tree_digest,
                identity.record_digest,
            ),
        )

    def _insert_game(
        self,
        game: PgnGame,
        source_id: int,
        *,
        raw_pgn: str | None = None,
        import_status: str | None = None,
    ) -> int:
        status = import_status or ("warning" if game.warnings else "full")
        if status not in IMPORT_STATUSES:
            raise ValueError(f"Unsupported import status: {status}")
        tags = game.tags
        pgn_text = raw_pgn if raw_pgn is not None else serialize_game(game)
        cur = self.conn.execute(
            """
            INSERT INTO games(
                source_id, source_index, import_status, warnings_json,
                event, site, game_date, round, white, black, result, eco,
                opening, start_fen, pgn_text
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                source_id,
                game.source_index,
                status,
                json.dumps(game.warnings, ensure_ascii=False),
                tags.get("Event"),
                tags.get("Site"),
                tags.get("Date"),
                tags.get("Round"),
                tags.get("White"),
                tags.get("Black"),
                game.result,
                tags.get("ECO"),
                tags.get("Opening"),
                tags.get("FEN") if tags.get("SetUp") == "1" else None,
                pgn_text,
            ),
        )
        game_id = int(cur.lastrowid)
        self._upsert_catalog(game_id, game)
        return game_id

    def store_game(
        self,
        game: PgnGame,
        source_id: int,
        *,
        raw_pgn: str | None = None,
        import_status: str | None = None,
    ) -> int:
        with self.conn:
            return self._insert_game(
                game, source_id, raw_pgn=raw_pgn, import_status=import_status
            )

    def _exact_source_exists(self, digest: str) -> int | None:
        row = self.conn.execute(
            "SELECT id FROM sources WHERE sha256=? ORDER BY id LIMIT 1", (digest,)
        ).fetchone()
        return int(row[0]) if row else None

    def _record_duplicate(self, game: PgnGame) -> int | None:
        digest = identity_for_game(game).record_digest
        row = self.conn.execute(
            "SELECT game_id FROM game_catalog WHERE record_digest=? ORDER BY game_id LIMIT 1",
            (digest,),
        ).fetchone()
        return int(row[0]) if row else None

    def import_pgn_text(
        self,
        text: str,
        source_name: str = "memory.pgn",
        *,
        duplicate_policy: str = "keep",
        provenance_id: str | None = None,
    ) -> ImportReport:
        if duplicate_policy not in DUPLICATE_POLICIES:
            raise ValueError(f"Unsupported duplicate policy: {duplicate_policy}")

        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        attempt_id = self._create_import_attempt(source_name, "pgn", digest)

        exact_source = self._exact_source_exists(digest)
        if duplicate_policy == "skip_exact_source" and exact_source is not None:
            with self.conn:
                self._finish_import_attempt(
                    attempt_id,
                    status="duplicate",
                    source_id=exact_source,
                    error_message="exact source digest already imported",
                )
            return ImportReport(
                source_id=exact_source, attempt_id=attempt_id, duplicate=1, skipped=1
            )

        try:
            games = parse_games(text)
            if not games:
                with self.conn:
                    source_id = self._insert_source(
                        source_name, "pgn", digest, provenance_id
                    )
                    self._finish_import_attempt(
                        attempt_id, status="damaged", source_id=source_id
                    )
                return ImportReport(
                    source_id=source_id, attempt_id=attempt_id, damaged=1
                )

            report = ImportReport(source_id=None, attempt_id=attempt_id)
            with self.conn:
                source_id = self._insert_source(
                    source_name, "pgn", digest, provenance_id
                )
                report.source_id = source_id
                for game in games:
                    if duplicate_policy == "skip_record" and self._record_duplicate(game):
                        report.duplicate += 1
                        report.skipped += 1
                        continue
                    status = "warning" if game.warnings else "full"
                    game_id = self._insert_game(game, source_id, import_status=status)
                    report.game_ids.append(game_id)
                    setattr(report, status, getattr(report, status) + 1)

                if report.game_ids:
                    attempt_status = "warning" if report.warning else "full"
                elif report.skipped:
                    attempt_status = "duplicate"
                else:
                    attempt_status = "damaged"
                self._finish_import_attempt(
                    attempt_id,
                    status=attempt_status,
                    source_id=source_id,
                    game_count=len(report.game_ids),
                    warning_count=report.warning,
                    error_message=(
                        f"{report.skipped} duplicate game(s) skipped"
                        if report.skipped
                        else None
                    ),
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

    def import_pgn_batch(
        self,
        sources: Sequence[tuple[str, str]],
        *,
        duplicate_policy: str = "keep",
        atomic: bool = True,
    ) -> BatchImportReport:
        """Import many independent PGN sources as one coherent operation.

        With ``atomic=True`` all source/game/catalog rows are committed together.
        Audit attempt rows survive a failed batch and are marked failed so callers
        receive an exact report without half-imported database content.
        """
        if duplicate_policy not in DUPLICATE_POLICIES:
            raise ValueError(f"Unsupported duplicate policy: {duplicate_policy}")
        prepared: list[tuple[str, str, str, int, list[PgnGame]]] = []
        failures: list[BatchImportFailure] = []
        for source_name, text in sources:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            attempt_id = self._create_import_attempt(source_name, "pgn", digest)
            try:
                prepared.append(
                    (source_name, text, digest, attempt_id, parse_games(text))
                )
            except Exception as exc:
                with self.conn:
                    self._finish_import_attempt(
                        attempt_id,
                        status="failed",
                        error_message=f"{type(exc).__name__}: {exc}",
                    )
                failures.append(
                    BatchImportFailure(
                        source_name, attempt_id, f"{type(exc).__name__}: {exc}"
                    )
                )
                if atomic:
                    for _, _, _, prior_attempt, _ in prepared:
                        with self.conn:
                            self._finish_import_attempt(
                                prior_attempt,
                                status="failed",
                                error_message="batch aborted before storage",
                            )
                    return BatchImportReport(failures=failures)

        reports: list[ImportReport] = []
        try:
            with self.conn:
                for source_name, _text, digest, attempt_id, games in prepared:
                    exact_source = self._exact_source_exists(digest)
                    if duplicate_policy == "skip_exact_source" and exact_source is not None:
                        self._finish_import_attempt(
                            attempt_id,
                            status="duplicate",
                            source_id=exact_source,
                            error_message="exact source digest already imported",
                        )
                        reports.append(
                            ImportReport(
                                source_id=exact_source,
                                attempt_id=attempt_id,
                                duplicate=1,
                                skipped=1,
                            )
                        )
                        continue

                    source_id = self._insert_source(source_name, "pgn", digest)
                    report = ImportReport(source_id=source_id, attempt_id=attempt_id)
                    if not games:
                        report.damaged = 1
                        self._finish_import_attempt(
                            attempt_id, status="damaged", source_id=source_id
                        )
                        reports.append(report)
                        continue

                    for game in games:
                        if duplicate_policy == "skip_record" and self._record_duplicate(game):
                            report.duplicate += 1
                            report.skipped += 1
                            continue
                        status = "warning" if game.warnings else "full"
                        report.game_ids.append(
                            self._insert_game(game, source_id, import_status=status)
                        )
                        setattr(report, status, getattr(report, status) + 1)

                    self._finish_import_attempt(
                        attempt_id,
                        status=(
                            "warning"
                            if report.warning
                            else "full"
                            if report.game_ids
                            else "duplicate"
                            if report.skipped
                            else "damaged"
                        ),
                        source_id=source_id,
                        game_count=len(report.game_ids),
                        warning_count=report.warning,
                        error_message=(
                            f"{report.skipped} duplicate game(s) skipped"
                            if report.skipped
                            else None
                        ),
                    )
                    reports.append(report)
            return BatchImportReport(reports=reports, failures=failures)
        except Exception as exc:
            if not atomic:
                raise
            failure_text = f"{type(exc).__name__}: {exc}"
            with self.conn:
                for _source_name, _text, _digest, attempt_id, _games in prepared:
                    row = self.get_import_attempt(attempt_id)
                    if row and row["status"] == "pending":
                        self._finish_import_attempt(
                            attempt_id, status="failed", error_message=failure_text
                        )
            raise

    def get_game(self, game_id: int) -> dict | None:
        row = self.conn.execute(
            """
            SELECT g.*, s.provenance_id, c.identity_schema_version,
                   c.tree_digest, c.record_digest
            FROM games g
            JOIN sources s ON s.id=g.source_id
            LEFT JOIN game_catalog c ON c.game_id=g.id
            WHERE g.id=?
            """,
            (int(game_id),),
        ).fetchone()
        return dict(row) if row else None

    def get_game_tree(self, game_id: int) -> PgnGame | None:
        row = self.conn.execute(
            "SELECT pgn_text FROM games WHERE id=?", (int(game_id),)
        ).fetchone()
        if not row:
            return None
        games = parse_games(str(row[0]))
        if len(games) != 1:
            raise ValueError(f"stored game {game_id} does not contain exactly one PGN game")
        return games[0]

    def get_variation(self, game_id: int, path: VariationPath = ()) -> object | None:
        game = self.get_game_tree(game_id)
        if game is None:
            return None
        return resolve_line(game, path)

    def get_source(self, source_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM sources WHERE id=?", (int(source_id),)
        ).fetchone()
        return dict(row) if row else None

    def get_import_attempt(self, attempt_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM import_attempts WHERE id=?", (int(attempt_id),)
        ).fetchone()
        return dict(row) if row else None

    def list_import_attempts(
        self,
        *,
        status: str | None = None,
        sha256: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
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
        sql = "SELECT * FROM import_attempts"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 5000)))
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def search_games(
        self,
        *,
        player: str | None = None,
        event: str | None = None,
        annotator: str | None = None,
        eco: str | None = None,
        opening: str | None = None,
        result: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        source_id: int | None = None,
        source_name: str | None = None,
        provenance_id: str | None = None,
        record_digest: str | None = None,
        tree_digest: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[object] = []
        if player:
            clauses.append(
                "(wp.name LIKE ? COLLATE NOCASE OR bp.name LIKE ? COLLATE NOCASE)"
            )
            needle = f"%{player}%"
            params.extend([needle, needle])
        if event:
            clauses.append("ev.name LIKE ? COLLATE NOCASE")
            params.append(f"%{event}%")
        if annotator:
            clauses.append("an.name LIKE ? COLLATE NOCASE")
            params.append(f"%{annotator}%")
        if eco:
            clauses.append("op.eco LIKE ? COLLATE NOCASE")
            params.append(f"{eco}%")
        if opening:
            clauses.append("op.name LIKE ? COLLATE NOCASE")
            params.append(f"%{opening}%")
        if result:
            clauses.append("g.result=?")
            params.append(result)
        if date_from:
            clauses.append("g.game_date>=?")
            params.append(date_from)
        if date_to:
            clauses.append("g.game_date<=?")
            params.append(date_to)
        if source_id is not None:
            clauses.append("g.source_id=?")
            params.append(int(source_id))
        if source_name:
            clauses.append("s.source_name LIKE ? COLLATE NOCASE")
            params.append(f"%{source_name}%")
        if provenance_id:
            clauses.append("s.provenance_id=?")
            params.append(provenance_id)
        if record_digest:
            clauses.append("c.record_digest=?")
            params.append(record_digest)
        if tree_digest:
            clauses.append("c.tree_digest=?")
            params.append(tree_digest)

        sql = """
            SELECT g.*, s.source_name, s.source_format, s.sha256, s.provenance_id,
                   wp.name AS white_player, bp.name AS black_player,
                   ev.name AS normalized_event, an.name AS annotator,
                   op.eco AS normalized_eco, op.name AS normalized_opening,
                   c.identity_schema_version, c.tree_digest, c.record_digest
            FROM games g
            JOIN sources s ON s.id=g.source_id
            LEFT JOIN game_catalog c ON c.game_id=g.id
            LEFT JOIN players wp ON wp.id=c.white_player_id
            LEFT JOIN players bp ON bp.id=c.black_player_id
            LEFT JOIN events ev ON ev.id=c.event_id
            LEFT JOIN annotators an ON an.id=c.annotator_id
            LEFT JOIN openings op ON op.id=c.opening_id
        """
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY g.id LIMIT ? OFFSET ?"
        params.extend([max(1, min(int(limit), 5000)), max(0, int(offset))])
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def catalog_counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in (
            "sources",
            "games",
            "players",
            "events",
            "annotators",
            "openings",
            "positions",
            "import_attempts",
        ):
            result[table] = int(
                self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
        return result

    def record_position(self, game_id: int, ply: int, fen: str) -> None:
        key = self.position_key(fen)
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO positions(game_id, ply, fen, position_key) VALUES(?,?,?,?)",
                (game_id, int(ply), fen, key),
            )

    def record_positions(
        self, game_id: int, positions: Iterable[tuple[int, str]]
    ) -> None:
        rows = [
            (game_id, int(ply), fen, self.position_key(fen))
            for ply, fen in positions
        ]
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO positions(game_id, ply, fen, position_key) VALUES(?,?,?,?)",
                rows,
            )

    def search_position(self, fen: str, limit: int = 100) -> list[dict]:
        key = self.position_key(fen)
        rows = self.conn.execute(
            """
            SELECT g.*, p.ply AS matched_ply, p.fen AS matched_fen,
                   s.provenance_id, c.tree_digest, c.record_digest
            FROM positions p
            JOIN games g ON g.id=p.game_id
            JOIN sources s ON s.id=g.source_id
            LEFT JOIN game_catalog c ON c.game_id=g.id
            WHERE p.position_key=?
            ORDER BY g.id, p.ply
            LIMIT ?
            """,
            (key, max(1, min(int(limit), 5000))),
        ).fetchall()
        return [dict(row) for row in rows]

    def integrity_report(self) -> dict[str, object]:
        quick = [str(row[0]) for row in self.conn.execute("PRAGMA quick_check").fetchall()]
        foreign = [
            tuple(row) for row in self.conn.execute("PRAGMA foreign_key_check").fetchall()
        ]
        return {
            "ok": quick == ["ok"] and not foreign,
            "quick_check": quick,
            "foreign_key_errors": foreign,
            "schema_version": self.schema_version,
        }

    def backup_to(self, destination: str | Path) -> Path:
        report = self.integrity_report()
        if not report["ok"]:
            raise sqlite3.DatabaseError(f"ACSDB integrity check failed: {report}")
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(destination_path))
        try:
            self.conn.backup(target)
            target.commit()
        finally:
            target.close()
        return destination_path

    def recover_copy(self, destination: str | Path) -> Path:
        """Create a validated recovery copy using SQLite's online backup API."""
        return self.backup_to(destination)

    @staticmethod
    def validate_database(path: str | Path) -> dict[str, object]:
        with AcsDatabase(path) as db:
            return db.integrity_report()
