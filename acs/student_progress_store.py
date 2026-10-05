from __future__ import annotations

"""Durable compare-and-swap persistence for :mod:`acs.student_progress`.

The student progress domain remains authoritative for record validation, ordering,
and summary semantics.  This module owns only filesystem persistence and
optimistic concurrency.  It never persists engine PVs/scores or canonical chess
state beyond the ledger snapshot already defined by ``StudentProgressLedger``.
"""

from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Mapping

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
    """Raised after publication when the canonical file cannot be confirmed."""


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


def _reparse(info: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


def _identity(info: os.stat_result) -> tuple[int, int]:
    return int(info.st_dev), int(info.st_ino)


def _same_file_identity(first: os.stat_result, second: os.stat_result) -> bool:
    try:
        return os.path.samestat(first, second)
    except (AttributeError, OSError):
        return _identity(first) == _identity(second)


def _same_file_version(
    first: os.stat_result, second: os.stat_result, *, cross_interface: bool = False
) -> bool:
    return (
        _same_file_identity(first, second)
        and int(first.st_size) == int(second.st_size)
        and int(getattr(first, "st_mtime_ns", 0))
        == int(getattr(second, "st_mtime_ns", 0))
        and (
            (cross_interface and os.name == "nt")
            or int(getattr(first, "st_ctime_ns", 0))
            == int(getattr(second, "st_ctime_ns", 0))
        )
    )


def _require_private_regular(info: os.stat_result, label: str) -> None:
    if (
        stat.S_ISLNK(info.st_mode)
        or _reparse(info)
        or not stat.S_ISREG(info.st_mode)
        or int(getattr(info, "st_nlink", 1)) != 1
    ):
        raise ValueError(f"{label} must be one private regular file")


def _require_private_directory(info: os.stat_result, label: str) -> None:
    if stat.S_ISLNK(info.st_mode) or _reparse(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"{label} must be one private directory")


def _read_bounded_file(path: Path) -> bytes:
    """Read one stable private snapshot without following filesystem redirects."""

    parent_before = path.parent.lstat()
    _require_private_directory(parent_before, "student progress directory")
    before = path.lstat()
    _require_private_regular(before, "student progress file")
    if int(before.st_size) > STUDENT_PROGRESS_STORE_MAX_BYTES:
        raise ValueError("student progress file exceeds maximum size")

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOINHERIT", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        _require_private_regular(opened, "student progress file")
        if not _same_file_identity(before, opened):
            raise ValueError("student progress file changed while opening")
        if int(opened.st_size) > STUDENT_PROGRESS_STORE_MAX_BYTES:
            raise ValueError("student progress file exceeds maximum size")

        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(
                descriptor,
                min(65536, STUDENT_PROGRESS_STORE_MAX_BYTES + 1 - total),
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > STUDENT_PROGRESS_STORE_MAX_BYTES:
                raise ValueError("student progress file exceeds maximum size")

        after = os.fstat(descriptor)
        _require_private_regular(after, "student progress file")
        if not _same_file_version(opened, after) or total != int(after.st_size):
            raise ValueError("student progress file changed while reading")

        # As in canonical Training persistence, Windows fstat/lstat ctime values
        # are not comparable across the two APIs. Keep full descriptor-version
        # checks, and confirm content through the held descriptor before the
        # final pathname identity/size/mtime check. A same-size edit with restored
        # mtime must still be rejected rather than mistaken for a stable snapshot.
        data = b"".join(chunks)
        del chunks
        expected_digest = hashlib.sha256(data).digest()
        os.lseek(descriptor, 0, os.SEEK_SET)
        confirmed_digest = hashlib.sha256()
        confirmed_total = 0
        while True:
            chunk = os.read(
                descriptor,
                min(65536, STUDENT_PROGRESS_STORE_MAX_BYTES + 1 - confirmed_total),
            )
            if not chunk:
                break
            confirmed_total += len(chunk)
            if confirmed_total > STUDENT_PROGRESS_STORE_MAX_BYTES:
                raise ValueError("student progress file exceeds maximum size")
            confirmed_digest.update(chunk)
        confirmed = os.fstat(descriptor)
        _require_private_regular(confirmed, "student progress file")
        if (
            not _same_file_version(opened, confirmed)
            or confirmed_total != total
            or confirmed_digest.digest() != expected_digest
        ):
            raise ValueError("student progress file changed while reading")

        parent_after = path.parent.lstat()
        _require_private_directory(parent_after, "student progress directory")
        if not _same_file_identity(parent_before, parent_after):
            raise ValueError("student progress directory changed while reading")
        current = path.lstat()
        _require_private_regular(current, "student progress file")
        if not _same_file_version(confirmed, current, cross_interface=True):
            raise ValueError("student progress file changed while reading")
        return data
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if os.name == "nt" or exc.errno in {
            errno.EACCES,
            errno.EINVAL,
            errno.ENOTSUP,
        }:
            return
        raise
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if os.name != "nt" and exc.errno not in {errno.EINVAL, errno.ENOTSUP}:
                raise
    finally:
        os.close(descriptor)



def _storage_directory_snapshot(path: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise StudentProgressBusyError(
            "student progress storage directory is unavailable"
        ) from exc
    try:
        _require_private_directory(metadata, "student progress directory")
    except ValueError as exc:
        raise StudentProgressBusyError(
            "student progress storage directory is unavailable"
        ) from exc
    return metadata


def _assert_storage_directory_current(
    path: Path,
    expected: os.stat_result,
) -> None:
    current = _storage_directory_snapshot(path)
    if not _same_file_identity(expected, current):
        raise StudentProgressBusyError(
            "student progress storage directory changed during save"
        )


def _open_writer_lock(path: Path) -> int:
    """Open one persistent private lock inode without following redirects.

    The pathname remains in place between transactions. Kernel lock ownership is
    descriptor-scoped, so an abrupt process exit releases writer authority
    automatically without a check-then-delete race on the shared lock pathname.
    """

    flags = os.O_RDWR
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOINHERIT", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)

    try:
        before = path.lstat()
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
            # A peer won first creation and may still be initializing its marker.
            # Fail this attempt closed rather than adopting an in-flight inode.
            raise StudentProgressBusyError("student progress store is busy") from None
        except OSError as exc:
            raise StudentProgressBusyError("student progress store lock is unavailable") from exc
    else:
        # A legacy directory lock may still belong to an older running writer.
        # Never remove it speculatively; unsafe reclamation could admit two writers.
        if stat.S_ISDIR(before.st_mode):
            raise StudentProgressBusyError("student progress store is busy")
        try:
            _require_private_regular(before, "student progress lock")
        except ValueError as exc:
            raise StudentProgressBusyError("student progress store lock is unavailable") from exc
        if int(before.st_size) != len(_LOCK_MARKER):
            raise StudentProgressBusyError("student progress store lock is unavailable")
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise StudentProgressBusyError("student progress store lock is unavailable") from exc

    try:
        if created:
            os.write(descriptor, _LOCK_MARKER)
            os.fsync(descriptor)
        opened = os.fstat(descriptor)
        _require_private_regular(opened, "student progress lock")
        if int(opened.st_size) != len(_LOCK_MARKER):
            raise StudentProgressBusyError("student progress store lock is unavailable")
        if before is not None and not _same_file_identity(before, opened):
            raise StudentProgressBusyError("student progress store lock changed while opening")
        try:
            current = path.lstat()
        except OSError as exc:
            raise StudentProgressBusyError("student progress store lock changed while opening") from exc
        _require_private_regular(current, "student progress lock")
        if not _same_file_identity(opened, current):
            raise StudentProgressBusyError("student progress store lock changed while opening")
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            marker = os.read(descriptor, len(_LOCK_MARKER) + 1)
        except OSError as exc:
            # A live peer's Windows byte-range lock can deny this pre-lock read.
            # Report the existing busy authority and release our descriptor;
            # never reinterpret denied access as a valid marker or delete it.
            raise StudentProgressBusyError("student progress store is busy") from exc
        if marker != _LOCK_MARKER:
            raise StudentProgressBusyError("student progress store lock changed while opening")
        return descriptor
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _assert_writer_lock_current(path: Path, descriptor: int) -> None:
    """Re-authenticate pathname-to-handle lock identity at transaction boundaries."""
    try:
        opened = os.fstat(descriptor)
        _require_private_regular(opened, "student progress lock")
        if int(opened.st_size) != len(_LOCK_MARKER):
            raise StudentProgressBusyError("student progress store lock is unavailable")
        current = path.lstat()
        _require_private_regular(current, "student progress lock")
    except (OSError, ValueError) as exc:
        raise StudentProgressBusyError(
            "student progress store lock changed during save"
        ) from exc

    if not _same_file_identity(opened, current):
        raise StudentProgressBusyError(
            "student progress store lock changed during save"
        )

    try:
        position = os.lseek(descriptor, 0, os.SEEK_CUR)
        os.lseek(descriptor, 0, os.SEEK_SET)
        marker = os.read(descriptor, len(_LOCK_MARKER) + 1)
        os.lseek(descriptor, position, os.SEEK_SET)
    except OSError as exc:
        raise StudentProgressBusyError(
            "student progress store lock changed during save"
        ) from exc
    if marker != _LOCK_MARKER:
        raise StudentProgressBusyError(
            "student progress store lock changed during save"
        )


def _lock_writer_descriptor(descriptor: int) -> None:
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


def _unlock_writer_descriptor(descriptor: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, len(_LOCK_MARKER))
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        # Closing the descriptor still releases kernel authority. Lock cleanup
        # must not turn already-published progress into a false save failure.
        pass


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("student progress JSON contains duplicate object keys")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"student progress JSON constant is invalid: {value}")


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
        # Bind relative configuration to the construction-time working directory
        # without resolving symlinks/reparse points.
        self.path = Path(path).expanduser().absolute()
        if str(self.path) in {"", "."}:
            raise ValueError("path must identify a student progress file")
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")

    def load(self) -> LoadedStudentProgress | None:
        try:
            data = _read_bounded_file(self.path)
        except FileNotFoundError:
            return None
        try:
            payload = json.loads(
                data.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
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
        directory_identity = _storage_directory_snapshot(self.path.parent)

        descriptor = _open_writer_lock(self._lock_path)
        acquired = False
        temporary: Path | None = None
        try:
            _lock_writer_descriptor(descriptor)
            acquired = True
            _assert_storage_directory_current(self.path.parent, directory_identity)
            _assert_writer_lock_current(self._lock_path, descriptor)
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
            temporary_identity: os.stat_result | None = None
            try:
                created = os.fstat(fd)
                _require_private_regular(created, "student progress temporary file")
                temporary_identity = created
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                    prepared = os.fstat(handle.fileno())
                    _require_private_regular(
                        prepared,
                        "student progress temporary file",
                    )
                    if not _same_file_identity(created, prepared):
                        raise StudentProgressBusyError(
                            "student progress temporary file changed while being prepared"
                        )
                    temporary_identity = prepared
            except Exception:
                # The descriptor may not yet have entered os.fdopen(). Always
                # close it, but never mutate the temporary pathname after an
                # error: another actor may have won a pathname race.
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise

            _assert_storage_directory_current(self.path.parent, directory_identity)
            current_temp = temporary.lstat()
            _require_private_regular(current_temp, "student progress temporary file")
            if (
                temporary_identity is None
                or not _same_file_identity(temporary_identity, current_temp)
            ):
                raise StudentProgressBusyError(
                    "student progress temporary file changed before publication"
                )
            _assert_writer_lock_current(self._lock_path, descriptor)
            os.replace(temporary, self.path)
            temporary = None

            published = self.path.lstat()
            _require_private_regular(published, "student progress publication")
            if not _same_file_identity(current_temp, published):
                raise StudentProgressDurabilityError(
                    "student progress publication identity changed"
                )
            try:
                _assert_storage_directory_current(
                    self.path.parent,
                    directory_identity,
                )
                _fsync_directory(self.path.parent)
                confirmed = _read_bounded_file(self.path)
            except Exception as exc:
                raise StudentProgressDurabilityError(
                    "student progress was published but could not be confirmed"
                ) from exc
            if confirmed != data or _revision(confirmed) != new_revision:
                raise StudentProgressDurabilityError(
                    "student progress was published but canonical bytes changed"
                )
            try:
                _assert_storage_directory_current(
                    self.path.parent,
                    directory_identity,
                )
                final_publication = self.path.lstat()
                _require_private_regular(
                    final_publication,
                    "student progress publication",
                )
                if not _same_file_identity(published, final_publication):
                    raise StudentProgressBusyError(
                        "student progress publication identity changed"
                    )
                _assert_writer_lock_current(self._lock_path, descriptor)
            except (StudentProgressBusyError, OSError, ValueError) as exc:
                raise StudentProgressDurabilityError(
                    "student progress was published but writer authority changed"
                ) from exc
            return new_revision
        finally:
            # A failed transaction may intentionally leave a noncanonical
            # random .tmp residue. Renaming or unlinking it after an error would
            # reintroduce a check-then-path-mutation race; canonical progress is
            # protected by the lock/CAS/publication path instead.
            if acquired:
                _unlock_writer_descriptor(descriptor)
            try:
                os.close(descriptor)
            except OSError:
                pass
