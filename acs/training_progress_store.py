from __future__ import annotations

"""Durable, presentation-neutral persistence for local training progress.

The training domain owns snapshot semantics in :mod:`acs.training`.  This module
only owns filesystem publication and optimistic concurrency.  It does not parse
moves, validate positions, or introduce another chess/application authority.

Writes are serialized with a persistent peer advisory lock file, validated
against the caller's exact previously observed revision, written to a peer
temporary file, fsynced, revalidated against the publication base, and atomically
published.  A missing expected revision is create-only; updates therefore cannot
silently overwrite progress that the caller never observed.  The lock file itself
may survive process termination; the operating-system lock is released with the
process, so crash residue cannot permanently block later progress saves.

Both read and write paths are bounded.  Progress data and the peer lock are bound
to the actually opened filesystem object before any byte is consumed or written;
symlink/reparse substitution between pathname inspection and open therefore fails
closed instead of redirecting durable progress or lock I/O.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Iterator, Mapping

from .training import ExerciseDefinition, ExerciseSession

TRAINING_PROGRESS_STORE_SCHEMA_VERSION = 1
MAX_TRAINING_PROGRESS_BYTES = 1 * 1024 * 1024
_ENVELOPE_FIELDS = frozenset({"schema_version", "snapshot"})


class TrainingProgressConflictError(RuntimeError):
    """Raised when durable progress changed since the caller last observed it."""


class TrainingProgressBusyError(RuntimeError):
    """Raised when another writer currently owns the peer publication lock."""


class TrainingProgressResourceError(ValueError):
    """Raised when durable progress exceeds the supported storage bounds."""


@dataclass(frozen=True, slots=True)
class LoadedTrainingProgress:
    session: ExerciseSession
    revision: str


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _reject_duplicate_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("training progress contains duplicate JSON object keys")
        result[key] = value
    return result


def _windows_open_no_reparse(path: Path, *, create: bool) -> int:
    """Open one Windows disk file without following a reparse point.

    ``FILE_FLAG_OPEN_REPARSE_POINT`` makes the opened handle, not a prior pathname
    observation, authoritative.  The handle is rejected before conversion to a
    CRT descriptor if it is itself a reparse point or not a disk file.
    """

    import ctypes
    from ctypes import wintypes
    import msvcrt

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    OPEN_EXISTING = 3
    OPEN_ALWAYS = 4
    FILE_ATTRIBUTE_NORMAL = 0x00000080
    FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    FILE_TYPE_DISK = 0x0001
    FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
    ERROR_FILE_NOT_FOUND = 2
    ERROR_PATH_NOT_FOUND = 3

    class FILE_ATTRIBUTE_TAG_INFO(ctypes.Structure):
        _fields_ = [
            ("FileAttributes", wintypes.DWORD),
            ("ReparseTag", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE

    get_file_type = kernel32.GetFileType
    get_file_type.argtypes = [wintypes.HANDLE]
    get_file_type.restype = wintypes.DWORD

    get_info = kernel32.GetFileInformationByHandleEx
    get_info.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    get_info.restype = wintypes.BOOL

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = create_file(
        str(path),
        GENERIC_READ | (GENERIC_WRITE if create else 0),
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_ALWAYS if create else OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid:
        error = ctypes.get_last_error()
        if error in {ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND}:
            raise FileNotFoundError(
                error,
                "could not open training progress storage",
                str(path),
            )
        raise OSError(error, "could not open training progress storage")

    transferred = False
    try:
        if get_file_type(handle) != FILE_TYPE_DISK:
            raise OSError("training progress storage is not a disk file")
        info = FILE_ATTRIBUTE_TAG_INFO()
        if not get_info(
            handle,
            FILE_ATTRIBUTE_TAG_INFO_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            error = ctypes.get_last_error()
            raise OSError(error, "could not inspect opened training progress storage")
        if info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError("training progress storage is a reparse point")

        flags = os.O_RDWR if create else os.O_RDONLY
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        descriptor = msvcrt.open_osfhandle(int(handle), flags)
        transferred = True
        return descriptor
    finally:
        if not transferred:
            close_handle(handle)


def _open_no_reparse(path: Path, *, create: bool) -> int:
    if os.name == "nt":
        return _windows_open_no_reparse(path, create=create)

    flags = os.O_RDWR | os.O_CREAT if create else os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags, 0o600) if create else os.open(path, flags)


class TrainingProgressStore:
    """Atomic single-exercise progress file with compare-and-swap updates."""

    def __init__(self, path: str | Path) -> None:
        if not isinstance(path, (str, Path)):
            raise TypeError("path must be a filesystem path")
        self.path = Path(path).expanduser()
        if str(self.path) in {"", "."}:
            raise ValueError("path must identify a progress file")
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")

    @staticmethod
    def _require_regular_progress(metadata: os.stat_result) -> None:
        if (
            stat.S_ISLNK(metadata.st_mode)
            or _is_reparse_point(metadata)
            or not stat.S_ISREG(metadata.st_mode)
        ):
            raise ValueError("training progress storage is not a regular file")

    def _read_progress_bytes(self, *, missing_ok: bool) -> bytes | None:
        try:
            descriptor = _open_no_reparse(self.path, create=False)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise ValueError("training progress file is unavailable")
        except OSError as exc:
            raise ValueError("training progress file could not be inspected") from exc

        try:
            metadata = os.fstat(descriptor)
            self._require_regular_progress(metadata)
            if metadata.st_size > MAX_TRAINING_PROGRESS_BYTES:
                raise TrainingProgressResourceError(
                    "training progress file exceeds the resource limit"
                )
            chunks: list[bytes] = []
            remaining = MAX_TRAINING_PROGRESS_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > MAX_TRAINING_PROGRESS_BYTES:
                raise TrainingProgressResourceError(
                    "training progress file exceeds the resource limit"
                )
            return data
        except OSError as exc:
            raise ValueError("training progress file could not be read") from exc
        finally:
            os.close(descriptor)

    def load(self, definition: ExerciseDefinition) -> LoadedTrainingProgress | None:
        data = self._read_progress_bytes(missing_ok=True)
        if data is None:
            return None
        try:
            payload = json.loads(
                data.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_object_pairs,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid training progress file") from exc
        if type(payload) is not dict:
            raise ValueError("invalid training progress envelope")
        if set(payload) != _ENVELOPE_FIELDS:
            raise ValueError("invalid training progress envelope fields")
        schema_version = payload["schema_version"]
        if type(schema_version) is not int:
            raise TypeError("training progress schema_version must be an integer")
        if schema_version != TRAINING_PROGRESS_STORE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported training progress schema_version: {schema_version}"
            )
        snapshot = payload["snapshot"]
        if not isinstance(snapshot, Mapping):
            raise TypeError("training progress snapshot must be a mapping")
        session = ExerciseSession.restore(definition, snapshot)
        return LoadedTrainingProgress(session=session, revision=_revision(data))

    @staticmethod
    def _require_regular_lock(metadata: os.stat_result) -> None:
        if (
            stat.S_ISLNK(metadata.st_mode)
            or _is_reparse_point(metadata)
            or not stat.S_ISREG(metadata.st_mode)
        ):
            raise TrainingProgressBusyError("training progress store is busy")

    def _open_lock_descriptor(self) -> int:
        # The precheck is only an early diagnostic.  The opened descriptor/handle
        # below is authoritative and is revalidated before any write.
        try:
            existing = os.lstat(self._lock_path)
        except FileNotFoundError:
            existing = None
        except OSError as exc:
            raise TrainingProgressBusyError("training progress store is busy") from exc
        if existing is not None:
            self._require_regular_lock(existing)

        try:
            descriptor = _open_no_reparse(self._lock_path, create=True)
        except OSError as exc:
            raise TrainingProgressBusyError("training progress store is busy") from exc
        try:
            metadata = os.fstat(descriptor)
            self._require_regular_lock(metadata)
            if metadata.st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _lock_descriptor(descriptor: int) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            raise TrainingProgressBusyError("training progress store is busy") from exc

    @staticmethod
    def _unlock_descriptor(descriptor: int) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass

    @contextmanager
    def _exclusive_access(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = self._open_lock_descriptor()
        acquired = False
        try:
            self._lock_descriptor(descriptor)
            acquired = True
            yield
        finally:
            if acquired:
                self._unlock_descriptor(descriptor)
            os.close(descriptor)

    def save(
        self,
        session: ExerciseSession,
        *,
        expected_revision: str | None,
    ) -> str:
        if not isinstance(session, ExerciseSession):
            raise TypeError("session must be an ExerciseSession")
        expected = _validate_revision(expected_revision)

        temporary: Path | None = None
        with self._exclusive_access():
            try:
                current_data = self._read_progress_bytes(missing_ok=True)
                current_revision = None if current_data is None else _revision(current_data)
                if current_revision != expected:
                    raise TrainingProgressConflictError(
                        "training progress changed since the caller last observed it"
                    )

                envelope: dict[str, object] = {
                    "schema_version": TRAINING_PROGRESS_STORE_SCHEMA_VERSION,
                    "snapshot": session.snapshot(),
                }
                data = _canonical_bytes(envelope)
                if len(data) > MAX_TRAINING_PROGRESS_BYTES:
                    raise TrainingProgressResourceError(
                        "training progress snapshot exceeds the resource limit"
                    )
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

                publication_base = self._read_progress_bytes(missing_ok=True)
                publication_revision = (
                    None if publication_base is None else _revision(publication_base)
                )
                if publication_revision != current_revision:
                    raise TrainingProgressConflictError(
                        "training progress changed during publication"
                    )

                os.replace(temporary, self.path)
                temporary = None
                return new_revision
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
