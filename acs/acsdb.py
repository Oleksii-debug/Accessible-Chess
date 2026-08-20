from __future__ import annotations

"""Versioned, source-preserving SQLite data core for Accessible Chess.

ACSDB owns provenance, loss-aware PGN storage, normalized catalog entities,
semantic game identities, exact-position references and import/migration audit
evidence. It is presentation-neutral and never rewrites an external source.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Iterable, Sequence
import unicodedata

from .bookdocument import BookDocument
from .bookreader import BookReader, ReadingLocation
from .game_identity import GameIdentity, identity_for_game, same_game_record
from .gametree import PgnGame, parse_games, serialize_game
from .gametree_legality import (
    DiagnosticSeverity,
    GameTreeLegalityReport,
    LegalityDiagnosticCode,
    link_game_legality,
)
from .gametree_navigation import ROOT_PATH, VariationPath, resolve_line
from .import_contract import sha256_utf8_text
from .position_editor import PositionState
from .training import (
    ExerciseDefinition,
    ExerciseSession,
    TRAINING_DEFINITION_SCHEMA_VERSION,
    TRAINING_SNAPSHOT_SCHEMA_VERSION,
)

IMPORT_STATUSES = {"full", "partial", "damaged", "warning"}
IMPORT_ATTEMPT_STATUSES = {
    "pending", "full", "warning", "damaged", "failed", "duplicate",
}
DUPLICATE_POLICIES = {"keep", "skip_exact_source", "skip_record"}
ACSDB_SCHEMA_VERSION = 4
MAX_IMPORT_DIAGNOSTIC_CODES = 16
MAX_ERROR_MESSAGE_CHARACTERS = 2048
MAX_PROVENANCE_ID_CHARACTERS = 512
MAX_CATALOG_TEXT_CHARACTERS = 4096
MAX_BOOK_DOCUMENT_CHARACTERS = 64 * 1024 * 1024
MAX_TRAINING_DEFINITION_CHARACTERS = 4 * 1024 * 1024
MAX_TRAINING_SNAPSHOT_CHARACTERS = 1024 * 1024
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class AcsImportValidationCode(str, Enum):
    LEGALITY_DAMAGED = "legality_damaged"
    RAW_PGN_GAME_COUNT = "raw_pgn_game_count"
    RAW_PGN_MISMATCH = "raw_pgn_mismatch"


class AcsMigrationCode(str, Enum):
    BACKUP_FAILED = "backup_failed"
    MIGRATION_FAILED = "migration_failed"
    ROLLBACK_UNVERIFIED = "rollback_unverified"
    UNSUPPORTED_NEWER_SCHEMA = "unsupported_newer_schema"


class AcsImportValidationError(ValueError):
    """Stable fail-closed rejection for an unsafe persistence request."""

    def __init__(
        self,
        message: str,
        *,
        code: AcsImportValidationCode,
        source_index: int,
        diagnostic_codes: tuple[LegalityDiagnosticCode, ...],
    ) -> None:
        super().__init__(message)
        self.code = AcsImportValidationCode(code)
        self.source_index = _require_exact_int(source_index, "source_index", minimum=0)
        if not isinstance(diagnostic_codes, tuple):
            raise TypeError("diagnostic_codes must be a tuple")
        canonical_codes = tuple(LegalityDiagnosticCode(item) for item in diagnostic_codes)
        if (
            len(canonical_codes) > MAX_IMPORT_DIAGNOSTIC_CODES
            or len(set(canonical_codes)) != len(canonical_codes)
        ):
            raise ValueError("diagnostic_codes must be bounded and unique")
        self.diagnostic_codes = canonical_codes


class AcsMigrationError(RuntimeError):
    """Migration failure carrying explicit backup and rollback evidence."""

    def __init__(
        self,
        message: str,
        *,
        code: AcsMigrationCode,
        from_version: int,
        to_version: int,
        backup_path: Path | None,
        rolled_back: bool,
        recovery_verified: bool,
    ) -> None:
        super().__init__(message)
        self.code = AcsMigrationCode(code)
        self.from_version = _require_exact_int(from_version, "from_version", minimum=0)
        self.to_version = _require_exact_int(to_version, "to_version", minimum=1)
        self.backup_path = backup_path
        self.rolled_back = bool(rolled_back)
        self.recovery_verified = bool(recovery_verified)


def _require_exact_int(
    value: object,
    name: str,
    *,
    minimum: int | None = None,
) -> int:
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


def _require_identity_text(value: object, name: str) -> str:
    text = _require_text(value, name)
    if (
        len(text) > MAX_PROVENANCE_ID_CHARACTERS
        or text != text.strip()
        or "\n" in text
        or "\r" in text
    ):
        raise ValueError(
            f"{name} must be bounded, single-line text without surrounding whitespace"
        )
    return text


def _require_digest(value: object, name: str) -> str:
    text = _require_text(value, name)
    if _DIGEST_RE.fullmatch(text) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _bounded_limit(value: object) -> int:
    return max(1, min(_require_exact_int(value, "limit"), 1000))


def _require_id(value: object, name: str) -> int:
    return _require_exact_int(value, name, minimum=1)


def _bounded_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:MAX_ERROR_MESSAGE_CHARACTERS]


def _canonical_catalog_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _stable_catalog_id(kind: str, *parts: str) -> str:
    payload = json.dumps(
        [kind, *(_canonical_catalog_text(part).casefold() for part in parts)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"{kind}:v1:{sha256_utf8_text(payload)}"


def _canonical_json(value: object, *, limit: int, name: str) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be JSON serializable") from exc
    if len(payload) > limit:
        raise ValueError(f"{name} exceeds the character safety limit")
    return payload


def escape_like_literal(value: str) -> str:
    """Escape exact user text for a parameter bound to LIKE with ESCAPE '!'."""
    value = _require_text(value, "LIKE literal", allow_empty=True)
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


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


@dataclass(frozen=True, slots=True)
class BatchImportFailure:
    source_name: str
    attempt_id: int
    error: str

    def __post_init__(self) -> None:
        _require_text(self.source_name, "source_name")
        _require_id(self.attempt_id, "attempt_id")
        _require_text(self.error, "error")


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


@dataclass(frozen=True, slots=True)
class MigrationEvidence:
    from_version: int
    to_version: int
    backup_path: Path | None
    started_at: str
    finished_at: str
    catalog_issue_count: int


@dataclass(frozen=True, slots=True)
class RecoveryEvidence:
    source_path: Path
    destination_path: Path
    schema_version: int
    quick_check: tuple[str, ...]
    created_at: str


@dataclass(frozen=True, slots=True)
class _ValidatedGame:
    serialized_pgn: str
    warnings: tuple[str, ...]
    legality: GameTreeLegalityReport
    identity: GameIdentity


def _validate_game_for_persistence(game: PgnGame) -> _ValidatedGame:
    # Structural recovery/export policy is checked before legality so its stable
    # GameTreeSerializationError remains authoritative.
    serialized = serialize_game(game)
    legality = link_game_legality(game)
    if legality.has_errors or not legality.all_moves_legal:
        errors = tuple(
            diagnostic
            for diagnostic in legality.diagnostics
            if diagnostic.severity is DiagnosticSeverity.ERROR
        )
        evidence = errors or legality.diagnostics
        summaries = [diagnostic.summary for diagnostic in evidence[:8]]
        if len(evidence) > 8:
            summaries.append(f"{len(evidence) - 8} additional diagnostic(s)")
        detail = "; ".join(summaries) or "move legality is incomplete"
        raise AcsImportValidationError(
            f"PGN game {game.source_index} failed legality validation: {detail}",
            code=AcsImportValidationCode.LEGALITY_DAMAGED,
            source_index=game.source_index,
            diagnostic_codes=tuple(
                dict.fromkeys(diagnostic.code for diagnostic in evidence)
            )[:MAX_IMPORT_DIAGNOSTIC_CODES],
        )
    warnings = tuple(game.warnings) + tuple(
        diagnostic.summary for diagnostic in legality.diagnostics
    )
    return _ValidatedGame(serialized, warnings, legality, identity_for_game(game))


def _validate_raw_pgn_override(
    game: PgnGame,
    raw_pgn: str,
    validation: _ValidatedGame,
) -> _ValidatedGame:
    raw_games = parse_games(raw_pgn)
    if len(raw_games) != 1:
        raise AcsImportValidationError(
            "raw_pgn must contain exactly one PGN game",
            code=AcsImportValidationCode.RAW_PGN_GAME_COUNT,
            source_index=game.source_index,
            diagnostic_codes=(),
        )
    raw_game = raw_games[0]
    raw_validation = _validate_game_for_persistence(raw_game)
    if not same_game_record(game, raw_game):
        raise AcsImportValidationError(
            "raw_pgn does not describe the validated game record",
            code=AcsImportValidationCode.RAW_PGN_MISMATCH,
            source_index=game.source_index,
            diagnostic_codes=(),
        )
    warnings = tuple(dict.fromkeys(validation.warnings + raw_validation.warnings))
    return _ValidatedGame(
        validation.serialized_pgn,
        warnings,
        validation.legality,
        validation.identity,
    )


class AcsDatabase:
    def __init__(self, path: str | Path = ":memory:") -> None:
        if not isinstance(path, (str, Path)):
            raise TypeError("path must be text or Path")
        self.path = str(path)
        self.last_migration: MigrationEvidence | None = None
        self.last_recovery: RecoveryEvidence | None = None
        self._migration_catalog_issue_count = 0
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

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _database_has_user_objects(self) -> bool:
        row = self.conn.execute(
            """
            SELECT COUNT(*) FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
              AND type IN ('table','index','trigger','view')
            """
        ).fetchone()
        return bool(row and int(row[0]))

    def _next_migration_backup_path(self, from_version: int) -> Path:
        source = Path(self.path)
        stem = Path(f"{source}.pre-v{from_version}-to-v{ACSDB_SCHEMA_VERSION}.backup")
        candidate = stem
        suffix = 2
        while candidate.exists():
            candidate = Path(f"{stem}.{suffix}")
            suffix += 1
        return candidate

    @staticmethod
    def _connection_integrity(
        connection: sqlite3.Connection,
    ) -> tuple[tuple[str, ...], tuple[tuple[object, ...], ...]]:
        quick = tuple(
            str(row[0]) for row in connection.execute("PRAGMA quick_check").fetchall()
        )
        connection.execute("PRAGMA foreign_keys = ON")
        foreign = tuple(
            tuple(row)
            for row in connection.execute("PRAGMA foreign_key_check").fetchall()
        )
        return quick, foreign

    def _create_pre_migration_backup(self, from_version: int) -> Path | None:
        if self.path == ":memory:" or not self._database_has_user_objects():
            return None
        quick, foreign = self._connection_integrity(self.conn)
        if quick != ("ok",) or foreign:
            raise sqlite3.DatabaseError("ACSDB integrity check failed before migration")
        destination = self._next_migration_backup_path(from_version)
        target = sqlite3.connect(str(destination))
        try:
            self.conn.backup(target)
            target.commit()
            copied_version = int(target.execute("PRAGMA user_version").fetchone()[0])
            copied_quick, copied_foreign = self._connection_integrity(target)
            if (
                copied_version != from_version
                or copied_quick != ("ok",)
                or copied_foreign
            ):
                raise sqlite3.DatabaseError("pre-migration backup verification failed")
        except Exception:
            target.close()
            if destination.exists():
                destination.unlink()
            raise
        else:
            target.close()
        return destination

    def _rollback_verified(self, from_version: int) -> bool:
        try:
            quick, foreign = self._connection_integrity(self.conn)
            return self.schema_version == from_version and quick == ("ok",) and not foreign
        except sqlite3.DatabaseError:
            return False

    def _migrate_schema(self) -> None:
        current = self.schema_version
        if current > ACSDB_SCHEMA_VERSION:
            raise AcsMigrationError(
                f"ACSDB schema {current} is newer than supported schema {ACSDB_SCHEMA_VERSION}",
                code=AcsMigrationCode.UNSUPPORTED_NEWER_SCHEMA,
                from_version=current,
                to_version=ACSDB_SCHEMA_VERSION,
                backup_path=None,
                rolled_back=True,
                recovery_verified=True,
            )
        if current == ACSDB_SCHEMA_VERSION:
            return

        started_at = self._now()
        try:
            backup_path = self._create_pre_migration_backup(current)
        except Exception as exc:
            raise AcsMigrationError(
                f"ACSDB migration backup failed before schema changes: {exc}",
                code=AcsMigrationCode.BACKUP_FAILED,
                from_version=current,
                to_version=ACSDB_SCHEMA_VERSION,
                backup_path=None,
                rolled_back=True,
                recovery_verified=self._rollback_verified(current),
            ) from exc

        self._migration_catalog_issue_count = 0
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            target = current
            while target < ACSDB_SCHEMA_VERSION:
                target += 1
                migration = getattr(self, f"_migrate_to_v{target}", None)
                if migration is None:
                    raise RuntimeError(
                        f"Missing ACSDB migration from {target - 1} to {target}"
                    )
                migration()
                self.conn.execute(f"PRAGMA user_version = {target}")
            finished_at = self._now()
            self.conn.execute(
                """
                INSERT INTO schema_migrations(
                    from_version, to_version, backup_name, started_at,
                    finished_at, catalog_issue_count
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    current,
                    ACSDB_SCHEMA_VERSION,
                    backup_path.name if backup_path is not None else None,
                    started_at,
                    finished_at,
                    self._migration_catalog_issue_count,
                ),
            )
            self.conn.commit()
        except Exception as exc:
            try:
                self.conn.rollback()
                rolled_back = True
            except sqlite3.DatabaseError:
                rolled_back = False
            recovery_verified = rolled_back and self._rollback_verified(current)
            raise AcsMigrationError(
                f"ACSDB migration from {current} to {ACSDB_SCHEMA_VERSION} failed: {exc}",
                code=(
                    AcsMigrationCode.MIGRATION_FAILED
                    if recovery_verified
                    else AcsMigrationCode.ROLLBACK_UNVERIFIED
                ),
                from_version=current,
                to_version=ACSDB_SCHEMA_VERSION,
                backup_path=backup_path,
                rolled_back=rolled_back,
                recovery_verified=recovery_verified,
            ) from exc

        self.last_migration = MigrationEvidence(
            from_version=current,
            to_version=ACSDB_SCHEMA_VERSION,
            backup_path=backup_path,
            started_at=started_at,
            finished_at=finished_at,
            catalog_issue_count=self._migration_catalog_issue_count,
        )

    def _migrate_to_v1(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY,
                source_name TEXT NOT NULL,
                source_format TEXT NOT NULL,
                sha256 TEXT,
                imported_at TEXT NOT NULL
            )
            """,
            """
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
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS positions (
                game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                ply INTEGER NOT NULL,
                fen TEXT NOT NULL,
                position_key TEXT NOT NULL,
                PRIMARY KEY(game_id, ply)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_sources_name ON sources(source_name)",
            "CREATE INDEX IF NOT EXISTS idx_sources_sha256 ON sources(sha256)",
            "CREATE INDEX IF NOT EXISTS idx_games_white ON games(white)",
            "CREATE INDEX IF NOT EXISTS idx_games_black ON games(black)",
            "CREATE INDEX IF NOT EXISTS idx_games_event ON games(event)",
            "CREATE INDEX IF NOT EXISTS idx_games_eco ON games(eco)",
            "CREATE INDEX IF NOT EXISTS idx_games_opening ON games(opening)",
            "CREATE INDEX IF NOT EXISTS idx_games_result ON games(result)",
            "CREATE INDEX IF NOT EXISTS idx_games_source ON games(source_id)",
            "CREATE INDEX IF NOT EXISTS idx_positions_key ON positions(position_key)",
        )
        for statement in statements:
            self.conn.execute(statement)

    def _migrate_to_v2(self) -> None:
        statements = (
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
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_import_attempts_sha256 ON import_attempts(sha256)",
            "CREATE INDEX IF NOT EXISTS idx_import_attempts_status ON import_attempts(status)",
            "CREATE INDEX IF NOT EXISTS idx_import_attempts_source ON import_attempts(source_id)",
        )
        for statement in statements:
            self.conn.execute(statement)

    def _migrate_to_v3(self) -> None:
        source_columns = {
            str(row[1]) for row in self.conn.execute("PRAGMA table_info(sources)")
        }
        if "provenance_id" not in source_columns:
            self.conn.execute("ALTER TABLE sources ADD COLUMN provenance_id TEXT")

        attempt_sql = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='import_attempts'"
        ).fetchone()
        if attempt_sql is None:
            raise sqlite3.DatabaseError("ACSDB v2 import_attempts table is missing")
        if "'duplicate'" not in str(attempt_sql[0]):
            self.conn.execute("ALTER TABLE import_attempts RENAME TO import_attempts_v2")
            self.conn.execute(
                """
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
                )
                """
            )
            self.conn.execute(
                """
                INSERT INTO import_attempts
                SELECT id, source_name, source_format, sha256, started_at,
                       finished_at, status, source_id, game_count, warning_count,
                       error_message
                FROM import_attempts_v2
                """
            )
            self.conn.execute("DROP TABLE import_attempts_v2")

        statements = (
            """
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY,
                catalog_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                catalog_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS annotators (
                id INTEGER PRIMARY KEY,
                catalog_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS openings (
                id INTEGER PRIMARY KEY,
                catalog_id TEXT NOT NULL UNIQUE,
                eco TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT ''
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS game_catalog (
                game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
                catalog_id TEXT NOT NULL,
                white_player_id INTEGER REFERENCES players(id),
                black_player_id INTEGER REFERENCES players(id),
                event_id INTEGER REFERENCES events(id),
                annotator_id INTEGER REFERENCES annotators(id),
                opening_id INTEGER REFERENCES openings(id),
                identity_schema_version INTEGER NOT NULL,
                tree_digest TEXT NOT NULL,
                record_digest TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS catalog_issues (
                game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
                code TEXT NOT NULL,
                detail TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INTEGER PRIMARY KEY,
                from_version INTEGER NOT NULL,
                to_version INTEGER NOT NULL,
                backup_name TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                catalog_issue_count INTEGER NOT NULL DEFAULT 0
            )
            """,
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_provenance ON sources(provenance_id)",
            "CREATE INDEX IF NOT EXISTS idx_catalog_white ON game_catalog(white_player_id)",
            "CREATE INDEX IF NOT EXISTS idx_catalog_black ON game_catalog(black_player_id)",
            "CREATE INDEX IF NOT EXISTS idx_catalog_event ON game_catalog(event_id)",
            "CREATE INDEX IF NOT EXISTS idx_catalog_annotator ON game_catalog(annotator_id)",
            "CREATE INDEX IF NOT EXISTS idx_catalog_opening ON game_catalog(opening_id)",
            "CREATE INDEX IF NOT EXISTS idx_catalog_id ON game_catalog(catalog_id)",
            "CREATE INDEX IF NOT EXISTS idx_catalog_record_digest ON game_catalog(record_digest)",
            "CREATE INDEX IF NOT EXISTS idx_catalog_tree_digest ON game_catalog(tree_digest)",
            "CREATE INDEX IF NOT EXISTS idx_games_date ON games(game_date)",
            "CREATE INDEX IF NOT EXISTS idx_import_attempts_sha256 ON import_attempts(sha256)",
            "CREATE INDEX IF NOT EXISTS idx_import_attempts_status ON import_attempts(status)",
            "CREATE INDEX IF NOT EXISTS idx_import_attempts_source ON import_attempts(source_id)",
        )
        for statement in statements:
            self.conn.execute(statement)

        source_rows = self.conn.execute(
            """
            SELECT id, source_name, source_format, sha256, imported_at,
                   provenance_id
            FROM sources ORDER BY id
            """
        ).fetchall()
        for row in source_rows:
            if isinstance(row["provenance_id"], str) and row["provenance_id"]:
                continue
            provenance = self._next_provenance_id(
                str(row["source_name"]),
                str(row["source_format"]),
                row["sha256"] if isinstance(row["sha256"], str) else None,
            )
            self.conn.execute(
                "UPDATE sources SET provenance_id=? WHERE id=?",
                (provenance, int(row["id"])),
            )

        self.conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS sources_provenance_required_insert
            BEFORE INSERT ON sources
            WHEN NEW.provenance_id IS NULL OR NEW.provenance_id = ''
            BEGIN
                SELECT RAISE(ABORT, 'provenance_id is required');
            END
            """
        )
        self.conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS sources_provenance_required_update
            BEFORE UPDATE OF provenance_id ON sources
            WHEN NEW.provenance_id IS NULL OR NEW.provenance_id = ''
            BEGIN
                SELECT RAISE(ABORT, 'provenance_id is required');
            END
            """
        )

        existing = {
            int(row[0]) for row in self.conn.execute("SELECT game_id FROM game_catalog")
        }
        for row in self.conn.execute("SELECT id, pgn_text FROM games ORDER BY id"):
            game_id = int(row["id"])
            if game_id in existing:
                continue
            try:
                pgn_text = row["pgn_text"]
                if type(pgn_text) is not str:
                    raise TypeError("stored pgn_text is not exact text")
                games = parse_games(pgn_text)
                if len(games) != 1:
                    raise ValueError("stored row does not contain exactly one PGN game")
                validation = _validate_game_for_persistence(games[0])
                self._upsert_catalog(game_id, games[0], validation.identity)
            except Exception as exc:
                self._migration_catalog_issue_count += 1
                code_value = getattr(getattr(exc, "code", None), "value", None)
                code = (
                    str(code_value)
                    if isinstance(code_value, str) and code_value
                    else "invalid_legacy_game"
                )
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO catalog_issues(
                        game_id, code, detail, recorded_at
                    ) VALUES(?,?,?,?)
                    """,
                    (game_id, code, _bounded_error(exc), self._now()),
                )

    def _migrate_to_v4(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY,
                book_key TEXT NOT NULL UNIQUE,
                schema_version INTEGER NOT NULL,
                document_digest TEXT NOT NULL,
                title TEXT NOT NULL,
                author TEXT,
                language TEXT,
                source_name TEXT,
                document_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS book_bookmarks (
                book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                location_schema_version INTEGER NOT NULL,
                snapshot_id TEXT NOT NULL,
                location_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(book_id, name)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS training_definitions (
                exercise_id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                definition_digest TEXT NOT NULL,
                title TEXT NOT NULL,
                source_id TEXT,
                tags_json TEXT NOT NULL,
                definition_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS training_progress (
                exercise_id TEXT PRIMARY KEY
                    REFERENCES training_definitions(exercise_id) ON DELETE CASCADE,
                snapshot_schema_version INTEGER NOT NULL,
                status TEXT NOT NULL,
                current_fen TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                mistakes INTEGER NOT NULL,
                hints_used INTEGER NOT NULL,
                snapshot_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_books_title ON books(title)",
            "CREATE INDEX IF NOT EXISTS idx_books_digest ON books(document_digest)",
            "CREATE INDEX IF NOT EXISTS idx_training_status ON training_progress(status)",
            "CREATE INDEX IF NOT EXISTS idx_training_definition_digest ON training_definitions(definition_digest)",
        )
        for statement in statements:
            self.conn.execute(statement)

    @staticmethod
    def position_key(fen: str) -> str:
        _require_text(fen, "fen")
        state = PositionState.from_fen(fen)
        return " ".join(state.to_fen().split()[:4])

    def _next_provenance_id(
        self,
        source_name: str,
        source_format: str,
        sha256: str | None,
    ) -> str:
        base = _stable_catalog_id(
            "source",
            source_format,
            sha256 or "no-digest",
            source_name,
        )
        candidate = base
        occurrence = 2
        while self.conn.execute(
            "SELECT 1 FROM sources WHERE provenance_id=?", (candidate,)
        ).fetchone():
            candidate = f"{base}:{occurrence}"
            occurrence += 1
        return candidate

    def _insert_source(
        self,
        source_name: str,
        source_format: str,
        sha256: str | None = None,
        provenance_id: str | None = None,
    ) -> int:
        source_name = _require_text(source_name, "source_name")
        source_format = _require_text(source_format, "source_format")
        sha256 = _require_optional_text(sha256, "sha256")
        if sha256:
            _require_digest(sha256, "sha256")
        imported_at = self._now()
        provenance = (
            self._next_provenance_id(
                source_name,
                source_format.lower(),
                sha256,
            )
            if provenance_id is None
            else _require_identity_text(provenance_id, "provenance_id")
        )
        if self.conn.execute(
            "SELECT 1 FROM sources WHERE provenance_id=?", (provenance,)
        ).fetchone():
            raise ValueError("provenance_id already exists")
        cur = self.conn.execute(
            """
            INSERT INTO sources(
                source_name, source_format, sha256, imported_at, provenance_id
            ) VALUES(?,?,?,?,?)
            """,
            (source_name, source_format.lower(), sha256, imported_at, provenance),
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

    def _create_import_attempt(
        self,
        source_name: str,
        source_format: str,
        sha256: str,
    ) -> int:
        source_name = _require_text(source_name, "source_name")
        source_format = _require_text(source_format, "source_format")
        sha256 = _require_digest(sha256, "sha256")
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
        attempt_id = _require_id(attempt_id, "attempt_id")
        status = _require_text(status, "status")
        if status not in IMPORT_ATTEMPT_STATUSES - {"pending"}:
            raise ValueError(f"Unsupported import attempt status: {status}")
        if source_id is not None:
            source_id = _require_id(source_id, "source_id")
        game_count = _require_exact_int(game_count, "game_count", minimum=0)
        warning_count = _require_exact_int(warning_count, "warning_count", minimum=0)
        error_message = _require_optional_text(error_message, "error_message")
        if error_message is not None:
            error_message = error_message[:MAX_ERROR_MESSAGE_CHARACTERS]
        self.conn.execute(
            """
            UPDATE import_attempts
            SET finished_at=?, status=?, source_id=?, game_count=?,
                warning_count=?, error_message=?
            WHERE id=?
            """,
            (
                self._now(), status, source_id, game_count, warning_count,
                error_message, attempt_id,
            ),
        )

    def _entity_id(self, table: str, name: str | None) -> int | None:
        if table not in {"players", "events", "annotators"}:
            raise ValueError("unsupported entity table")
        if name is None:
            return None
        value = _canonical_catalog_text(_require_text(name, "catalog name"))
        if not value:
            return None
        if len(value) > MAX_CATALOG_TEXT_CHARACTERS:
            raise ValueError("catalog name exceeds the supported limit")
        catalog_id = _stable_catalog_id(table[:-1], value)
        self.conn.execute(
            f"INSERT OR IGNORE INTO {table}(catalog_id, name) VALUES(?,?)",
            (catalog_id, value),
        )
        row = self.conn.execute(
            f"SELECT id FROM {table} WHERE catalog_id=?", (catalog_id,)
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("catalog entity insert did not persist")
        return int(row[0])

    def _opening_id(self, eco: str | None, name: str | None) -> int | None:
        eco_value = (
            _canonical_catalog_text(_require_text(eco, "ECO")).upper()
            if eco is not None else ""
        )
        name_value = (
            _canonical_catalog_text(_require_text(name, "opening"))
            if name is not None else ""
        )
        if not eco_value and not name_value:
            return None
        if (
            len(eco_value) > MAX_CATALOG_TEXT_CHARACTERS
            or len(name_value) > MAX_CATALOG_TEXT_CHARACTERS
        ):
            raise ValueError("opening catalog text exceeds the supported limit")
        catalog_id = _stable_catalog_id("opening", eco_value, name_value)
        self.conn.execute(
            "INSERT OR IGNORE INTO openings(catalog_id, eco, name) VALUES(?,?,?)",
            (catalog_id, eco_value, name_value),
        )
        row = self.conn.execute(
            "SELECT id FROM openings WHERE catalog_id=?", (catalog_id,)
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("opening catalog insert did not persist")
        return int(row[0])

    def _upsert_catalog(
        self,
        game_id: int,
        game: PgnGame,
        identity: GameIdentity | None = None,
    ) -> None:
        game_id = _require_id(game_id, "game_id")
        if not isinstance(game, PgnGame):
            raise TypeError("game must be a PgnGame")
        semantic_identity = identity or identity_for_game(game)
        if not isinstance(semantic_identity, GameIdentity):
            raise TypeError("identity must be GameIdentity or None")
        tags = game.tags
        catalog_id = (
            f"game:v{semantic_identity.schema_version}:"
            f"{semantic_identity.record_digest}"
        )
        self.conn.execute(
            """
            INSERT INTO game_catalog(
                game_id, catalog_id, white_player_id, black_player_id,
                event_id, annotator_id, opening_id, identity_schema_version,
                tree_digest, record_digest
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(game_id) DO UPDATE SET
                catalog_id=excluded.catalog_id,
                white_player_id=excluded.white_player_id,
                black_player_id=excluded.black_player_id,
                event_id=excluded.event_id,
                annotator_id=excluded.annotator_id,
                opening_id=excluded.opening_id,
                identity_schema_version=excluded.identity_schema_version,
                tree_digest=excluded.tree_digest,
                record_digest=excluded.record_digest
            """,
            (
                game_id,
                catalog_id,
                self._entity_id("players", tags.get("White")),
                self._entity_id("players", tags.get("Black")),
                self._entity_id("events", tags.get("Event")),
                self._entity_id("annotators", tags.get("Annotator")),
                self._opening_id(tags.get("ECO"), tags.get("Opening")),
                semantic_identity.schema_version,
                semantic_identity.tree_digest,
                semantic_identity.record_digest,
            ),
        )
        self.conn.execute("DELETE FROM catalog_issues WHERE game_id=?", (game_id,))

    def _insert_game(
        self,
        game: PgnGame,
        source_id: int,
        *,
        raw_pgn: str | None = None,
        import_status: str | None = None,
        validated: _ValidatedGame | None = None,
    ) -> int:
        if not isinstance(game, PgnGame):
            raise TypeError("game must be a PgnGame")
        source_id = _require_id(source_id, "source_id")
        raw_pgn = _require_optional_text(raw_pgn, "raw_pgn")
        if import_status is not None:
            import_status = _require_text(import_status, "import_status")
        if validated is not None and not isinstance(validated, _ValidatedGame):
            raise TypeError("validated must be _ValidatedGame or None")
        validation = validated or _validate_game_for_persistence(game)
        if raw_pgn is not None:
            validation = _validate_raw_pgn_override(game, raw_pgn, validation)
        status = import_status or ("warning" if validation.warnings else "full")
        if status not in IMPORT_STATUSES:
            raise ValueError(f"Unsupported import status: {status}")
        if status == "full" and validation.warnings:
            raise ValueError("a game with preserved warnings cannot be stored as full")
        tags = game.tags
        pgn_text = raw_pgn if raw_pgn is not None else validation.serialized_pgn
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
                json.dumps(validation.warnings, ensure_ascii=False),
                tags.get("Event"), tags.get("Site"), tags.get("Date"),
                tags.get("Round"), tags.get("White"), tags.get("Black"),
                game.result, tags.get("ECO"), tags.get("Opening"),
                tags.get("FEN") if tags.get("SetUp") == "1" else None,
                pgn_text,
            ),
        )
        game_id = int(cur.lastrowid)
        self._upsert_catalog(game_id, game, validation.identity)
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
        digest = _require_digest(digest, "digest")
        row = self.conn.execute(
            "SELECT id FROM sources WHERE sha256=? ORDER BY id LIMIT 1", (digest,)
        ).fetchone()
        return int(row[0]) if row else None

    def _record_duplicate(self, identity: GameIdentity) -> int | None:
        if not isinstance(identity, GameIdentity):
            raise TypeError("identity must be GameIdentity")
        rows = self.conn.execute(
            """
            SELECT c.game_id, g.pgn_text
            FROM game_catalog c
            JOIN games g ON g.id=c.game_id
            WHERE c.identity_schema_version=? AND c.record_digest=?
            ORDER BY c.game_id
            """,
            (identity.schema_version, identity.record_digest),
        ).fetchall()
        # The index narrows candidates, but raw stored evidence remains
        # authoritative if a database was externally edited or partially
        # recovered. A stale catalog row must never cause false coalescing.
        for row in rows:
            try:
                if type(row["pgn_text"]) is not str:
                    continue
                games = parse_games(row["pgn_text"])
                if len(games) != 1:
                    continue
                validation = _validate_game_for_persistence(games[0])
                if validation.identity.record_digest == identity.record_digest:
                    return int(row["game_id"])
            except Exception:
                continue
        return None

    def import_pgn_text(
        self,
        text: str,
        source_name: str = "memory.pgn",
        *,
        duplicate_policy: str = "keep",
        provenance_id: str | None = None,
    ) -> ImportReport:
        text = _require_text(text, "text", allow_empty=True)
        source_name = _require_text(source_name, "source_name")
        duplicate_policy = _require_text(duplicate_policy, "duplicate_policy")
        if duplicate_policy not in DUPLICATE_POLICIES:
            raise ValueError(f"Unsupported duplicate policy: {duplicate_policy}")
        if provenance_id is not None:
            provenance_id = _require_identity_text(provenance_id, "provenance_id")

        digest = sha256_utf8_text(text)
        attempt_id = self._create_import_attempt(source_name, "pgn", digest)
        try:
            games = parse_games(text)
            validated_games = tuple(
                _validate_game_for_persistence(game) for game in games
            )
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
                    source_id=exact_source,
                    attempt_id=attempt_id,
                    duplicate=1,
                    skipped=1,
                )

            report = ImportReport(source_id=None, attempt_id=attempt_id)
            with self.conn:
                source_id = self._insert_source(
                    source_name, "pgn", digest, provenance_id
                )
                report.source_id = source_id
                for game, validation in zip(games, validated_games, strict=True):
                    if (
                        duplicate_policy == "skip_record"
                        and self._record_duplicate(validation.identity) is not None
                    ):
                        report.duplicate += 1
                        report.skipped += 1
                        continue
                    status = "warning" if validation.warnings else "full"
                    game_id = self._insert_game(
                        game,
                        source_id,
                        import_status=status,
                        validated=validation,
                    )
                    report.game_ids.append(game_id)
                    setattr(report, status, getattr(report, status) + 1)

                attempt_status = (
                    "warning" if report.warning else
                    "full" if report.game_ids else
                    "duplicate" if report.skipped else "damaged"
                )
                self._finish_import_attempt(
                    attempt_id,
                    status=attempt_status,
                    source_id=source_id,
                    game_count=len(report.game_ids),
                    warning_count=report.warning,
                    error_message=(
                        f"{report.skipped} duplicate game(s) skipped"
                        if report.skipped else None
                    ),
                )
            return report
        except Exception as exc:
            with self.conn:
                self._finish_import_attempt(
                    attempt_id, status="failed", error_message=_bounded_error(exc)
                )
            raise

    @staticmethod
    def _snapshot_batch_sources(
        sources: Sequence[tuple[str, str]],
    ) -> tuple[tuple[str, str], ...]:
        if isinstance(sources, (str, bytes)):
            raise TypeError("sources must be a sequence of (source_name, text) tuples")
        try:
            snapshot = tuple(sources)
        except TypeError as exc:
            raise TypeError(
                "sources must be a sequence of (source_name, text) tuples"
            ) from exc
        result: list[tuple[str, str]] = []
        for item in snapshot:
            if type(item) is not tuple or len(item) != 2:
                raise TypeError("each batch source must be an exact two-item tuple")
            result.append(
                (
                    _require_text(item[0], "source_name"),
                    _require_text(item[1], "text", allow_empty=True),
                )
            )
        return tuple(result)

    def import_pgn_batch(
        self,
        sources: Sequence[tuple[str, str]],
        *,
        duplicate_policy: str = "keep",
        atomic: bool = True,
    ) -> BatchImportReport:
        duplicate_policy = _require_text(duplicate_policy, "duplicate_policy")
        if duplicate_policy not in DUPLICATE_POLICIES:
            raise ValueError(f"Unsupported duplicate policy: {duplicate_policy}")
        if type(atomic) is not bool:
            raise TypeError("atomic must be an exact boolean")
        snapshot = self._snapshot_batch_sources(sources)

        if not atomic:
            reports: list[ImportReport] = []
            failures: list[BatchImportFailure] = []
            for source_name, text in snapshot:
                try:
                    reports.append(
                        self.import_pgn_text(
                            text, source_name, duplicate_policy=duplicate_policy
                        )
                    )
                except Exception as exc:
                    digest = sha256_utf8_text(text)
                    row = self.conn.execute(
                        """
                        SELECT id FROM import_attempts
                        WHERE source_name=? AND sha256=? ORDER BY id DESC LIMIT 1
                        """,
                        (source_name, digest),
                    ).fetchone()
                    if row is None:
                        raise sqlite3.DatabaseError(
                            "failed import attempt evidence is missing"
                        ) from exc
                    failures.append(
                        BatchImportFailure(source_name, int(row[0]), _bounded_error(exc))
                    )
            return BatchImportReport(reports=reports, failures=failures)

        attempts: list[tuple[str, str, str, int]] = []
        for source_name, text in snapshot:
            digest = sha256_utf8_text(text)
            attempts.append(
                (
                    source_name,
                    text,
                    digest,
                    self._create_import_attempt(source_name, "pgn", digest),
                )
            )

        prepared: list[
            tuple[
                str, str, str, int, tuple[PgnGame, ...], tuple[_ValidatedGame, ...]
            ]
        ] = []
        preparation_failure: tuple[int, Exception] | None = None
        for index, (source_name, text, digest, attempt_id) in enumerate(attempts):
            try:
                games = tuple(parse_games(text))
                validations = tuple(
                    _validate_game_for_persistence(game) for game in games
                )
                prepared.append(
                    (source_name, text, digest, attempt_id, games, validations)
                )
            except Exception as exc:
                preparation_failure = (index, exc)
                break

        if preparation_failure is not None:
            failed_index, failure = preparation_failure
            failures: list[BatchImportFailure] = []
            with self.conn:
                for index, (source_name, _text, _digest, attempt_id) in enumerate(
                    attempts
                ):
                    error = (
                        _bounded_error(failure)
                        if index == failed_index else "batch aborted before storage"
                    )
                    self._finish_import_attempt(
                        attempt_id, status="failed", error_message=error
                    )
                    failures.append(BatchImportFailure(source_name, attempt_id, error))
            return BatchImportReport(failures=failures)

        reports: list[ImportReport] = []
        try:
            with self.conn:
                for (
                    source_name, _text, digest, attempt_id, games, validations,
                ) in prepared:
                    exact_source = self._exact_source_exists(digest)
                    if (
                        duplicate_policy == "skip_exact_source"
                        and exact_source is not None
                    ):
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

                    for game, validation in zip(games, validations, strict=True):
                        if (
                            duplicate_policy == "skip_record"
                            and self._record_duplicate(validation.identity) is not None
                        ):
                            report.duplicate += 1
                            report.skipped += 1
                            continue
                        status = "warning" if validation.warnings else "full"
                        report.game_ids.append(
                            self._insert_game(
                                game,
                                source_id,
                                import_status=status,
                                validated=validation,
                            )
                        )
                        setattr(report, status, getattr(report, status) + 1)

                    self._finish_import_attempt(
                        attempt_id,
                        status=(
                            "warning" if report.warning else
                            "full" if report.game_ids else
                            "duplicate" if report.skipped else "damaged"
                        ),
                        source_id=source_id,
                        game_count=len(report.game_ids),
                        warning_count=report.warning,
                        error_message=(
                            f"{report.skipped} duplicate game(s) skipped"
                            if report.skipped else None
                        ),
                    )
                    reports.append(report)
            return BatchImportReport(reports=reports)
        except Exception as exc:
            failure_text = _bounded_error(exc)
            failures = []
            with self.conn:
                for source_name, _text, _digest, attempt_id in attempts:
                    self._finish_import_attempt(
                        attempt_id, status="failed", error_message=failure_text
                    )
                    failures.append(
                        BatchImportFailure(source_name, attempt_id, failure_text)
                    )
            return BatchImportReport(failures=failures)

    def get_game(self, game_id: int) -> dict | None:
        game_id = _require_id(game_id, "game_id")
        row = self.conn.execute(
            """
            SELECT g.*, s.provenance_id, c.catalog_id,
                   c.identity_schema_version, c.tree_digest, c.record_digest
            FROM games g
            JOIN sources s ON s.id=g.source_id
            LEFT JOIN game_catalog c ON c.game_id=g.id
            WHERE g.id=?
            """,
            (game_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_game_tree(self, game_id: int) -> PgnGame | None:
        game_id = _require_id(game_id, "game_id")
        row = self.conn.execute(
            "SELECT pgn_text FROM games WHERE id=?", (game_id,)
        ).fetchone()
        if not row:
            return None
        pgn_text = row[0]
        if type(pgn_text) is not str:
            raise ValueError(f"stored game {game_id} does not contain PGN text")
        games = parse_games(pgn_text)
        if len(games) != 1:
            raise ValueError(
                f"stored game {game_id} does not contain exactly one PGN game"
            )
        _validate_game_for_persistence(games[0])
        return games[0]

    def get_variation(
        self,
        game_id: int,
        path: VariationPath = ROOT_PATH,
    ) -> object | None:
        game = self.get_game_tree(game_id)
        if game is None:
            return None
        return resolve_line(game, path)

    def get_source(self, source_id: int) -> dict | None:
        source_id = _require_id(source_id, "source_id")
        row = self.conn.execute(
            "SELECT * FROM sources WHERE id=?", (source_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_import_attempt(self, attempt_id: int) -> dict | None:
        attempt_id = _require_id(attempt_id, "attempt_id")
        row = self.conn.execute(
            "SELECT * FROM import_attempts WHERE id=?", (attempt_id,)
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
            status = _require_text(status, "status")
            if status not in IMPORT_ATTEMPT_STATUSES:
                raise ValueError(f"Unsupported import attempt status: {status}")
            clauses.append("status=?")
            params.append(status)
        sha256 = _require_optional_text(sha256, "sha256")
        if sha256:
            clauses.append("sha256=?")
            params.append(_require_digest(sha256, "sha256"))
        sql = "SELECT * FROM import_attempts"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(_bounded_limit(limit))
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def list_migration_events(self, *, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM schema_migrations ORDER BY id DESC LIMIT ?",
            (_bounded_limit(limit),),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_catalog_issues(self, *, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT i.*, g.source_id, g.source_index
            FROM catalog_issues i
            JOIN games g ON g.id=i.game_id
            ORDER BY i.game_id LIMIT ?
            """,
            (_bounded_limit(limit),),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _book_wire(document: BookDocument) -> tuple[str, str, str]:
        if not isinstance(document, BookDocument):
            raise TypeError("document must be a BookDocument")
        payload = document.as_dict()
        wire = _canonical_json(
            payload,
            limit=MAX_BOOK_DOCUMENT_CHARACTERS,
            name="BookDocument",
        )
        digest = sha256_utf8_text(wire)
        key = document.book_id or f"sha256:{digest}"
        return _require_identity_text(key, "book_key"), digest, wire

    def save_book(self, document: BookDocument) -> int:
        """Atomically upsert one validated semantic book snapshot."""

        book_key, digest, wire = self._book_wire(document)
        now = self._now()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO books(
                    book_key, schema_version, document_digest, title, author,
                    language, source_name, document_json, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(book_key) DO UPDATE SET
                    schema_version=excluded.schema_version,
                    document_digest=excluded.document_digest,
                    title=excluded.title,
                    author=excluded.author,
                    language=excluded.language,
                    source_name=excluded.source_name,
                    document_json=excluded.document_json,
                    updated_at=excluded.updated_at
                """,
                (
                    book_key,
                    int(document.as_dict()["schema_version"]),
                    digest,
                    document.title,
                    document.author,
                    document.language,
                    document.source_name,
                    wire,
                    now,
                    now,
                ),
            )
            row = self.conn.execute(
                "SELECT id FROM books WHERE book_key=?", (book_key,)
            ).fetchone()
            if row is None:
                raise sqlite3.DatabaseError("saved book row is unavailable")
            book_id = int(row[0])
            self.conn.execute(
                "DELETE FROM book_bookmarks WHERE book_id=? AND snapshot_id<>?",
                (book_id, digest),
            )
        return book_id

    def _book_row(self, book: int | str) -> sqlite3.Row:
        if type(book) is int:
            query, value = "SELECT * FROM books WHERE id=?", _require_id(book, "book_id")
        elif type(book) is str:
            query, value = (
                "SELECT * FROM books WHERE book_key=?",
                _require_identity_text(book, "book_key"),
            )
        else:
            raise TypeError("book must be an exact integer ID or text key")
        row = self.conn.execute(query, (value,)).fetchone()
        if row is None:
            raise LookupError(f"Unknown book: {book}")
        return row

    def get_book(self, book: int | str) -> BookDocument:
        row = self._book_row(book)
        wire = row["document_json"]
        if type(wire) is not str or len(wire) > MAX_BOOK_DOCUMENT_CHARACTERS:
            raise sqlite3.DatabaseError("stored BookDocument payload is invalid")
        try:
            payload = json.loads(wire)
            document = BookDocument.from_dict(payload)
            canonical_wire = _canonical_json(
                document.as_dict(),
                limit=MAX_BOOK_DOCUMENT_CHARACTERS,
                name="stored BookDocument",
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise sqlite3.DatabaseError("stored BookDocument failed validation") from exc
        digest = sha256_utf8_text(canonical_wire)
        expected_key = document.book_id or f"sha256:{digest}"
        if (
            wire != canonical_wire
            or row["document_digest"] != digest
            or row["book_key"] != expected_key
        ):
            raise sqlite3.DatabaseError("stored BookDocument identity does not match payload")
        return document

    def list_books(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        offset = _require_exact_int(offset, "offset", minimum=0)
        rows = self.conn.execute(
            """
            SELECT id, book_key, schema_version, document_digest, title, author,
                   language, source_name, created_at, updated_at
            FROM books ORDER BY title COLLATE NOCASE, id LIMIT ? OFFSET ?
            """,
            (_bounded_limit(limit), offset),
        ).fetchall()
        return [dict(row) for row in rows]

    def save_bookmark(
        self,
        book: int | str,
        name: str,
        location: ReadingLocation | dict[str, object],
    ) -> None:
        name = _require_identity_text(name.strip() if type(name) is str else name, "bookmark name")
        row = self._book_row(book)
        reader = BookReader(self.get_book(int(row["id"])))
        restored = reader.restore_location(location)
        payload = restored.as_dict()
        wire = _canonical_json(
            payload,
            limit=MAX_TRAINING_SNAPSHOT_CHARACTERS,
            name="book reading location",
        )
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO book_bookmarks(
                    book_id, name, location_schema_version, snapshot_id,
                    location_json, updated_at
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT(book_id, name) DO UPDATE SET
                    location_schema_version=excluded.location_schema_version,
                    snapshot_id=excluded.snapshot_id,
                    location_json=excluded.location_json,
                    updated_at=excluded.updated_at
                """,
                (
                    int(row["id"]),
                    name,
                    int(payload["schema_version"]),
                    restored.snapshot_id,
                    wire,
                    self._now(),
                ),
            )

    def load_bookmark(
        self,
        book: int | str,
        name: str,
    ) -> ReadingLocation:
        name = _require_identity_text(name.strip() if type(name) is str else name, "bookmark name")
        row = self._book_row(book)
        bookmark = self.conn.execute(
            "SELECT * FROM book_bookmarks WHERE book_id=? AND name=?",
            (int(row["id"]), name),
        ).fetchone()
        if bookmark is None:
            raise LookupError(f"Unknown book bookmark: {name}")
        try:
            payload = json.loads(bookmark["location_json"])
            reader = BookReader(self.get_book(int(row["id"])))
            location = reader.restore_location(payload)
        except (TypeError, ValueError, LookupError, json.JSONDecodeError) as exc:
            raise sqlite3.DatabaseError("stored book bookmark failed validation") from exc
        if location.snapshot_id != bookmark["snapshot_id"]:
            raise sqlite3.DatabaseError("stored book bookmark snapshot does not match")
        return location

    @staticmethod
    def _training_definition_wire(
        definition: ExerciseDefinition,
    ) -> tuple[str, str]:
        if not isinstance(definition, ExerciseDefinition):
            raise TypeError("definition must be an ExerciseDefinition")
        wire = _canonical_json(
            definition.as_dict(),
            limit=MAX_TRAINING_DEFINITION_CHARACTERS,
            name="training definition",
        )
        return sha256_utf8_text(wire), wire

    def save_training_definition(self, definition: ExerciseDefinition) -> str:
        digest, wire = self._training_definition_wire(definition)
        now = self._now()
        with self.conn:
            existing = self.conn.execute(
                "SELECT definition_digest FROM training_definitions WHERE exercise_id=?",
                (definition.exercise_id,),
            ).fetchone()
            if existing is not None and existing[0] != digest:
                self.conn.execute(
                    "DELETE FROM training_progress WHERE exercise_id=?",
                    (definition.exercise_id,),
                )
            self.conn.execute(
                """
                INSERT INTO training_definitions(
                    exercise_id, schema_version, definition_digest, title,
                    source_id, tags_json, definition_json, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(exercise_id) DO UPDATE SET
                    schema_version=excluded.schema_version,
                    definition_digest=excluded.definition_digest,
                    title=excluded.title,
                    source_id=excluded.source_id,
                    tags_json=excluded.tags_json,
                    definition_json=excluded.definition_json,
                    updated_at=excluded.updated_at
                """,
                (
                    definition.exercise_id,
                    TRAINING_DEFINITION_SCHEMA_VERSION,
                    digest,
                    definition.title,
                    definition.source_id,
                    _canonical_json(list(definition.tags), limit=65536, name="training tags"),
                    wire,
                    now,
                    now,
                ),
            )
        return definition.exercise_id

    def get_training_definition(self, exercise_id: str) -> ExerciseDefinition:
        exercise_id = _require_identity_text(exercise_id, "exercise_id")
        row = self.conn.execute(
            "SELECT * FROM training_definitions WHERE exercise_id=?", (exercise_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"Unknown training exercise: {exercise_id}")
        wire = row["definition_json"]
        try:
            if type(wire) is not str or len(wire) > MAX_TRAINING_DEFINITION_CHARACTERS:
                raise ValueError("definition payload size is invalid")
            definition = ExerciseDefinition.from_dict(json.loads(wire))
            digest, canonical_wire = self._training_definition_wire(definition)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise sqlite3.DatabaseError("stored training definition failed validation") from exc
        if (
            definition.exercise_id != exercise_id
            or canonical_wire != wire
            or row["definition_digest"] != digest
            or row["schema_version"] != TRAINING_DEFINITION_SCHEMA_VERSION
        ):
            raise sqlite3.DatabaseError("stored training definition identity does not match")
        return definition

    def list_training_definitions(self, *, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT d.exercise_id, d.schema_version, d.definition_digest,
                   d.title, d.source_id, d.tags_json, d.created_at, d.updated_at,
                   p.status, p.current_fen, p.attempts, p.mistakes,
                   p.hints_used, p.updated_at AS progress_updated_at
            FROM training_definitions d
            LEFT JOIN training_progress p ON p.exercise_id=d.exercise_id
            ORDER BY d.title COLLATE NOCASE, d.exercise_id LIMIT ?
            """,
            (_bounded_limit(limit),),
        ).fetchall()
        return [dict(row) for row in rows]

    def save_training_progress(self, session: ExerciseSession) -> None:
        if not isinstance(session, ExerciseSession):
            raise TypeError("session must be an ExerciseSession")
        self.save_training_definition(session.definition)
        snapshot = session.snapshot()
        ExerciseSession.restore(session.definition, snapshot)
        wire = _canonical_json(
            snapshot,
            limit=MAX_TRAINING_SNAPSHOT_CHARACTERS,
            name="training snapshot",
        )
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO training_progress(
                    exercise_id, snapshot_schema_version, status, current_fen,
                    attempts, mistakes, hints_used, snapshot_json, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(exercise_id) DO UPDATE SET
                    snapshot_schema_version=excluded.snapshot_schema_version,
                    status=excluded.status,
                    current_fen=excluded.current_fen,
                    attempts=excluded.attempts,
                    mistakes=excluded.mistakes,
                    hints_used=excluded.hints_used,
                    snapshot_json=excluded.snapshot_json,
                    updated_at=excluded.updated_at
                """,
                (
                    session.definition.exercise_id,
                    TRAINING_SNAPSHOT_SCHEMA_VERSION,
                    session.status.value,
                    session.position_fen,
                    session.attempts,
                    session.mistakes,
                    session.hints_used,
                    wire,
                    self._now(),
                ),
            )

    def load_training_session(self, exercise_id: str) -> ExerciseSession:
        definition = self.get_training_definition(exercise_id)
        row = self.conn.execute(
            "SELECT * FROM training_progress WHERE exercise_id=?",
            (definition.exercise_id,),
        ).fetchone()
        if row is None:
            return ExerciseSession(definition)
        wire = row["snapshot_json"]
        try:
            if type(wire) is not str or len(wire) > MAX_TRAINING_SNAPSHOT_CHARACTERS:
                raise ValueError("snapshot payload size is invalid")
            snapshot = json.loads(wire)
            session = ExerciseSession.restore(definition, snapshot)
            canonical_wire = _canonical_json(
                session.snapshot(),
                limit=MAX_TRAINING_SNAPSHOT_CHARACTERS,
                name="stored training snapshot",
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise sqlite3.DatabaseError("stored training progress failed validation") from exc
        if (
            wire != canonical_wire
            or row["snapshot_schema_version"] != TRAINING_SNAPSHOT_SCHEMA_VERSION
            or row["status"] != session.status.value
            or row["current_fen"] != session.position_fen
            or row["attempts"] != session.attempts
            or row["mistakes"] != session.mistakes
            or row["hints_used"] != session.hints_used
        ):
            raise sqlite3.DatabaseError("stored training progress summary does not match")
        return session

    def list_training_progress(self, *, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT p.exercise_id, d.title, d.source_id, d.tags_json,
                   p.status, p.current_fen, p.attempts, p.mistakes,
                   p.hints_used, p.updated_at
            FROM training_progress p
            JOIN training_definitions d ON d.exercise_id=p.exercise_id
            ORDER BY p.updated_at DESC, p.exercise_id LIMIT ?
            """,
            (_bounded_limit(limit),),
        ).fetchall()
        return [dict(row) for row in rows]

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
        player = _require_optional_text(player, "player")
        event = _require_optional_text(event, "event")
        annotator = _require_optional_text(annotator, "annotator")
        eco = _require_optional_text(eco, "eco")
        opening = _require_optional_text(opening, "opening")
        result = _require_optional_text(result, "result")
        date_from = _require_optional_text(date_from, "date_from")
        date_to = _require_optional_text(date_to, "date_to")
        source_name = _require_optional_text(source_name, "source_name")
        provenance_id = _require_optional_text(provenance_id, "provenance_id")
        record_digest = _require_optional_text(record_digest, "record_digest")
        tree_digest = _require_optional_text(tree_digest, "tree_digest")
        if source_id is not None:
            source_id = _require_id(source_id, "source_id")
        offset = _require_exact_int(offset, "offset", minimum=0)

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
        if annotator:
            clauses.append("an.name LIKE ? ESCAPE '!' COLLATE NOCASE")
            params.append(f"%{escape_like_literal(annotator)}%")
        if eco:
            clauses.append("g.eco LIKE ? ESCAPE '!' COLLATE NOCASE")
            params.append(f"{escape_like_literal(eco)}%")
        if opening:
            clauses.append("g.opening LIKE ? ESCAPE '!' COLLATE NOCASE")
            params.append(f"%{escape_like_literal(opening)}%")
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
            params.append(source_id)
        if source_name:
            clauses.append("s.source_name LIKE ? ESCAPE '!' COLLATE NOCASE")
            params.append(f"%{escape_like_literal(source_name)}%")
        if provenance_id:
            clauses.append("s.provenance_id=?")
            params.append(_require_identity_text(provenance_id, "provenance_id"))
        if record_digest:
            clauses.append("c.record_digest=?")
            params.append(_require_digest(record_digest, "record_digest"))
        if tree_digest:
            clauses.append("c.tree_digest=?")
            params.append(_require_digest(tree_digest, "tree_digest"))

        sql = """
            SELECT g.*, s.source_name, s.source_format, s.sha256,
                   s.provenance_id, wp.name AS white_player,
                   bp.name AS black_player, ev.name AS normalized_event,
                   an.name AS annotator, op.eco AS normalized_eco,
                   op.name AS normalized_opening, c.catalog_id,
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
        params.extend([_bounded_limit(limit), offset])
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def catalog_counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in (
            "sources", "games", "players", "events", "annotators", "openings",
            "positions", "import_attempts", "game_catalog", "catalog_issues",
            "schema_migrations", "books", "book_bookmarks",
            "training_definitions", "training_progress",
        ):
            result[table] = int(
                self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
        return result

    def record_position(self, game_id: int, ply: int, fen: str) -> None:
        game_id = _require_id(game_id, "game_id")
        ply = _require_exact_int(ply, "ply", minimum=0)
        key = self.position_key(fen)
        canonical_fen = PositionState.from_fen(fen).to_fen()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO positions(game_id, ply, fen, position_key)
                VALUES(?,?,?,?)
                """,
                (game_id, ply, canonical_fen, key),
            )

    def record_positions(
        self,
        game_id: int,
        positions: Iterable[tuple[int, str]],
    ) -> None:
        game_id = _require_id(game_id, "game_id")
        try:
            snapshot = tuple(positions)
        except TypeError as exc:
            raise TypeError(
                "positions must be an iterable of (ply, fen) tuples"
            ) from exc
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
                """
                INSERT OR REPLACE INTO positions(game_id, ply, fen, position_key)
                VALUES(?,?,?,?)
                """,
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
            ORDER BY g.id, p.ply LIMIT ?
            """,
            (key, _bounded_limit(limit)),
        ).fetchall()
        return [dict(row) for row in rows]

    def integrity_report(self) -> dict[str, object]:
        quick, foreign = self._connection_integrity(self.conn)
        missing_provenance = int(
            self.conn.execute(
                "SELECT COUNT(*) FROM sources WHERE provenance_id IS NULL OR provenance_id=''"
            ).fetchone()[0]
        )
        catalog_issues = int(
            self.conn.execute("SELECT COUNT(*) FROM catalog_issues").fetchone()[0]
        )
        return {
            "ok": quick == ("ok",) and not foreign and missing_provenance == 0,
            "quick_check": list(quick),
            "foreign_key_errors": list(foreign),
            "schema_version": self.schema_version,
            "missing_provenance": missing_provenance,
            "catalog_issue_count": catalog_issues,
        }

    @staticmethod
    def _validate_plain_database(path: Path) -> dict[str, object]:
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(path)
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try:
            connection.row_factory = sqlite3.Row
            quick, foreign = AcsDatabase._connection_integrity(connection)
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            return {
                "ok": quick == ("ok",) and not foreign,
                "quick_check": list(quick),
                "foreign_key_errors": list(foreign),
                "schema_version": version,
                "supported": version <= ACSDB_SCHEMA_VERSION,
            }
        finally:
            connection.close()

    def backup_to(self, destination: str | Path) -> Path:
        if not isinstance(destination, (str, Path)):
            raise TypeError("destination must be text or Path")
        report = self.integrity_report()
        if not report["ok"]:
            raise sqlite3.DatabaseError(f"ACSDB integrity check failed: {report}")
        destination_path = Path(destination)
        if destination_path.exists():
            raise FileExistsError(destination_path)
        if (
            self.path != ":memory:"
            and destination_path.resolve() == Path(self.path).resolve()
        ):
            raise ValueError("backup destination must differ from the source database")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination_path.name}.",
            suffix=".partial",
            dir=str(destination_path.parent),
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            target = sqlite3.connect(str(temporary_path))
            try:
                self.conn.backup(target)
                target.commit()
            finally:
                target.close()
            copied = self._validate_plain_database(temporary_path)
            if not copied["ok"] or copied["schema_version"] != self.schema_version:
                raise sqlite3.DatabaseError("ACSDB backup validation failed")
            os.replace(temporary_path, destination_path)
        except Exception:
            if temporary_path.exists():
                temporary_path.unlink()
            raise
        self.last_recovery = RecoveryEvidence(
            source_path=Path(self.path),
            destination_path=destination_path,
            schema_version=self.schema_version,
            quick_check=tuple(str(item) for item in copied["quick_check"]),
            created_at=self._now(),
        )
        return destination_path

    def recover_copy(self, destination: str | Path) -> Path:
        """Create a validated recovery copy using SQLite's online backup API."""
        return self.backup_to(destination)

    @staticmethod
    def validate_database(path: str | Path) -> dict[str, object]:
        if not isinstance(path, (str, Path)):
            raise TypeError("path must be text or Path")
        return AcsDatabase._validate_plain_database(Path(path))
