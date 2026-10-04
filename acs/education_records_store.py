from __future__ import annotations

"""Atomic local persistence for :mod:`acs.education_records`.

The domain ledger owns validation and idempotency.  This store adds only a
versioned envelope, bounded reads, compare-and-swap publication, peer exclusion,
and atomic replacement.  A failed or stale writer never partially overwrites the
last durable ledger.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping

from .education_records import (
    EducationLedger,
    EducationRecordsError,
    MAX_SNAPSHOT_BYTES,
)


EDUCATION_RECORDS_STORE_VERSION = 1
MAX_STORE_BYTES = MAX_SNAPSHOT_BYTES + 128_000
MAX_WIRE_INTEGER = (1 << 53) - 1
_ENVELOPE_FIELDS = frozenset({"schema_version", "ledger"})


class EducationRecordsConflictError(RuntimeError):
    """Raised when the durable file changed since the caller loaded it."""


class EducationRecordsBusyError(RuntimeError):
    """Raised while another writer owns the peer publication lock."""


class EducationRecordsStoreError(ValueError):
    """Raised for malformed, unsupported, or oversized durable envelopes."""


@dataclass(frozen=True)
class LoadedEducationRecords:
    ledger: EducationLedger
    revision: str


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    try:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        data = text.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise EducationRecordsStoreError(
            "education records cannot be serialized for durable storage"
        ) from exc
    if len(data) > MAX_STORE_BYTES:
        raise EducationRecordsStoreError("education records store exceeds size limit")
    return data


def _revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_revision(value: object) -> str | None:
    if value is None:
        return None
    if (
        type(value) is not str
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EducationRecordsStoreError(
            "expected revision must be a lowercase SHA-256 digest or null"
        )
    return value


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EducationRecordsStoreError(f"duplicate durable JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise EducationRecordsStoreError(
        f"non-finite durable JSON constant is not allowed: {value}"
    )


def _parse_wire_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 16:
        raise EducationRecordsStoreError(
            "durable JSON integer exceeds exact wire bounds"
        )
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise EducationRecordsStoreError("invalid durable JSON integer") from exc
    if not -MAX_WIRE_INTEGER <= parsed <= MAX_WIRE_INTEGER:
        raise EducationRecordsStoreError(
            "durable JSON integer exceeds exact wire bounds"
        )
    return parsed


class EducationRecordsStore:
    """Versioned atomic file store with exact compare-and-swap semantics.

    ``expected_revision=None`` is create-only.  Any update requires the exact
    revision returned by :meth:`load` or :meth:`save`.  This prevents a stale
    teacher/session process from replacing newer assignment/session history.
    """

    def __init__(self, path: str | Path) -> None:
        if not isinstance(path, (str, Path)):
            raise TypeError("path must be a filesystem path")
        self.path = Path(path).expanduser()
        if str(self.path) in {"", "."}:
            raise ValueError("path must identify an education records file")
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")

    def _read_current_bytes(self) -> bytes | None:
        try:
            with self.path.open("rb") as handle:
                data = handle.read(MAX_STORE_BYTES + 1)
        except FileNotFoundError:
            return None
        if len(data) > MAX_STORE_BYTES:
            raise EducationRecordsStoreError(
                "education records store exceeds size limit"
            )
        return data

    def load(self) -> LoadedEducationRecords | None:
        data = self._read_current_bytes()
        if data is None:
            return None
        try:
            text = data.decode("utf-8")
            payload = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
                parse_int=_parse_wire_integer,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise EducationRecordsStoreError(
                "invalid education records store"
            ) from exc
        if type(payload) is not dict or set(payload) != _ENVELOPE_FIELDS:
            raise EducationRecordsStoreError(
                "invalid education records store envelope"
            )
        schema = payload["schema_version"]
        if type(schema) is not int or schema != EDUCATION_RECORDS_STORE_VERSION:
            raise EducationRecordsStoreError(
                f"unsupported education records store schema version: {schema!r}"
            )
        raw_ledger = payload["ledger"]
        if not isinstance(raw_ledger, Mapping):
            raise EducationRecordsStoreError(
                "education records ledger must be an object"
            )
        try:
            ledger = EducationLedger.from_record(raw_ledger)
        except EducationRecordsError as exc:
            raise EducationRecordsStoreError(
                "invalid education records ledger"
            ) from exc
        return LoadedEducationRecords(ledger=ledger, revision=_revision(data))

    def save(
        self,
        ledger: EducationLedger,
        *,
        expected_revision: str | None,
    ) -> str:
        if type(ledger) is not EducationLedger:
            raise TypeError("ledger must be EducationLedger")
        expected = _validate_revision(expected_revision)
        envelope = {
            "schema_version": EDUCATION_RECORDS_STORE_VERSION,
            "ledger": ledger.to_record(),
        }
        data = _canonical_bytes(envelope)
        new_revision = _revision(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._lock_path.mkdir()
        except FileExistsError as exc:
            raise EducationRecordsBusyError(
                "education records store is busy"
            ) from exc

        temporary: Path | None = None
        try:
            current_data = self._read_current_bytes()
            current_revision = (
                None if current_data is None else _revision(current_data)
            )
            if current_revision != expected:
                raise EducationRecordsConflictError(
                    "education records changed since the caller last observed them"
                )

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
