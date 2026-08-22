from __future__ import annotations

"""Durable compare-and-swap persistence for :mod:`acs.student_progress`.

The student progress domain remains authoritative for record validation, ordering,
and summary semantics.  This module owns only filesystem persistence and
optimistic concurrency.  It never persists engine PVs/scores or canonical chess
state beyond the ledger snapshot already defined by ``StudentProgressLedger``.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping

from .student_progress import StudentProgressLedger

STUDENT_PROGRESS_STORE_SCHEMA_VERSION = 1
STUDENT_PROGRESS_STORE_MAX_BYTES = 16 * 1024 * 1024
_ENVELOPE_FIELDS = frozenset({"schema_version", "snapshot"})


class StudentProgressConflictError(RuntimeError):
    """Raised when durable progress changed since the caller last observed it."""


class StudentProgressBusyError(RuntimeError):
    """Raised when another writer currently owns the peer publication lock."""


@dataclass(frozen=True, slots=True)
class LoadedStudentProgress:
    ledger: StudentProgressLedger
    revision: str


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bounded_file(path: Path) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(STUDENT_PROGRESS_STORE_MAX_BYTES + 1)
    if len(data) > STUDENT_PROGRESS_STORE_MAX_BYTES:
        raise ValueError("student progress file exceeds maximum size")
    return data


def _validate_revision(value: str | None) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise TypeError("expected_revision must be a string or None")
    if (
        len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("expected_revision must be a lowercase SHA-256 digest")
    return value


class StudentProgressStore:
    """Atomic local progress file with exact compare-and-swap publication.

    ``expected_revision=None`` means create-only.  Updates require a prior
    :meth:`load` and the exact returned revision.  A stale writer therefore
    fails closed rather than silently replacing newer review history.
    """

    def __init__(self, path: str | Path) -> None:
        if not isinstance(path, (str, Path)):
            raise TypeError("path must be a filesystem path")
        self.path = Path(path).expanduser()
        if str(self.path) in {"", "."}:
            raise ValueError("path must identify a student progress file")
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")

    def load(self) -> LoadedStudentProgress | None:
        try:
            data = _read_bounded_file(self.path)
        except FileNotFoundError:
            return None
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid student progress file") from exc
        if type(payload) is not dict:
            raise ValueError("invalid student progress envelope")
        if set(payload) != _ENVELOPE_FIELDS:
            raise ValueError("invalid student progress envelope fields")
        schema_version = payload["schema_version"]
        if type(schema_version) is not int:
            raise TypeError("student progress store schema_version must be an integer")
        if schema_version != STUDENT_PROGRESS_STORE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported student progress store schema_version: {schema_version}"
            )
        snapshot = payload["snapshot"]
        if not isinstance(snapshot, Mapping):
            raise TypeError("student progress snapshot must be a mapping")
        ledger = StudentProgressLedger.restore(snapshot)
        return LoadedStudentProgress(ledger=ledger, revision=_revision(data))

    def save(
        self,
        ledger: StudentProgressLedger,
        *,
        expected_revision: str | None,
    ) -> str:
        if not isinstance(ledger, StudentProgressLedger):
            raise TypeError("ledger must be a StudentProgressLedger")
        expected = _validate_revision(expected_revision)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._lock_path.mkdir()
        except FileExistsError as exc:
            raise StudentProgressBusyError("student progress store is busy") from exc

        temporary: Path | None = None
        try:
            try:
                current_data = _read_bounded_file(self.path)
            except FileNotFoundError:
                current_revision: str | None = None
            else:
                current_revision = _revision(current_data)

            if current_revision != expected:
                raise StudentProgressConflictError(
                    "student progress changed since the caller last observed it"
                )

            envelope: dict[str, object] = {
                "schema_version": STUDENT_PROGRESS_STORE_SCHEMA_VERSION,
                "snapshot": ledger.snapshot(),
            }
            data = _canonical_bytes(envelope)
            if len(data) > STUDENT_PROGRESS_STORE_MAX_BYTES:
                raise ValueError("student progress payload exceeds maximum size")
            new_revision = _revision(data)

            fd, raw_path = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=str(self.path.parent),
            )
            temporary = Path(raw_path)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                if temporary.exists():
                    temporary.unlink()
                temporary = None
                raise

            os.replace(temporary, self.path)
            temporary = None
            return new_revision
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
            try:
                self._lock_path.rmdir()
            except FileNotFoundError:
                pass
