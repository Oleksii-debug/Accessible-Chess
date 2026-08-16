from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .lesson_plan import (
    AssignmentTarget,
    LessonItem,
    LessonItemKind,
    LessonPlan,
    LessonPosition,
    PositionAssignment,
)
from .local_profile import LocalProfile
from .usage_statistics import UsageStatisticsSnapshot

SCHEMA_VERSION = 2
FenValidator = Callable[[str], None]


class LessonStorageError(RuntimeError):
    pass


class LessonConflictError(LessonStorageError):
    pass


@dataclass(frozen=True)
class LessonRevision:
    lesson_id: str
    revision: int


@dataclass(frozen=True)
class DeploymentRecord:
    deployment_id: str
    lesson_id: str
    assignment_id: str | None
    position_id: str
    target_kind: str
    target_id: str
    session_id: str
    sequence_no: int


@dataclass(frozen=True)
class DeploymentTarget:
    target_kind: str
    target_id: str

    def __post_init__(self) -> None:
        if not self.target_kind.strip():
            raise ValueError("target_kind must not be empty")
        if not self.target_id.strip():
            raise ValueError("target_id must not be empty")


@dataclass(frozen=True)
class DeploymentBatch:
    batch_id: str
    lesson_id: str
    assignment_id: str | None
    position_id: str
    session_id: str
    first_sequence_no: int
    records: tuple[DeploymentRecord, ...]


class LessonSQLiteStore:
    """Versioned local persistence for lesson/classroom data.

    FEN legality is deliberately delegated to the shared Core validator supplied
    by the application boundary. This layer stores the accepted FEN text exactly
    and never uploads lesson content or uses it as telemetry.
    """

    def __init__(self, path: str | Path, *, fen_validator: FenValidator) -> None:
        if not callable(fen_validator):
            raise TypeError("fen_validator must be callable")
        self.path = Path(path)
        self._fen_validator = fen_validator
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _set_schema_version(db: sqlite3.Connection, version: int) -> None:
        db.execute(
            "INSERT INTO schema_meta(key,value) VALUES('schema_version',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (version,),
        )

    def _migrate(self) -> None:
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
            row = db.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
            version = int(row[0]) if row else 0
            if version > SCHEMA_VERSION:
                raise LessonStorageError(f"unsupported lesson database schema {version}")
            if version < 1:
                self._migration_v1(db)
                version = 1
                self._set_schema_version(db, version)
            if version < 2:
                self._migration_v2(db)
                version = 2
                self._set_schema_version(db, version)

    @staticmethod
    def _migration_v1(db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE lessons(
                lesson_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                age_band TEXT NOT NULL,
                level TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision >= 1)
            );
            CREATE TABLE lesson_positions(
                lesson_id TEXT NOT NULL REFERENCES lessons(lesson_id) ON DELETE CASCADE,
                position_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                title TEXT NOT NULL,
                fen TEXT NOT NULL,
                student_prompt TEXT NOT NULL,
                teacher_notes TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                PRIMARY KEY(lesson_id, position_id),
                UNIQUE(lesson_id, ordinal)
            );
            CREATE TABLE lesson_items(
                lesson_id TEXT NOT NULL REFERENCES lessons(lesson_id) ON DELETE CASCADE,
                item_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                position_id TEXT,
                notes TEXT NOT NULL,
                PRIMARY KEY(lesson_id, item_id),
                UNIQUE(lesson_id, ordinal)
            );
            CREATE TABLE position_assignments(
                lesson_id TEXT NOT NULL REFERENCES lessons(lesson_id) ON DELETE CASCADE,
                assignment_id TEXT NOT NULL,
                position_id TEXT NOT NULL,
                target TEXT NOT NULL,
                participant_ids_json TEXT NOT NULL,
                group_id TEXT,
                PRIMARY KEY(lesson_id, assignment_id)
            );
            CREATE TABLE deployments(
                deployment_id TEXT PRIMARY KEY,
                lesson_id TEXT NOT NULL,
                assignment_id TEXT,
                position_id TEXT NOT NULL,
                target_kind TEXT NOT NULL,
                target_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                sequence_no INTEGER NOT NULL,
                UNIQUE(session_id, sequence_no),
                UNIQUE(session_id, assignment_id, target_kind, target_id)
            );
            CREATE INDEX idx_items_order ON lesson_items(lesson_id, ordinal);
            CREATE INDEX idx_positions_order ON lesson_positions(lesson_id, ordinal);
            CREATE INDEX idx_deployments_timeline ON deployments(session_id, sequence_no);
            CREATE TABLE local_profile(
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                installation_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                generated_alias INTEGER NOT NULL,
                schema_version INTEGER NOT NULL
            );
            CREATE TABLE aggregate_usage(
                installation_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            );
            """
        )

    @staticmethod
    def _migration_v2(db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE deployment_batches(
                batch_id TEXT PRIMARY KEY,
                lesson_id TEXT NOT NULL REFERENCES lessons(lesson_id) ON DELETE CASCADE,
                assignment_id TEXT,
                position_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                first_sequence_no INTEGER NOT NULL CHECK(first_sequence_no >= 0),
                target_count INTEGER NOT NULL CHECK(target_count > 0)
            );
            CREATE TABLE deployment_batch_targets(
                batch_id TEXT NOT NULL REFERENCES deployment_batches(batch_id) ON DELETE CASCADE,
                target_ordinal INTEGER NOT NULL CHECK(target_ordinal >= 0),
                target_kind TEXT NOT NULL,
                target_id TEXT NOT NULL,
                deployment_id TEXT NOT NULL UNIQUE REFERENCES deployments(deployment_id) ON DELETE CASCADE,
                PRIMARY KEY(batch_id, target_ordinal),
                UNIQUE(batch_id, target_kind, target_id)
            );
            CREATE INDEX idx_deployment_batch_session ON deployment_batches(session_id, first_sequence_no);
            """
        )

    def save_new(self, plan: LessonPlan) -> LessonRevision:
        self._validate_fens(plan.positions)
        try:
            with self._connect() as db:
                self._insert_plan(db, plan, revision=1)
        except sqlite3.IntegrityError as exc:
            raise LessonConflictError(f"lesson already exists: {plan.lesson_id}") from exc
        return LessonRevision(plan.lesson_id, 1)

    def update(self, plan: LessonPlan, *, expected_revision: int) -> LessonRevision:
        self._validate_fens(plan.positions)
        if expected_revision < 1:
            raise ValueError("expected_revision must be positive")
        with self._connect() as db:
            row = db.execute("SELECT revision FROM lessons WHERE lesson_id=?", (plan.lesson_id,)).fetchone()
            if row is None:
                raise LessonStorageError(f"unknown lesson: {plan.lesson_id}")
            if int(row[0]) != expected_revision:
                raise LessonConflictError(
                    f"lesson revision conflict: expected {expected_revision}, found {int(row[0])}"
                )
            new_revision = expected_revision + 1
            db.execute("DELETE FROM lessons WHERE lesson_id=?", (plan.lesson_id,))
            self._insert_plan(db, plan, revision=new_revision)
        return LessonRevision(plan.lesson_id, new_revision)

    def _insert_plan(self, db: sqlite3.Connection, plan: LessonPlan, *, revision: int) -> None:
        db.execute(
            "INSERT INTO lessons(lesson_id,title,age_band,level,revision) VALUES(?,?,?,?,?)",
            (plan.lesson_id, plan.title, plan.age_band, plan.level, revision),
        )
        db.executemany(
            "INSERT INTO lesson_positions VALUES(?,?,?,?,?,?,?,?)",
            [
                (
                    plan.lesson_id,
                    p.position_id,
                    ordinal,
                    p.title,
                    p.fen,
                    p.prompt,
                    p.teacher_notes,
                    json.dumps(p.tags, ensure_ascii=False),
                )
                for ordinal, p in enumerate(plan.positions)
            ],
        )
        db.executemany(
            "INSERT INTO lesson_items VALUES(?,?,?,?,?,?,?,?)",
            [
                (
                    plan.lesson_id,
                    item.item_id,
                    ordinal,
                    item.kind.value,
                    item.title,
                    item.duration_minutes,
                    item.position_id,
                    item.notes,
                )
                for ordinal, item in enumerate(plan.items)
            ],
        )
        db.executemany(
            "INSERT INTO position_assignments VALUES(?,?,?,?,?,?)",
            [
                (
                    plan.lesson_id,
                    assignment.assignment_id,
                    assignment.position_id,
                    assignment.target.value,
                    json.dumps(assignment.participant_ids),
                    assignment.group_id,
                )
                for assignment in plan.assignments
            ],
        )

    def load(self, lesson_id: str) -> tuple[LessonPlan, LessonRevision]:
        with self._connect() as db:
            lesson = db.execute("SELECT * FROM lessons WHERE lesson_id=?", (lesson_id,)).fetchone()
            if lesson is None:
                raise LessonStorageError(f"unknown lesson: {lesson_id}")
            positions = tuple(
                LessonPosition(
                    row["position_id"], row["title"], row["fen"], row["student_prompt"], row["teacher_notes"],
                    tuple(json.loads(row["tags_json"])),
                )
                for row in db.execute(
                    "SELECT * FROM lesson_positions WHERE lesson_id=? ORDER BY ordinal", (lesson_id,)
                )
            )
            items = tuple(
                LessonItem(
                    row["item_id"], LessonItemKind(row["kind"]), row["title"], row["duration_minutes"],
                    row["position_id"], row["notes"],
                )
                for row in db.execute("SELECT * FROM lesson_items WHERE lesson_id=? ORDER BY ordinal", (lesson_id,))
            )
            assignments = tuple(
                PositionAssignment(
                    row["assignment_id"], row["position_id"], AssignmentTarget(row["target"]),
                    tuple(json.loads(row["participant_ids_json"])), row["group_id"],
                )
                for row in db.execute(
                    "SELECT * FROM position_assignments WHERE lesson_id=? ORDER BY rowid", (lesson_id,)
                )
            )
        plan = LessonPlan(
            lesson["lesson_id"], lesson["title"], lesson["age_band"], lesson["level"], items, positions, assignments
        )
        return plan, LessonRevision(lesson_id, int(lesson["revision"]))

    def ordered_items(self, lesson_id: str) -> tuple[LessonItem, ...]:
        return self.load(lesson_id)[0].items

    def ordered_positions(self, lesson_id: str) -> tuple[LessonPosition, ...]:
        return self.load(lesson_id)[0].positions

    def search_positions(self, query: str) -> tuple[LessonPosition, ...]:
        text = str(query).strip().casefold()
        with self._connect() as db:
            rows = db.execute("SELECT * FROM lesson_positions ORDER BY lesson_id, ordinal").fetchall()
        result = []
        for row in rows:
            tags = tuple(json.loads(row["tags_json"]))
            haystack = " ".join((row["title"], row["student_prompt"], *tags)).casefold()
            if not text or text in haystack:
                result.append(
                    LessonPosition(
                        row["position_id"], row["title"], row["fen"], row["student_prompt"],
                        row["teacher_notes"], tags,
                    )
                )
        return tuple(result)

    def record_deployment(self, record: DeploymentRecord) -> DeploymentRecord:
        if record.sequence_no < 0:
            raise ValueError("sequence_no must be non-negative")
        with self._connect() as db:
            return self._record_deployment_in_transaction(db, record)

    def _record_deployment_in_transaction(
        self, db: sqlite3.Connection, record: DeploymentRecord
    ) -> DeploymentRecord:
        existing = db.execute("SELECT * FROM deployments WHERE deployment_id=?", (record.deployment_id,)).fetchone()
        if existing is not None:
            loaded = self._deployment_from_row(existing)
            if loaded != record:
                raise LessonConflictError(f"deployment identity reused with different payload: {record.deployment_id}")
            return loaded
        try:
            db.execute(
                "INSERT INTO deployments VALUES(?,?,?,?,?,?,?,?)",
                (
                    record.deployment_id, record.lesson_id, record.assignment_id, record.position_id,
                    record.target_kind, record.target_id, record.session_id, record.sequence_no,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise LessonConflictError("deployment identity conflicts with existing timeline entry") from exc
        return record

    @staticmethod
    def _deployment_id_for_batch_target(batch_id: str, target: DeploymentTarget) -> str:
        identity = f"{batch_id}\0{target.target_kind}\0{target.target_id}".encode("utf-8")
        return f"deploy.{hashlib.sha256(identity).hexdigest()}"

    def record_deployment_batch(
        self,
        *,
        batch_id: str,
        lesson_id: str,
        assignment_id: str | None,
        position_id: str,
        session_id: str,
        targets: Iterable[DeploymentTarget],
        first_sequence_no: int,
    ) -> DeploymentBatch:
        if not batch_id.strip():
            raise ValueError("batch_id must not be empty")
        if first_sequence_no < 0:
            raise ValueError("first_sequence_no must be non-negative")
        target_tuple = tuple(targets)
        if not target_tuple:
            raise ValueError("deployment batch must contain at least one target")
        target_keys = tuple((target.target_kind, target.target_id) for target in target_tuple)
        if len(set(target_keys)) != len(target_keys):
            raise ValueError("deployment batch targets must be unique")

        requested_header = (
            lesson_id,
            assignment_id,
            position_id,
            session_id,
            first_sequence_no,
            len(target_tuple),
        )
        with self._connect() as db:
            existing = db.execute("SELECT * FROM deployment_batches WHERE batch_id=?", (batch_id,)).fetchone()
            if existing is not None:
                stored_header = (
                    existing["lesson_id"],
                    existing["assignment_id"],
                    existing["position_id"],
                    existing["session_id"],
                    int(existing["first_sequence_no"]),
                    int(existing["target_count"]),
                )
                if stored_header != requested_header:
                    raise LessonConflictError(f"deployment batch identity reused with different payload: {batch_id}")
                stored_targets = tuple(
                    DeploymentTarget(row["target_kind"], row["target_id"])
                    for row in db.execute(
                        "SELECT target_kind,target_id FROM deployment_batch_targets "
                        "WHERE batch_id=? ORDER BY target_ordinal",
                        (batch_id,),
                    )
                )
                if stored_targets != target_tuple:
                    raise LessonConflictError(f"deployment batch target order changed: {batch_id}")
                records = tuple(
                    self._deployment_from_row(row)
                    for row in db.execute(
                        "SELECT d.* FROM deployment_batch_targets bt "
                        "JOIN deployments d ON d.deployment_id=bt.deployment_id "
                        "WHERE bt.batch_id=? ORDER BY bt.target_ordinal",
                        (batch_id,),
                    )
                )
                if len(records) != len(target_tuple):
                    raise LessonStorageError(f"deployment batch is incomplete: {batch_id}")
                return DeploymentBatch(
                    batch_id, lesson_id, assignment_id, position_id, session_id, first_sequence_no, records
                )

            try:
                db.execute(
                    "INSERT INTO deployment_batches VALUES(?,?,?,?,?,?,?)",
                    requested_header[:4] + (batch_id,) if False else (
                        batch_id, lesson_id, assignment_id, position_id, session_id, first_sequence_no, len(target_tuple)
                    ),
                )
                records = []
                for ordinal, target in enumerate(target_tuple):
                    record = DeploymentRecord(
                        self._deployment_id_for_batch_target(batch_id, target),
                        lesson_id,
                        assignment_id,
                        position_id,
                        target.target_kind,
                        target.target_id,
                        session_id,
                        first_sequence_no + ordinal,
                    )
                    stored = self._record_deployment_in_transaction(db, record)
                    db.execute(
                        "INSERT INTO deployment_batch_targets VALUES(?,?,?,?,?)",
                        (batch_id, ordinal, target.target_kind, target.target_id, stored.deployment_id),
                    )
                    records.append(stored)
            except sqlite3.IntegrityError as exc:
                raise LessonConflictError(f"deployment batch conflicts with existing timeline: {batch_id}") from exc
        return DeploymentBatch(
            batch_id, lesson_id, assignment_id, position_id, session_id, first_sequence_no, tuple(records)
        )

    def load_deployment_batch(self, batch_id: str) -> DeploymentBatch | None:
        with self._connect() as db:
            batch = db.execute("SELECT * FROM deployment_batches WHERE batch_id=?", (batch_id,)).fetchone()
            if batch is None:
                return None
            records = tuple(
                self._deployment_from_row(row)
                for row in db.execute(
                    "SELECT d.* FROM deployment_batch_targets bt "
                    "JOIN deployments d ON d.deployment_id=bt.deployment_id "
                    "WHERE bt.batch_id=? ORDER BY bt.target_ordinal",
                    (batch_id,),
                )
            )
            if len(records) != int(batch["target_count"]):
                raise LessonStorageError(f"deployment batch is incomplete: {batch_id}")
        return DeploymentBatch(
            batch["batch_id"], batch["lesson_id"], batch["assignment_id"], batch["position_id"],
            batch["session_id"], int(batch["first_sequence_no"]), records,
        )

    def deployment_timeline(self, session_id: str) -> tuple[DeploymentRecord, ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM deployments WHERE session_id=? ORDER BY sequence_no", (session_id,)
            ).fetchall()
        return tuple(self._deployment_from_row(row) for row in rows)

    @staticmethod
    def _deployment_from_row(row: sqlite3.Row) -> DeploymentRecord:
        return DeploymentRecord(
            row["deployment_id"], row["lesson_id"], row["assignment_id"], row["position_id"],
            row["target_kind"], row["target_id"], row["session_id"], int(row["sequence_no"]),
        )

    def save_local_profile(self, profile: LocalProfile) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO local_profile VALUES(1,?,?,?,?) ON CONFLICT(singleton) DO UPDATE SET "
                "installation_id=excluded.installation_id,display_name=excluded.display_name,"
                "generated_alias=excluded.generated_alias,schema_version=excluded.schema_version",
                (profile.installation_id, profile.display_name, int(profile.generated_alias), profile.schema_version),
            )

    def load_local_profile(self) -> LocalProfile | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM local_profile WHERE singleton=1").fetchone()
        if row is None:
            return None
        return LocalProfile(row["installation_id"], row["display_name"], bool(row["generated_alias"]), row["schema_version"])

    def save_usage_statistics(self, snapshot: UsageStatisticsSnapshot) -> None:
        payload = json.dumps(snapshot.as_dict(), ensure_ascii=False, separators=(",", ":"))
        with self._connect() as db:
            db.execute(
                "INSERT INTO aggregate_usage(installation_id,payload_json) VALUES(?,?) "
                "ON CONFLICT(installation_id) DO UPDATE SET payload_json=excluded.payload_json",
                (snapshot.installation_id, payload),
            )

    def load_usage_statistics(self, installation_id: str) -> UsageStatisticsSnapshot | None:
        with self._connect() as db:
            row = db.execute("SELECT payload_json FROM aggregate_usage WHERE installation_id=?", (installation_id,)).fetchone()
        if row is None:
            return None
        return UsageStatisticsSnapshot.from_dict(json.loads(row[0]))

    def integrity_check(self) -> None:
        with self._connect() as db:
            result = db.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise LessonStorageError("SQLite integrity check failed")

    def _validate_fens(self, positions: Iterable[LessonPosition]) -> None:
        for position in positions:
            try:
                self._fen_validator(position.fen)
            except Exception as exc:
                raise ValueError(f"Core rejected FEN for {position.position_id}: {exc}") from exc
