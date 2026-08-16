from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .lesson_plan import ClassroomPairing

PAIRING_SCHEMA_VERSION = 1


class LessonSessionStorageError(RuntimeError):
    pass


class LessonSessionConflictError(LessonSessionStorageError):
    pass


@dataclass(frozen=True)
class PairingSessionRecord:
    pairing_id: str
    lesson_id: str
    classroom_session_id: str
    game_session_id: str
    white_participant_id: str
    black_participant_id: str
    base_seconds: int
    increment_seconds: int
    start_fen: str | None
    ordinal: int


@dataclass(frozen=True)
class PairingSessionBatch:
    batch_id: str
    lesson_id: str
    classroom_session_id: str
    records: tuple[PairingSessionRecord, ...]


class LessonSessionSQLiteStore:
    """Persistence for classroom pairing/session orchestration.

    The store owns identities and reconnect state only. It deliberately does not
    own Board objects, chess legality, clocks, moves, PGN, or audio. A canonical
    game/session service can consume ``game_session_id`` later.

    This schema is independently versioned so it can safely share the same
    SQLite file with ``LessonSQLiteStore`` without mutating its lesson schema.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def _migrate(self) -> None:
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS classroom_schema_meta "
                "(key TEXT PRIMARY KEY, value INTEGER NOT NULL)"
            )
            row = db.execute(
                "SELECT value FROM classroom_schema_meta WHERE key='pairing_schema_version'"
            ).fetchone()
            version = int(row[0]) if row else 0
            if version > PAIRING_SCHEMA_VERSION:
                raise LessonSessionStorageError(
                    f"unsupported classroom pairing schema {version}"
                )
            if version < 1:
                self._migration_v1(db)
                db.execute(
                    "INSERT INTO classroom_schema_meta(key,value) VALUES('pairing_schema_version',1) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
                )

    @staticmethod
    def _migration_v1(db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE pairing_batches(
                batch_id TEXT PRIMARY KEY,
                lesson_id TEXT NOT NULL,
                classroom_session_id TEXT NOT NULL,
                pairing_count INTEGER NOT NULL CHECK(pairing_count >= 0)
            );
            CREATE TABLE pairing_sessions(
                batch_id TEXT NOT NULL REFERENCES pairing_batches(batch_id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                pairing_id TEXT NOT NULL,
                lesson_id TEXT NOT NULL,
                classroom_session_id TEXT NOT NULL,
                game_session_id TEXT NOT NULL UNIQUE,
                white_participant_id TEXT NOT NULL,
                black_participant_id TEXT NOT NULL,
                base_seconds INTEGER NOT NULL CHECK(base_seconds >= 0),
                increment_seconds INTEGER NOT NULL CHECK(increment_seconds >= 0),
                start_fen TEXT,
                PRIMARY KEY(batch_id, ordinal),
                UNIQUE(classroom_session_id, pairing_id),
                CHECK(white_participant_id <> black_participant_id)
            );
            CREATE INDEX idx_pairing_session_order
                ON pairing_sessions(classroom_session_id, ordinal);
            CREATE INDEX idx_pairing_game_session
                ON pairing_sessions(game_session_id);
            """
        )

    @staticmethod
    def _require_id(value: object, field_name: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError(f"{field_name} must not be empty")
        return text

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> PairingSessionRecord:
        return PairingSessionRecord(
            row["pairing_id"],
            row["lesson_id"],
            row["classroom_session_id"],
            row["game_session_id"],
            row["white_participant_id"],
            row["black_participant_id"],
            int(row["base_seconds"]),
            int(row["increment_seconds"]),
            row["start_fen"],
            int(row["ordinal"]),
        )

    def record_pairing_batch(
        self,
        *,
        batch_id: str,
        lesson_id: str,
        classroom_session_id: str,
        pairings: Iterable[ClassroomPairing],
        game_session_ids: Iterable[str],
    ) -> PairingSessionBatch:
        batch_id = self._require_id(batch_id, "batch_id")
        lesson_id = self._require_id(lesson_id, "lesson_id")
        classroom_session_id = self._require_id(
            classroom_session_id, "classroom_session_id"
        )
        pairing_tuple = tuple(pairings)
        game_ids = tuple(
            self._require_id(value, "game_session_id") for value in game_session_ids
        )
        if len(pairing_tuple) != len(game_ids):
            raise ValueError("pairings and game_session_ids must have equal length")
        if len(set(game_ids)) != len(game_ids):
            raise ValueError("game_session_ids must be unique")
        pairing_ids = tuple(pairing.pairing_id for pairing in pairing_tuple)
        if len(set(pairing_ids)) != len(pairing_ids):
            raise ValueError("pairing_ids must be unique within a batch")

        requested = tuple(
            PairingSessionRecord(
                pairing.pairing_id,
                lesson_id,
                classroom_session_id,
                game_ids[index],
                pairing.white_participant_id,
                pairing.black_participant_id,
                pairing.base_seconds,
                pairing.increment_seconds,
                pairing.start_fen,
                index,
            )
            for index, pairing in enumerate(pairing_tuple)
        )

        with self._connect() as db:
            existing_header = db.execute(
                "SELECT * FROM pairing_batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
            if existing_header is not None:
                header = (
                    existing_header["lesson_id"],
                    existing_header["classroom_session_id"],
                    int(existing_header["pairing_count"]),
                )
                expected_header = (lesson_id, classroom_session_id, len(requested))
                if header != expected_header:
                    raise LessonSessionConflictError(
                        f"pairing batch identity reused with different payload: {batch_id}"
                    )
                stored = tuple(
                    self._record_from_row(row)
                    for row in db.execute(
                        "SELECT * FROM pairing_sessions WHERE batch_id=? ORDER BY ordinal",
                        (batch_id,),
                    )
                )
                if len(stored) != len(requested):
                    raise LessonSessionStorageError(
                        f"pairing batch is incomplete: {batch_id}"
                    )
                if stored != requested:
                    raise LessonSessionConflictError(
                        f"pairing batch identity reused with different pairings: {batch_id}"
                    )
                return PairingSessionBatch(
                    batch_id, lesson_id, classroom_session_id, stored
                )

            try:
                db.execute(
                    "INSERT INTO pairing_batches VALUES(?,?,?,?)",
                    (batch_id, lesson_id, classroom_session_id, len(requested)),
                )
                db.executemany(
                    "INSERT INTO pairing_sessions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            batch_id,
                            record.ordinal,
                            record.pairing_id,
                            record.lesson_id,
                            record.classroom_session_id,
                            record.game_session_id,
                            record.white_participant_id,
                            record.black_participant_id,
                            record.base_seconds,
                            record.increment_seconds,
                            record.start_fen,
                        )
                        for record in requested
                    ],
                )
            except sqlite3.IntegrityError as exc:
                raise LessonSessionConflictError(
                    "pairing batch conflicts with existing classroom/game identity"
                ) from exc
        return PairingSessionBatch(batch_id, lesson_id, classroom_session_id, requested)

    def load_pairing_batch(self, batch_id: str) -> PairingSessionBatch | None:
        batch_id = self._require_id(batch_id, "batch_id")
        with self._connect() as db:
            header = db.execute(
                "SELECT * FROM pairing_batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
            if header is None:
                return None
            records = tuple(
                self._record_from_row(row)
                for row in db.execute(
                    "SELECT * FROM pairing_sessions WHERE batch_id=? ORDER BY ordinal",
                    (batch_id,),
                )
            )
            if len(records) != int(header["pairing_count"]):
                raise LessonSessionStorageError(
                    f"pairing batch is incomplete: {batch_id}"
                )
        return PairingSessionBatch(
            batch_id,
            header["lesson_id"],
            header["classroom_session_id"],
            records,
        )

    def session_pairings(
        self, classroom_session_id: str
    ) -> tuple[PairingSessionRecord, ...]:
        classroom_session_id = self._require_id(
            classroom_session_id, "classroom_session_id"
        )
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM pairing_sessions WHERE classroom_session_id=? "
                "ORDER BY batch_id, ordinal",
                (classroom_session_id,),
            ).fetchall()
        return tuple(self._record_from_row(row) for row in rows)

    def find_by_game_session(self, game_session_id: str) -> PairingSessionRecord | None:
        game_session_id = self._require_id(game_session_id, "game_session_id")
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM pairing_sessions WHERE game_session_id=?",
                (game_session_id,),
            ).fetchone()
        return None if row is None else self._record_from_row(row)

    def integrity_check(self) -> None:
        with self._connect() as db:
            result = db.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise LessonSessionStorageError("SQLite integrity check failed")
