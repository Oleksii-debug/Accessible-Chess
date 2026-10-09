from __future__ import annotations

"""Section 54 durable, isolated, lease-fenced book-job queue.

Standalone adapter: the canonical app must supply a trusted user-data DB path.
No source book bytes, API keys, user text, network requests or output artifacts
are stored here. SQLite transactions fence stale workers and survive restarts.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Literal

from .format_factory_policy import FactoryJobPolicy


class FactoryQueueError(ValueError):
    """Stable, path-free queue failure."""


@dataclass(frozen=True, slots=True)
class FactoryLease:
    job_id: str
    lease_id: str
    deadline: float
    attempts: int
    policy_sha256: str


@dataclass(frozen=True, slots=True)
class FactoryJobSnapshot:
    job_id: str
    state: str
    attempts: int
    priority: int
    policy_sha256: str
    source_sha256: str
    fragment_count: int
    verified_fragment_count: int
    artifact_sha256: str | None


def _id(value: object, name: str) -> str:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) is None:
        raise FactoryQueueError(name + " has invalid identity")
    return value


def _sha(value: object, name: str) -> str:
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise FactoryQueueError(name + " must be a SHA-256 hex digest")
    return value


def _now(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise FactoryQueueError("Invalid monotonic job wall-clock value")
    return float(value)


class FactoryJobQueue:
    """One SQLite-backed job state authority per trusted owner-selected DB file."""

    def __init__(self, db_path: str | Path) -> None:
        if type(db_path) not in (str, Path):
            raise FactoryQueueError("Trusted database path required")
        db = Path(db_path)
        if not db.is_absolute() or str(db) == ":memory:":
            raise FactoryQueueError("Queue requires a trusted persistent absolute path")
        self._db = str(db)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS factory_jobs (
                    job_id TEXT PRIMARY KEY,
                    policy_json TEXT NOT NULL,
                    policy_sha256 TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    created REAL NOT NULL,
                    updated REAL NOT NULL,
                    lease_id TEXT,
                    lease_deadline REAL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    artifact_sha256 TEXT
                );
                CREATE TABLE IF NOT EXISTS factory_fragments (
                    job_id TEXT NOT NULL,
                    fragment_id TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    result_sha256 TEXT NOT NULL,
                    verified INTEGER NOT NULL,
                    PRIMARY KEY (job_id, fragment_id),
                    FOREIGN KEY (job_id) REFERENCES factory_jobs(job_id)
                );
            """)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self._db, timeout=5.0, isolation_level=None)
        try:
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            yield db
        finally:
            db.close()

    def submit(self, job_id: str, policy: FactoryJobPolicy, *, now: int | float, priority: int = 0) -> FactoryJobSnapshot:
        job_id = _id(job_id, "job_id")
        if type(policy) is not FactoryJobPolicy:
            raise FactoryQueueError("Canonical immutable policy is required")
        if type(priority) is not int or not -1000 <= priority <= 1000:
            raise FactoryQueueError("Priority is invalid")
        timestamp = _now(now)
        serialized = json.dumps(policy.snapshot(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        digest = sha256(serialized.encode("utf-8")).hexdigest()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT policy_sha256, source_sha256 FROM factory_jobs WHERE job_id=?", (job_id,)).fetchone()
            if row:
                if row != (digest, policy.source_sha256):
                    raise FactoryQueueError("Job identity already owns a different immutable policy")
            else:
                db.execute("""INSERT INTO factory_jobs
                    (job_id, policy_json, policy_sha256, source_sha256, state, priority, created, updated)
                    VALUES (?, ?, ?, ?, 'WAITING', ?, ?, ?)""",
                    (job_id, serialized, digest, policy.source_sha256, priority, timestamp, timestamp))
            db.commit()
        return self.snapshot(job_id)

    def acquire(self, *, now: int | float, lease_seconds: int = 60) -> FactoryLease | None:
        timestamp = _now(now)
        if type(lease_seconds) is not int or not 5 <= lease_seconds <= 3600:
            raise FactoryQueueError("Lease duration is invalid")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT job_id, policy_sha256, attempts FROM factory_jobs
                WHERE state='WAITING' OR
                      (state='RUNNING' AND lease_deadline <= ?)
                ORDER BY priority DESC, created ASC, job_id ASC LIMIT 1""", (timestamp,)).fetchone()
            if row is None:
                db.commit()
                return None
            job_id, digest, attempts = row
            token = secrets.token_hex(24)
            deadline = timestamp + lease_seconds
            db.execute("""UPDATE factory_jobs SET state='RUNNING', lease_id=?,
                lease_deadline=?, attempts=attempts+1, updated=? WHERE job_id=?""",
                (token, deadline, timestamp, job_id))
            db.commit()
        return FactoryLease(job_id, token, deadline, attempts + 1, digest)

    def _assert_owned(self, db: sqlite3.Connection, lease: FactoryLease, timestamp: float) -> None:
        if type(lease) is not FactoryLease:
            raise FactoryQueueError("Lease identity required")
        row = db.execute("SELECT lease_id, lease_deadline, state, policy_sha256 FROM factory_jobs WHERE job_id=?", (lease.job_id,)).fetchone()
        if not row or row[0] != lease.lease_id or row[1] <= timestamp or row[2] != "RUNNING" or row[3] != lease.policy_sha256:
            raise FactoryQueueError("Job lease expired, was replaced or is not running")

    def heartbeat(self, lease: FactoryLease, *, now: int | float, lease_seconds: int = 60) -> FactoryLease:
        timestamp = _now(now)
        if type(lease_seconds) is not int or not 5 <= lease_seconds <= 3600:
            raise FactoryQueueError("Lease duration is invalid")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._assert_owned(db, lease, timestamp)
            deadline = timestamp + lease_seconds
            db.execute("UPDATE factory_jobs SET lease_deadline=?, updated=? WHERE job_id=?", (deadline, timestamp, lease.job_id))
            db.commit()
        return FactoryLease(lease.job_id, lease.lease_id, deadline, lease.attempts, lease.policy_sha256)

    def acknowledge_fragment(self, lease: FactoryLease, fragment_id: str, *, source_sha256: str,
                             result_sha256: str, verified: bool, now: int | float) -> bool:
        fragment_id = _id(fragment_id, "fragment_id")
        source_sha256 = _sha(source_sha256, "source_sha256")
        result_sha256 = _sha(result_sha256, "result_sha256")
        if type(verified) is not bool:
            raise FactoryQueueError("Verification flag must be a boolean")
        timestamp = _now(now)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._assert_owned(db, lease, timestamp)
            expected = db.execute("SELECT source_sha256 FROM factory_jobs WHERE job_id=?", (lease.job_id,)).fetchone()[0]
            if source_sha256 != expected:
                raise FactoryQueueError("Checkpoint source drift")
            existing = db.execute("""SELECT source_sha256, result_sha256, verified
                FROM factory_fragments WHERE job_id=? AND fragment_id=?""", (lease.job_id, fragment_id)).fetchone()
            item = (source_sha256, result_sha256, int(verified))
            if existing is not None:
                if existing != item:
                    raise FactoryQueueError("Conflicting fragment checkpoint")
                db.commit()
                return False
            db.execute("""INSERT INTO factory_fragments
                (job_id, fragment_id, source_sha256, result_sha256, verified)
                VALUES (?, ?, ?, ?, ?)""", (lease.job_id, fragment_id, *item))
            db.commit()
            return True

    def transition(self, lease: FactoryLease, *, now: int | float,
                   target: Literal["WAITING", "PAUSED", "REVIEW_REQUIRED", "PARTIAL", "FAILED", "DONE"],
                   artifact_sha256: str | None = None, coverage_verified: bool = False) -> FactoryJobSnapshot:
        timestamp = _now(now)
        if target not in ("WAITING", "PAUSED", "REVIEW_REQUIRED", "PARTIAL", "FAILED", "DONE") or type(target) is not str:
            raise FactoryQueueError("Invalid job transition")
        if type(coverage_verified) is not bool:
            raise FactoryQueueError("Coverage attestation must be boolean")
        if target == "DONE":
            _sha(artifact_sha256, "artifact_sha256")
            if not coverage_verified:
                raise FactoryQueueError("Unverified requested coverage cannot be DONE")
        elif artifact_sha256 is not None or coverage_verified:
            raise FactoryQueueError("Artifact/coverage attestation is only allowed for DONE")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._assert_owned(db, lease, timestamp)
            if target == "DONE":
                counts = db.execute("""SELECT COUNT(*), SUM(verified)
                    FROM factory_fragments WHERE job_id=?""", (lease.job_id,)).fetchone()
                if not counts[0] or counts[0] != counts[1]:
                    raise FactoryQueueError("All accepted fragments must be verified")
            db.execute("""UPDATE factory_jobs SET state=?, lease_id=NULL, lease_deadline=NULL,
                artifact_sha256=?, updated=? WHERE job_id=?""", (target, artifact_sha256, timestamp, lease.job_id))
            db.commit()
        return self.snapshot(lease.job_id)

    def snapshot(self, job_id: str) -> FactoryJobSnapshot:
        job_id = _id(job_id, "job_id")
        with self._connect() as db:
            row = db.execute("""SELECT state, attempts, priority, policy_sha256, source_sha256,
                artifact_sha256 FROM factory_jobs WHERE job_id=?""", (job_id,)).fetchone()
            if row is None:
                raise FactoryQueueError("Unknown job")
            count = db.execute("SELECT COUNT(*), COALESCE(SUM(verified),0) FROM factory_fragments WHERE job_id=?", (job_id,)).fetchone()
        return FactoryJobSnapshot(job_id, row[0], row[1], row[2], row[3], row[4], count[0], count[1], row[5])
