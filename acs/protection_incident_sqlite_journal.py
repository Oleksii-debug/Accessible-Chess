"""R62 durable case-journal ADAPTER for canonical R61/R22 leak response.

This stores only opaque case/proof hashes and exact R22 revocation IDs.
The independent R22 verifier checks that the same revocation is STILL active;
a replay, restored/replaced effect or provider uncertainty NEVER grants NEW.
This is not a watermark issuer, second revocation authority, or online API.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
from typing import Callable

from .protection_incident_response_boundary import IncidentBoundaryDenied

_CASE = re.compile(r"^[0-9a-f]{32}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class SqliteIncidentJournal:
    """Single-host ACID journal; external anti-rollback/HA anchors still needed."""

    def __init__(
        self, path: str | Path,
        *, verify_active_revocation: Callable[[str], bool],
    ) -> None:
        if not callable(verify_active_revocation):
            raise IncidentBoundaryDenied("R62_EFFECT_READBACK_NOT_CONFIGURED")
        if not isinstance(path, (str, Path)) or not str(path).strip():
            raise IncidentBoundaryDenied("R62_JOURNAL_PATH_INVALID")
        self.path = Path(path)
        if (self.path.suffix.casefold() != ".sqlite3"
                or str(self.path) == ":memory:"
                or not self.path.parent.is_dir()
                or self.path.is_symlink()):
            raise IncidentBoundaryDenied("R62_JOURNAL_PATH_UNSAFE")
        self._active = verify_active_revocation
        try:
            with self._open() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS r62_meta("
                    "singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
                    "schema_version INTEGER NOT NULL)"
                )
                found = db.execute(
                    "SELECT schema_version FROM r62_meta WHERE singleton=1"
                ).fetchone()
                if found is None:
                    db.execute(
                        "INSERT INTO r62_meta(singleton,schema_version) VALUES(1,1)"
                    )
                elif found[0] != 1:
                    raise IncidentBoundaryDenied("R62_JOURNAL_SCHEMA_UNSUPPORTED")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS r62_incidents("
                    "case_id TEXT PRIMARY KEY,"
                    "request_digest TEXT NOT NULL,"
                    "state TEXT NOT NULL CHECK(state IN ('UNKNOWN','COMMITTED')),"
                    "revocation_id TEXT)"
                )
        except IncidentBoundaryDenied:
            raise
        except (sqlite3.Error, OSError):
            raise IncidentBoundaryDenied("R62_JOURNAL_UNAVAILABLE") from None

    @contextmanager
    def _open(self):
        if self.path.is_symlink():
            raise IncidentBoundaryDenied("R62_JOURNAL_PATH_UNSAFE")
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA synchronous=FULL")
            yield db
            if db.in_transaction:
                db.commit()
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _validate_case(case_id: str, request_digest: str) -> None:
        if (type(case_id) is not str or _CASE.fullmatch(case_id) is None
                or type(request_digest) is not str
                or _SHA.fullmatch(request_digest) is None):
            raise IncidentBoundaryDenied("R62_JOURNAL_INPUT_INVALID")

    def reserve(self, *, case_id: str, request_digest: str) -> str:
        self._validate_case(case_id, request_digest)
        try:
            with self._open() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT request_digest FROM r62_incidents WHERE case_id=?",
                    (case_id,),
                ).fetchone()
                if row is not None:
                    return "UNKNOWN"
                db.execute(
                    "INSERT INTO r62_incidents(case_id,request_digest,state)"
                    " VALUES(?,?,'UNKNOWN')",
                    (case_id, request_digest),
                )
                return "NEW"
        except (sqlite3.Error, OSError):
            # Even after an uncertain commit it is forbidden to send R22 twice.
            raise IncidentBoundaryDenied("R62_JOURNAL_RESERVATION_UNKNOWN") from None

    def complete(
        self, *, case_id: str, request_digest: str, revocation_id: str,
    ) -> bool:
        self._validate_case(case_id, request_digest)
        if type(revocation_id) is not str or _ID.fullmatch(revocation_id) is None:
            raise IncidentBoundaryDenied("R62_REVOCATION_ID_INVALID")
        try:
            if self._active(revocation_id) is not True:
                return False
        except Exception:
            return False
        try:
            with self._open() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT request_digest,state FROM r62_incidents WHERE case_id=?",
                    (case_id,),
                ).fetchone()
                if (row is None or row[0] != request_digest
                        or row[1] != "UNKNOWN"):
                    return False
                changed = db.execute(
                    "UPDATE r62_incidents SET state='COMMITTED', revocation_id=?"
                    " WHERE case_id=? AND request_digest=? AND state='UNKNOWN'",
                    (revocation_id, case_id, request_digest),
                )
                if changed.rowcount != 1:
                    return False
        except (sqlite3.Error, OSError):
            raise IncidentBoundaryDenied("R62_JOURNAL_COMMIT_UNKNOWN") from None
        # Confirm exact durable state and the SAME active R22 effect after commit.
        return self.status(case_id=case_id, request_digest=request_digest) == "COMMITTED"

    def status(self, *, case_id: str, request_digest: str) -> str:
        self._validate_case(case_id, request_digest)
        try:
            with self._open() as db:
                row = db.execute(
                    "SELECT request_digest,state,revocation_id FROM r62_incidents"
                    " WHERE case_id=?",
                    (case_id,),
                ).fetchone()
            if (row is None or row[0] != request_digest
                    or row[1] != "COMMITTED"
                    or type(row[2]) is not str or _ID.fullmatch(row[2]) is None):
                return "UNKNOWN_FAIL_CLOSED"
            try:
                return "COMMITTED" if self._active(row[2]) is True else "UNKNOWN_FAIL_CLOSED"
            except Exception:
                return "UNKNOWN_FAIL_CLOSED"
        except (sqlite3.Error, OSError):
            return "UNKNOWN_FAIL_CLOSED"


__all__ = ["SqliteIncidentJournal"]
