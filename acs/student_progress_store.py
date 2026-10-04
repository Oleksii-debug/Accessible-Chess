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
import stat
import tempfile
from typing import Mapping

from .book_progress_store import _replace_published_path, _sync_published_path
from .student_progress import StudentProgressLedger

STUDENT_PROGRESS_STORE_SCHEMA_VERSION = 1
STUDENT_PROGRESS_STORE_MAX_BYTES = 16 * 1024 * 1024
_ENVELOPE_FIELDS = frozenset({"schema_version", "snapshot"})
_LOCK_MARKER = b"\0"


class StudentProgressConflictError(RuntimeError):
    """Raised when durable progress changed since the caller last observed it."""


class StudentProgressBusyError(RuntimeError):
    """Raised when another writer currently owns the peer publication lock."""


class StudentProgressDurabilityError(RuntimeError):
    """Raised after publication when stable-storage confirmation is unknown."""


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


def _is_reparse_point(metadata: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(flag and attributes & flag)


def _same_file_identity(first: os.stat_result, second: os.stat_result) -> bool:
    try:
        return os.path.samestat(first, second)
    except (AttributeError, OSError):
        return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def _require_private_lock_metadata(metadata: os.stat_result) -> None:
    if (
        stat.S_ISLNK(metadata.st_mode)
        or _is_reparse_point(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or int(getattr(metadata, "st_nlink", 1)) != 1
        or metadata.st_size != len(_LOCK_MARKER)
    ):
        raise StudentProgressBusyError("student progress store lock is unavailable")


def _open_lock_descriptor(path: Path) -> int:
    """Open one persistent private lock inode without following redirects.

    The lock pathname is intentionally retained after a transaction.  Kernel
    lock ownership is descriptor-scoped, so a process crash releases authority
    automatically without a check-then-delete race on the shared pathname.
    """

    flags = os.O_RDWR
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOINHERIT", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)

    try:
        before = os.lstat(path)
    except FileNotFoundError:
        before = None
    except OSError as exc:
        raise StudentProgressBusyError("student progress store lock is unavailable") from exc

    created = False
    if before is None:
        try:
            descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
        except FileExistsError:
            # A peer won first creation. Fail closed for this attempt rather than
            # reopening a pathname whose initialization is still in flight.
            raise StudentProgressBusyError("student progress store is busy") from None
        except OSError as exc:
            raise StudentProgressBusyError("student progress store lock is unavailable") from exc
    else:
        # A legacy directory lock may still be held by an older process. Never
        # reclaim it speculatively: that could admit two writers. It therefore
        # remains a safe busy state that can be repaired out of band if stale.
        if stat.S_ISDIR(before.st_mode):
            raise StudentProgressBusyError("student progress store is busy")
        _require_private_lock_metadata(before)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise StudentProgressBusyError("student progress store lock is unavailable") from exc

    try:
        if created:
            os.write(descriptor, _LOCK_MARKER)
            os.fsync(descriptor)
        opened = os.fstat(descriptor)
        _require_private_lock_metadata(opened)
        if before is not None and not _same_file_identity(before, opened):
            raise StudentProgressBusyError("student progress store lock changed while opening")
        try:
            current = os.lstat(path)
        except OSError as exc:
            raise StudentProgressBusyError("student progress store lock changed while opening") from exc
        _require_private_lock_metadata(current)
        if not _same_file_identity(opened, current):
            raise StudentProgressBusyError("student progress store lock changed while opening")
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.read(descriptor, len(_LOCK_MARKER) + 1) != _LOCK_MARKER:
            raise StudentProgressBusyError("student progress store lock changed while opening")
        return descriptor
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _lock_file_descriptor(descriptor: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, len(_LOCK_MARKER))
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise StudentProgressBusyError("student progress store is busy") from None


def _unlock_file_descriptor(descriptor: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, len(_LOCK_MARKER))
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        # Transaction completion is authoritative. Failure to explicitly unlock
        # cannot undo already-published bytes; close below still releases the OS
        # lock and must not turn a successful durable save into a false failure.
        pass


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

        descriptor = _open_lock_descriptor(self._lock_path)
        acquired = False
        temporary: Path | None = None
        try:
            _lock_file_descriptor(descriptor)
            acquired = True

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

            # Reuse the already-canonical BookProgress publication authority:
            # Windows uses MoveFileExW(...WRITE_THROUGH), while POSIX publishes
            # atomically and fsyncs the containing directory below.
            _replace_published_path(temporary, self.path)
            temporary = None
            try:
                _sync_published_path(self.path)
            except OSError:
                # Replacement has already made bytes visible. Returning a normal
                # revision here would falsely acknowledge durability. Callers can
                # reload the visible canonical state before choosing a retry.
                raise StudentProgressDurabilityError(
                    "student progress was published but durability could not be confirmed"
                ) from None
            return new_revision
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
            if acquired:
                _unlock_file_descriptor(descriptor)
            try:
                os.close(descriptor)
            except OSError:
                pass
