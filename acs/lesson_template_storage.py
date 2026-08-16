from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

from .child_coaching_ui import LessonTemplate, LessonTemplateBlock
from .lesson_plan import LessonItemKind

TEMPLATE_SCHEMA_VERSION = 1


class LessonTemplateStorageError(RuntimeError):
    pass


class LessonTemplateConflictError(LessonTemplateStorageError):
    pass


class RotationRoundState(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"


@dataclass(frozen=True)
class LessonTemplatePreset:
    template: LessonTemplate
    level: str
    is_preset: bool = False

    def __post_init__(self) -> None:
        level = str(self.level).strip()
        if not level:
            raise ValueError("lesson template level must not be empty")
        object.__setattr__(self, "level", level)


@dataclass(frozen=True)
class TemplateRevision:
    template_id: str
    revision: int


@dataclass(frozen=True)
class RotationRoundRecord:
    round_id: str
    classroom_session_id: str
    round_number: int
    label: str
    state: RotationRoundState = RotationRoundState.PLANNED
    pairing_ids: tuple[str, ...] = ()
    deployment_batch_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "round_id", _stable_id(self.round_id, "round_id"))
        object.__setattr__(
            self,
            "classroom_session_id",
            _stable_id(self.classroom_session_id, "classroom_session_id"),
        )
        if isinstance(self.round_number, bool) or int(self.round_number) < 1:
            raise ValueError("round_number must be positive")
        object.__setattr__(self, "round_number", int(self.round_number))
        label = str(self.label).strip()
        if not label:
            raise ValueError("rotation round label must not be empty")
        object.__setattr__(self, "label", label)
        pairings = tuple(_stable_id(value, "pairing_id") for value in self.pairing_ids)
        deployments = tuple(
            _stable_id(value, "deployment_batch_id") for value in self.deployment_batch_ids
        )
        if len(set(pairings)) != len(pairings):
            raise ValueError("rotation round contains duplicate pairing IDs")
        if len(set(deployments)) != len(deployments):
            raise ValueError("rotation round contains duplicate deployment batch IDs")
        object.__setattr__(self, "pairing_ids", pairings)
        object.__setattr__(self, "deployment_batch_ids", deployments)


@dataclass(frozen=True)
class RotationRevision:
    round_id: str
    revision: int


class LessonTemplateSQLiteStore:
    """Durable teaching-data persistence that composes with LessonSQLiteStore.

    This store owns editable lesson-template metadata and classroom rotation-round
    orchestration only. It never owns a chess Board, legality, move history, media,
    chat, or analytics. Stable references point at pairings/deployment batches
    persisted by the existing lesson/session stores.
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
                "CREATE TABLE IF NOT EXISTS lesson_template_schema_meta "
                "(key TEXT PRIMARY KEY, value INTEGER NOT NULL)"
            )
            row = db.execute(
                "SELECT value FROM lesson_template_schema_meta WHERE key='schema_version'"
            ).fetchone()
            version = int(row[0]) if row else 0
            if version > TEMPLATE_SCHEMA_VERSION:
                raise LessonTemplateStorageError(
                    f"unsupported lesson-template database schema {version}"
                )
            if version < 1:
                self._migration_v1(db)
                db.execute(
                    "INSERT INTO lesson_template_schema_meta(key,value) VALUES('schema_version',1) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
                )

    @staticmethod
    def _migration_v1(db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE lesson_templates(
                template_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                age_band TEXT NOT NULL,
                level TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision >= 1),
                is_preset INTEGER NOT NULL CHECK(is_preset IN (0,1))
            );
            CREATE TABLE lesson_template_blocks(
                template_id TEXT NOT NULL REFERENCES lesson_templates(template_id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                block_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL CHECK(duration_minutes > 0),
                notation_required INTEGER NOT NULL CHECK(notation_required IN (0,1)),
                PRIMARY KEY(template_id, block_id),
                UNIQUE(template_id, ordinal)
            );
            CREATE TABLE rotation_rounds(
                round_id TEXT PRIMARY KEY,
                classroom_session_id TEXT NOT NULL,
                round_number INTEGER NOT NULL CHECK(round_number >= 1),
                label TEXT NOT NULL,
                state TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision >= 1),
                UNIQUE(classroom_session_id, round_number)
            );
            CREATE TABLE rotation_round_pairings(
                round_id TEXT NOT NULL REFERENCES rotation_rounds(round_id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                pairing_id TEXT NOT NULL,
                PRIMARY KEY(round_id, ordinal),
                UNIQUE(round_id, pairing_id)
            );
            CREATE TABLE rotation_round_deployments(
                round_id TEXT NOT NULL REFERENCES rotation_rounds(round_id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                deployment_batch_id TEXT NOT NULL,
                PRIMARY KEY(round_id, ordinal),
                UNIQUE(round_id, deployment_batch_id)
            );
            CREATE INDEX idx_rotation_round_session
                ON rotation_rounds(classroom_session_id, round_number);
            """
        )

    def ensure_presets(self, presets: Iterable[LessonTemplatePreset]) -> tuple[TemplateRevision, ...]:
        revisions: list[TemplateRevision] = []
        with self._connect() as db:
            for preset in presets:
                template_id = _stable_id(preset.template.template_id, "template_id")
                row = db.execute(
                    "SELECT revision FROM lesson_templates WHERE template_id=?", (template_id,)
                ).fetchone()
                if row is None:
                    self._insert_template(db, preset, revision=1)
                    revisions.append(TemplateRevision(template_id, 1))
                else:
                    revisions.append(TemplateRevision(template_id, int(row[0])))
        return tuple(revisions)

    def save_new_template(self, preset: LessonTemplatePreset) -> TemplateRevision:
        template_id = _stable_id(preset.template.template_id, "template_id")
        try:
            with self._connect() as db:
                self._insert_template(db, preset, revision=1)
        except sqlite3.IntegrityError as exc:
            raise LessonTemplateConflictError(f"lesson template already exists: {template_id}") from exc
        return TemplateRevision(template_id, 1)

    def update_template(
        self, preset: LessonTemplatePreset, *, expected_revision: int
    ) -> TemplateRevision:
        if isinstance(expected_revision, bool) or int(expected_revision) < 1:
            raise ValueError("expected_revision must be positive")
        template_id = _stable_id(preset.template.template_id, "template_id")
        with self._connect() as db:
            row = db.execute(
                "SELECT revision FROM lesson_templates WHERE template_id=?", (template_id,)
            ).fetchone()
            if row is None:
                raise LessonTemplateStorageError(f"unknown lesson template: {template_id}")
            current = int(row[0])
            if current != int(expected_revision):
                raise LessonTemplateConflictError(
                    f"lesson template revision conflict: expected {expected_revision}, found {current}"
                )
            revision = current + 1
            db.execute(
                "UPDATE lesson_templates SET title=?,age_band=?,level=?,revision=?,is_preset=? "
                "WHERE template_id=?",
                (
                    preset.template.title,
                    preset.template.age_band,
                    preset.level,
                    revision,
                    int(preset.is_preset),
                    template_id,
                ),
            )
            db.execute("DELETE FROM lesson_template_blocks WHERE template_id=?", (template_id,))
            self._insert_blocks(db, preset.template)
        return TemplateRevision(template_id, revision)

    @staticmethod
    def _insert_template(
        db: sqlite3.Connection, preset: LessonTemplatePreset, *, revision: int
    ) -> None:
        template = preset.template
        template_id = _stable_id(template.template_id, "template_id")
        title = str(template.title).strip()
        age_band = str(template.age_band).strip()
        if not title or not age_band or not template.blocks:
            raise ValueError("lesson template requires title, age band and at least one block")
        db.execute(
            "INSERT INTO lesson_templates(template_id,title,age_band,level,revision,is_preset) "
            "VALUES(?,?,?,?,?,?)",
            (template_id, title, age_band, preset.level, revision, int(preset.is_preset)),
        )
        LessonTemplateSQLiteStore._insert_blocks(db, template)

    @staticmethod
    def _insert_blocks(db: sqlite3.Connection, template: LessonTemplate) -> None:
        rows = []
        seen: set[str] = set()
        for ordinal, block in enumerate(template.blocks):
            block_id = _stable_id(block.block_id, "block_id")
            if block_id in seen:
                raise ValueError("lesson template contains duplicate block IDs")
            seen.add(block_id)
            rows.append(
                (
                    _stable_id(template.template_id, "template_id"),
                    ordinal,
                    block_id,
                    block.kind.value,
                    block.title,
                    block.duration_minutes,
                    int(block.notation_required),
                )
            )
        db.executemany(
            "INSERT INTO lesson_template_blocks VALUES(?,?,?,?,?,?,?)",
            rows,
        )

    def load_template(self, template_id: str) -> tuple[LessonTemplatePreset, TemplateRevision]:
        template_id = _stable_id(template_id, "template_id")
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM lesson_templates WHERE template_id=?", (template_id,)
            ).fetchone()
            if row is None:
                raise LessonTemplateStorageError(f"unknown lesson template: {template_id}")
            blocks = tuple(
                LessonTemplateBlock(
                    block["block_id"],
                    LessonItemKind(block["kind"]),
                    block["title"],
                    int(block["duration_minutes"]),
                    bool(block["notation_required"]),
                )
                for block in db.execute(
                    "SELECT * FROM lesson_template_blocks WHERE template_id=? ORDER BY ordinal",
                    (template_id,),
                )
            )
        preset = LessonTemplatePreset(
            LessonTemplate(row["template_id"], row["title"], row["age_band"], blocks),
            row["level"],
            bool(row["is_preset"]),
        )
        return preset, TemplateRevision(template_id, int(row["revision"]))

    def save_new_rotation(self, record: RotationRoundRecord) -> RotationRevision:
        try:
            with self._connect() as db:
                self._insert_rotation(db, record, revision=1)
        except sqlite3.IntegrityError as exc:
            raise LessonTemplateConflictError(
                f"rotation round conflicts with existing identity/order: {record.round_id}"
            ) from exc
        return RotationRevision(record.round_id, 1)

    def update_rotation(
        self, record: RotationRoundRecord, *, expected_revision: int
    ) -> RotationRevision:
        if isinstance(expected_revision, bool) or int(expected_revision) < 1:
            raise ValueError("expected_revision must be positive")
        with self._connect() as db:
            row = db.execute(
                "SELECT revision,classroom_session_id,round_number FROM rotation_rounds WHERE round_id=?",
                (record.round_id,),
            ).fetchone()
            if row is None:
                raise LessonTemplateStorageError(f"unknown rotation round: {record.round_id}")
            current = int(row["revision"])
            if current != int(expected_revision):
                raise LessonTemplateConflictError(
                    f"rotation round revision conflict: expected {expected_revision}, found {current}"
                )
            if row["classroom_session_id"] != record.classroom_session_id or int(row["round_number"]) != record.round_number:
                raise LessonTemplateConflictError("rotation round identity/order cannot be rewritten")
            revision = current + 1
            db.execute(
                "UPDATE rotation_rounds SET label=?,state=?,revision=? WHERE round_id=?",
                (record.label, record.state.value, revision, record.round_id),
            )
            db.execute("DELETE FROM rotation_round_pairings WHERE round_id=?", (record.round_id,))
            db.execute("DELETE FROM rotation_round_deployments WHERE round_id=?", (record.round_id,))
            self._insert_rotation_children(db, record)
        return RotationRevision(record.round_id, revision)

    @staticmethod
    def _insert_rotation(
        db: sqlite3.Connection, record: RotationRoundRecord, *, revision: int
    ) -> None:
        db.execute(
            "INSERT INTO rotation_rounds(round_id,classroom_session_id,round_number,label,state,revision) "
            "VALUES(?,?,?,?,?,?)",
            (
                record.round_id,
                record.classroom_session_id,
                record.round_number,
                record.label,
                record.state.value,
                revision,
            ),
        )
        LessonTemplateSQLiteStore._insert_rotation_children(db, record)

    @staticmethod
    def _insert_rotation_children(db: sqlite3.Connection, record: RotationRoundRecord) -> None:
        db.executemany(
            "INSERT INTO rotation_round_pairings VALUES(?,?,?)",
            [(record.round_id, index, value) for index, value in enumerate(record.pairing_ids)],
        )
        db.executemany(
            "INSERT INTO rotation_round_deployments VALUES(?,?,?)",
            [
                (record.round_id, index, value)
                for index, value in enumerate(record.deployment_batch_ids)
            ],
        )

    def load_rotation(self, round_id: str) -> tuple[RotationRoundRecord, RotationRevision]:
        round_id = _stable_id(round_id, "round_id")
        with self._connect() as db:
            row = db.execute("SELECT * FROM rotation_rounds WHERE round_id=?", (round_id,)).fetchone()
            if row is None:
                raise LessonTemplateStorageError(f"unknown rotation round: {round_id}")
            pairings = tuple(
                item["pairing_id"]
                for item in db.execute(
                    "SELECT pairing_id FROM rotation_round_pairings WHERE round_id=? ORDER BY ordinal",
                    (round_id,),
                )
            )
            deployments = tuple(
                item["deployment_batch_id"]
                for item in db.execute(
                    "SELECT deployment_batch_id FROM rotation_round_deployments WHERE round_id=? ORDER BY ordinal",
                    (round_id,),
                )
            )
        record = RotationRoundRecord(
            row["round_id"],
            row["classroom_session_id"],
            int(row["round_number"]),
            row["label"],
            RotationRoundState(row["state"]),
            pairings,
            deployments,
        )
        return record, RotationRevision(round_id, int(row["revision"]))

    def list_rotations(self, classroom_session_id: str) -> tuple[RotationRoundRecord, ...]:
        classroom_session_id = _stable_id(classroom_session_id, "classroom_session_id")
        with self._connect() as db:
            ids = tuple(
                row["round_id"]
                for row in db.execute(
                    "SELECT round_id FROM rotation_rounds WHERE classroom_session_id=? ORDER BY round_number",
                    (classroom_session_id,),
                )
            )
        return tuple(self.load_rotation(round_id)[0] for round_id in ids)


def _stable_id(value: object, field_name: str) -> str:
    text = str(value).strip().lower()
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789._-"
    if not text or any(ch not in allowed for ch in text):
        raise ValueError(f"{field_name} must be a stable lowercase id")
    return text
