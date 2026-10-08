"""R68 product SQLite journal ADAPTER for the single canonical MigrationCutover.

A journal is not a second cutover authority. Durable reservation is UNKNOWN
until fenced/staged/committed in the original canonical order. Replays NEVER
return NEW, including same-digest idempotent calls. The independent routing
CAS and source fence remain external, as does anti-rollback/HA qualification.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3

from continuum_runtime.backend_migration import MigrationError, MigrationProof


class SqliteMigrationJournal:
    """Single-host, ACID, fail-closed R68 DurableJournal protocol adapter.

    All operations use fresh SQLite connections and BEGIN IMMEDIATE so separate
    workers/processes contend on the same persisted migration_id. This is NOT
    a cross-host consensus journal and requires external backup/anti-rollback.
    """

    _SCHEMA_VERSION = 1
    _NEXT = {
        "RESERVED_UNKNOWN": "FENCED",
        "FENCED": "STAGED",
        "STAGED": "COMMITTED",
    }

    def __init__(self, path: str | Path) -> None:
        if not isinstance(path, (str, Path)) or not str(path).strip():
            raise MigrationError("MIGRATION_JOURNAL_PATH_INVALID")
        self.path = Path(path)
        if (str(self.path) == ":memory:" or self.path.suffix.casefold() != ".sqlite3"
                or self.path.is_symlink() or not self.path.parent.is_dir()):
            raise MigrationError("MIGRATION_JOURNAL_PATH_UNSAFE")
        try:
            with self._open() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS r68_journal_meta("
                    "singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
                    "schema_version INTEGER NOT NULL)"
                )
                found = db.execute(
                    "SELECT schema_version FROM r68_journal_meta WHERE singleton=1"
                ).fetchone()
                if found is None:
                    db.execute(
                        "INSERT INTO r68_journal_meta(singleton,schema_version) VALUES(1,?)",
                        (self._SCHEMA_VERSION,)
                    )
                elif found[0] != self._SCHEMA_VERSION:
                    raise MigrationError("MIGRATION_JOURNAL_SCHEMA_UNSUPPORTED")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS r68_migration_journal("
                    "migration_id TEXT PRIMARY KEY NOT NULL,"
                    "proof_sha256 TEXT NOT NULL,"
                    "snapshot_sha256 TEXT NOT NULL,"
                    "phase TEXT NOT NULL CHECK(phase IN "
                    "('RESERVED_UNKNOWN','FENCED','STAGED','COMMITTED')))"
                )
        except MigrationError:
            raise
        except (OSError, sqlite3.Error):
            raise MigrationError("MIGRATION_JOURNAL_UNAVAILABLE") from None

    def _open(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA journal_mode=WAL")
            return db
        except Exception:
            db.close()
            raise

    @staticmethod
    def _proof_digest(proof: MigrationProof) -> str:
        if type(proof) is not MigrationProof:
            raise MigrationError("MIGRATION_JOURNAL_PROOF_INVALID")
        proof.__post_init__()
        raw = json.dumps(
            asdict(proof), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("ascii")
        return hashlib.sha256(b"acs:r68:migration-journal:v1\0" + raw).hexdigest()

    def begin(self, proof: MigrationProof) -> bool:
        proof_sha = self._proof_digest(proof)
        try:
            with self._open() as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute(
                    "SELECT proof_sha256 FROM r68_migration_journal WHERE migration_id=?",
                    (proof.migration_id,),
                ).fetchone()
                if existing is not None:
                    # NEVER issue a second 'NEW', even with the same proof.
                    return False
                db.execute(
                    "INSERT INTO r68_migration_journal("
                    "migration_id,proof_sha256,snapshot_sha256,phase)"
                    " VALUES(?,?,?,?)",
                    (proof.migration_id, proof_sha, proof.snapshot_sha256,
                     "RESERVED_UNKNOWN"),
                )
                return True
        except (sqlite3.Error, OSError):
            # Insert might have committed. It is unsafe to blind-retry.
            raise MigrationError("MIGRATION_JOURNAL_RESERVATION_UNKNOWN") from None

    def record(self, migration_id: str, event: str, digest: str) -> bool:
        if (type(migration_id) is not str or not migration_id
                or type(event) is not str or event not in self._NEXT.values()
                or type(digest) is not str or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)):
            raise MigrationError("MIGRATION_JOURNAL_RECORD_INVALID")
        try:
            with self._open() as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute(
                    "SELECT snapshot_sha256,phase FROM r68_migration_journal"
                    " WHERE migration_id=?", (migration_id,),
                ).fetchone()
                if (existing is None or existing[0] != digest
                        or self._NEXT.get(existing[1]) != event):
                    return False
                cursor = db.execute(
                    "UPDATE r68_migration_journal SET phase=? WHERE migration_id=?"
                    " AND phase=? AND snapshot_sha256=?",
                    (event, migration_id, existing[1], digest),
                )
                return cursor.rowcount == 1
        except (sqlite3.Error, OSError):
            raise MigrationError("MIGRATION_JOURNAL_RECORD_UNKNOWN") from None

    def status(self, migration_id: str) -> str:
        if type(migration_id) is not str or not migration_id:
            raise MigrationError("MIGRATION_JOURNAL_ID_INVALID")
        try:
            with self._open() as db:
                record = db.execute(
                    "SELECT phase FROM r68_migration_journal WHERE migration_id=?",
                    (migration_id,),
                ).fetchone()
                if record is None:
                    return "UNKNOWN_FAIL_CLOSED"
                if type(record[0]) is not str or record[0] not in {
                    "RESERVED_UNKNOWN", *self._NEXT.values()
                }:
                    raise MigrationError("MIGRATION_JOURNAL_CORRUPT")
                return record[0]
        except MigrationError:
            raise
        except (sqlite3.Error, OSError):
            raise MigrationError("MIGRATION_JOURNAL_READ_UNKNOWN") from None


__all__ = ["SqliteMigrationJournal"]
