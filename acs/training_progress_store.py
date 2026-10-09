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
the configured path is bound to an absolute lexical location at construction and
existing storage-directory components reject symlink/reparse redirection before
reads or directory creation.  The containing storage directory is likewise
identity-bound across a transaction.  Symlink/reparse substitution between
pathname inspection and open therefore fails closed instead of redirecting
durable progress or lock I/O.  Successful writes are reported only after the
published namespace entry receives the platform's durability barrier.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile
import time
from typing import Any, Iterator, Mapping

from .training import ExerciseDefinition, ExerciseSession

TRAINING_PROGRESS_STORE_SCHEMA_VERSION = 1
MAX_TRAINING_PROGRESS_BYTES = 1 * 1024 * 1024
MAX_TRAINING_PROGRESS_JSON_OBJECT_MEMBERS = 64
MAX_TRAINING_PROGRESS_JSON_KEY_CHARS = 128
_ENVELOPE_FIELDS = frozenset({"schema_version", "snapshot"})


class TrainingProgressConflictError(RuntimeError):
    """Raised when durable progress changed since the caller last observed it."""


class TrainingProgressBusyError(RuntimeError):
    """Raised when another writer currently owns the peer publication lock."""


class TrainingProgressDurabilityUnknownError(RuntimeError):
    """Raised after atomic publication when durable/canonical confirmation fails."""

    def __init__(self, message: str, *, published_revision: str) -> None:
        super().__init__(message)
        self.published_revision = _validate_revision(published_revision)
        assert self.published_revision is not None


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
    # json's object_pairs_hook receives the parser's unhashed pair list. Bound
    # both dimensions before the first dict lookup/insertion so a malformed
    # persisted file cannot amplify its bounded bytes into unbounded hash work.
    # Current Training envelopes/snapshots use far fewer members, and canonical
    # Training snapshot field names are already bounded to 128 characters.
    if len(pairs) > MAX_TRAINING_PROGRESS_JSON_OBJECT_MEMBERS:
        raise TrainingProgressResourceError(
            "training progress JSON object contains too many members"
        )
    result: dict[str, Any] = {}
    for key, value in pairs:
        if len(key) > MAX_TRAINING_PROGRESS_JSON_KEY_CHARS:
            raise TrainingProgressResourceError(
                "training progress JSON object key exceeds the resource limit"
            )
        if key in result:
            raise ValueError("training progress contains duplicate JSON object keys")
        result[key] = value
    return result


def _windows_open_no_reparse(
    path: Path,
    *,
    create: bool,
    writable: bool = False,
    exclusive: bool = False,
) -> int:
    """Open one Windows disk file without following a reparse point.

    ``FILE_FLAG_OPEN_REPARSE_POINT`` makes the opened handle, not a prior pathname
    observation, authoritative.  Read-only handles share only concurrent reads so
    another process cannot mutate or replace the authenticated object while its
    bytes are being consumed.  Create/write handles retain the broader sharing
    required by the existing publication and durability paths.
    """

    import ctypes
    from ctypes import wintypes
    import msvcrt

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    CREATE_NEW = 1
    OPEN_EXISTING = 3
    OPEN_ALWAYS = 4
    FILE_ATTRIBUTE_NORMAL = 0x00000080
    FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    FILE_TYPE_DISK = 0x0001
    FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
    ERROR_FILE_NOT_FOUND = 2
    ERROR_PATH_NOT_FOUND = 3
    ERROR_FILE_EXISTS = 80
    ERROR_ALREADY_EXISTS = 183

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

    if exclusive and not create:
        raise ValueError("exclusive open requires create=True")
    share_mode = FILE_SHARE_READ
    if create or writable:
        share_mode |= FILE_SHARE_WRITE | FILE_SHARE_DELETE
    handle = create_file(
        str(path),
        GENERIC_READ | (GENERIC_WRITE if create or writable else 0),
        share_mode,
        None,
        CREATE_NEW if exclusive else (OPEN_ALWAYS if create else OPEN_EXISTING),
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
        if exclusive and error in {ERROR_FILE_EXISTS, ERROR_ALREADY_EXISTS}:
            raise FileExistsError(
                error,
                "training progress storage already exists",
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

        flags = os.O_RDWR if create or writable else os.O_RDONLY
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        descriptor = msvcrt.open_osfhandle(int(handle), flags)
        transferred = True
        return descriptor
    finally:
        if not transferred:
            close_handle(handle)


def _open_no_reparse(
    path: Path,
    *,
    create: bool,
    writable: bool = False,
    exclusive: bool = False,
) -> int:
    if exclusive and not create:
        raise ValueError("exclusive open requires create=True")
    if os.name == "nt":
        return _windows_open_no_reparse(
            path,
            create=create,
            writable=writable,
            exclusive=exclusive,
        )

    flags = os.O_RDWR if create or writable else os.O_RDONLY
    if create:
        flags |= os.O_CREAT
        if exclusive:
            flags |= os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags, 0o600) if create else os.open(path, flags)


_MOVEFILE_REPLACE_EXISTING = 0x00000001
_MOVEFILE_WRITE_THROUGH = 0x00000008


def _windows_replace_write_through(source: Path, destination: Path) -> None:
    """Atomically replace one Training-progress file with Windows write-through."""

    import ctypes

    move_file_ex = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    move_file_ex.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    )
    move_file_ex.restype = ctypes.c_int
    if not move_file_ex(
        os.fspath(source),
        os.fspath(destination),
        _MOVEFILE_REPLACE_EXISTING | _MOVEFILE_WRITE_THROUGH,
    ):
        error_code = ctypes.get_last_error()
        raise OSError(
            error_code,
            f"durable Windows Training-progress replacement failed (Win32 {error_code})",
            os.fspath(destination),
        )


def _replace_published_path(source: Path, destination: Path) -> None:
    """Publish one prepared Training-progress file with platform durability intent."""

    if os.name == "nt":
        _windows_replace_write_through(source, destination)
        return
    os.replace(source, destination)


def _sync_published_path(path: Path) -> None:
    """Confirm the published Training-progress namespace entry reached stable storage."""

    if os.name == "nt":
        # Re-open the published file through the same no-reparse authority used
        # by reads/locks. A path swap after atomic publication must not redirect
        # the durability barrier through a junction/symlink-like reparse point.
        descriptor = _open_no_reparse(path, create=False, writable=True)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return

    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    directory_fd = os.open(os.fspath(path.parent), flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


class TrainingProgressStore:
    """Atomic single-exercise progress file with compare-and-swap updates."""

    def __init__(self, path: str | Path) -> None:
        if not isinstance(path, (str, Path)):
            raise TypeError("path must be a filesystem path")
        configured = Path(path).expanduser()
        if str(configured) in {"", "."}:
            raise ValueError("path must identify a progress file")
        # Bind relative inputs to the exact construction-time location without
        # resolving symlinks/reparse points.  Later CWD changes must not silently
        # redirect persistent Training authority.
        self.path = Path(os.path.abspath(os.fspath(configured)))
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")
        self._active_storage_directory_identity: os.stat_result | None = None
        self._active_lock_descriptor: int | None = None

    @staticmethod
    def _same_file_identity(first: os.stat_result, second: os.stat_result) -> bool:
        try:
            return os.path.samestat(first, second)
        except (AttributeError, OSError):
            return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)

    def _storage_path_component_identities(
        self,
        *,
        allow_missing: bool,
    ) -> tuple[tuple[Path, os.stat_result], ...]:
        """Return identity-bound lexical directory components, rejecting redirects."""

        parent = self.path.parent
        anchor = parent.anchor
        if not anchor:
            raise ValueError("training progress storage path is not absolute")

        components: list[Path] = [Path(anchor)]
        current = Path(anchor)
        parts = parent.parts
        start = 1 if parts and parts[0] == anchor else 0
        for part in parts[start:]:
            current = current / part
            components.append(current)

        identities: list[tuple[Path, os.stat_result]] = []
        for component in components:
            try:
                metadata = os.lstat(component)
            except FileNotFoundError:
                if allow_missing:
                    return tuple(identities)
                raise ValueError(
                    "training progress storage directory is unavailable"
                ) from None
            except OSError as exc:
                raise ValueError(
                    "training progress storage directory is unavailable"
                ) from exc
            if (
                stat.S_ISLNK(metadata.st_mode)
                or _is_reparse_point(metadata)
                or not stat.S_ISDIR(metadata.st_mode)
            ):
                raise ValueError(
                    "training progress storage directory path contains redirected directory"
                )
            identities.append((component, metadata))
        return tuple(identities)

    def _require_storage_directory(
        self,
        expected_identity: os.stat_result | None = None,
        *,
        missing_ok: bool = False,
    ) -> os.stat_result | None:
        """Require and optionally identity-bind the configured storage parent."""

        identities = self._storage_path_component_identities(
            allow_missing=missing_ok and expected_identity is None
        )
        if not identities or identities[-1][0] != self.path.parent:
            if missing_ok and expected_identity is None:
                return None
            raise ValueError("training progress storage directory is unavailable")
        metadata = identities[-1][1]
        if (
            expected_identity is not None
            and not self._same_file_identity(expected_identity, metadata)
        ):
            raise ValueError(
                "training progress storage directory changed during the transaction"
            )
        return metadata

    def _bound_storage_directory(self, *, missing_ok: bool) -> os.stat_result | None:
        active = self._active_storage_directory_identity
        if active is not None:
            return self._require_storage_directory(active)
        return self._require_storage_directory(missing_ok=missing_ok)

    @staticmethod
    def _require_regular_progress(metadata: os.stat_result) -> None:
        if (
            stat.S_ISLNK(metadata.st_mode)
            or _is_reparse_point(metadata)
            or not stat.S_ISREG(metadata.st_mode)
        ):
            raise ValueError("training progress storage is not a regular file")
        if int(getattr(metadata, "st_nlink", 1)) != 1:
            raise ValueError("training progress storage is not private")

    @staticmethod
    def _require_private_temp(metadata: os.stat_result) -> None:
        if (
            stat.S_ISLNK(metadata.st_mode)
            or _is_reparse_point(metadata)
            or not stat.S_ISREG(metadata.st_mode)
            or int(getattr(metadata, "st_nlink", 1)) != 1
        ):
            raise ValueError("training progress temporary file is not private")

    def _progress_path_identity(self, *, missing_ok: bool) -> os.stat_result | None:
        """Return the current private progress inode identity, or a stable missing state."""
        try:
            metadata = os.lstat(self.path)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise ValueError("training progress file is unavailable") from None
        except OSError as exc:
            raise ValueError("training progress file could not be inspected") from exc
        self._require_regular_progress(metadata)
        return metadata

    @classmethod
    def _quarantine_owned_path(
        cls,
        path: Path,
        expected: os.stat_result | None,
        *,
        lock_file: bool,
    ) -> None:
        """Vacate an owned pathname without check-then-unlink deletion."""
        if expected is None:
            return
        validator = cls._require_regular_lock if lock_file else cls._require_private_temp
        try:
            current = os.lstat(path)
            validator(current)
        except (FileNotFoundError, OSError, ValueError, TrainingProgressBusyError):
            return
        if not cls._same_file_identity(expected, current):
            return

        quarantine: Path | None = None
        for _ in range(8):
            candidate = path.parent / (
                f".{path.name}.cleanup-quarantine-{secrets.token_hex(8)}"
            )
            try:
                os.lstat(candidate)
            except FileNotFoundError:
                quarantine = candidate
                break
            except OSError:
                return
        if quarantine is None:
            return
        try:
            os.replace(path, quarantine)
        except OSError:
            return
        try:
            moved = os.lstat(quarantine)
            validator(moved)
        except (FileNotFoundError, OSError, ValueError, TrainingProgressBusyError):
            return
        # Retain quarantine even when it is still our inode. A second
        # check-then-unlink would recreate the substitution race.
        if not cls._same_file_identity(expected, moved):
            return

    def _require_active_lock(self) -> None:
        descriptor = self._active_lock_descriptor
        if descriptor is not None:
            self._require_lock_descriptor_current(descriptor)

    def _read_progress_bytes(self, *, missing_ok: bool) -> bytes | None:
        directory_identity = self._bound_storage_directory(missing_ok=missing_ok)
        if directory_identity is None:
            return None
        self._require_active_lock()
        try:
            before = os.lstat(self.path)
        except FileNotFoundError:
            before = None
        except OSError as exc:
            raise ValueError("training progress file could not be inspected") from exc
        if before is not None:
            self._require_regular_progress(before)
            if before.st_size > MAX_TRAINING_PROGRESS_BYTES:
                raise TrainingProgressResourceError(
                    "training progress file exceeds the resource limit"
                )
        try:
            descriptor = _open_no_reparse(self.path, create=False)
        except FileNotFoundError:
            self._require_storage_directory(directory_identity)
            self._require_active_lock()
            # A pathname that existed at the pre-open inspection must not be
            # reclassified as an ordinary missing file if it disappears in the
            # lstat -> open window. That is a namespace race and must fail
            # closed before callers can treat the store as a clean first run.
            if before is not None:
                raise ValueError(
                    "training progress storage changed while being opened"
                ) from None
            if missing_ok:
                return None
            raise ValueError("training progress file is unavailable")
        except OSError as exc:
            raise ValueError("training progress file could not be inspected") from exc

        try:
            opened = os.fstat(descriptor)
            self._require_regular_progress(opened)
            if opened.st_size > MAX_TRAINING_PROGRESS_BYTES:
                raise TrainingProgressResourceError(
                    "training progress file exceeds the resource limit"
                )
            if before is None:
                # A file that appears after the pre-open missing snapshot is a
                # namespace race, not authoritative progress. Reject it before
                # any bytes can be interpreted as a valid resumed session.
                raise ValueError(
                    "training progress storage changed while being opened"
                )
            if not self._same_file_identity(before, opened):
                raise ValueError("training progress storage changed while being opened")
            try:
                after_open = os.lstat(self.path)
            except OSError as exc:
                raise ValueError(
                    "training progress storage changed while being opened"
                ) from exc
            self._require_regular_progress(after_open)
            if not self._same_file_identity(opened, after_open):
                raise ValueError("training progress storage changed while being opened")

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

            if os.name == "nt":
                os.lseek(descriptor, 0, os.SEEK_SET)
                confirmed_chunks: list[bytes] = []
                remaining = MAX_TRAINING_PROGRESS_BYTES + 1
                while remaining:
                    chunk = os.read(descriptor, min(64 * 1024, remaining))
                    if not chunk:
                        break
                    confirmed_chunks.append(chunk)
                    remaining -= len(chunk)
                if b"".join(confirmed_chunks) != data:
                    raise ValueError("training progress storage changed while being read")

            final_metadata = os.fstat(descriptor)
            cross_descriptor_changed = (
                not self._same_file_identity(opened, final_metadata)
                or final_metadata.st_size != opened.st_size
                or getattr(final_metadata, "st_mtime_ns", None)
                != getattr(opened, "st_mtime_ns", None)
                or getattr(final_metadata, "st_ctime_ns", None)
                != getattr(opened, "st_ctime_ns", None)
            )
            if cross_descriptor_changed:
                raise ValueError("training progress storage changed while being read")
            try:
                after_read = os.lstat(self.path)
            except OSError as exc:
                raise ValueError(
                    "training progress storage changed while being read"
                ) from exc
            self._require_regular_progress(after_read)
            cross_interface_ctime_changed = (
                os.name != "nt"
                and getattr(after_read, "st_ctime_ns", None)
                != getattr(final_metadata, "st_ctime_ns", None)
            )
            if (
                not self._same_file_identity(opened, after_read)
                or after_read.st_size != final_metadata.st_size
                or getattr(after_read, "st_mtime_ns", None)
                != getattr(final_metadata, "st_mtime_ns", None)
                or cross_interface_ctime_changed
            ):
                raise ValueError("training progress storage changed while being read")
            self._require_storage_directory(directory_identity)
            self._require_active_lock()
            return data
        except OSError as exc:
            raise ValueError("training progress file could not be read") from exc
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass

    def load(self, definition: ExerciseDefinition) -> LoadedTrainingProgress | None:
        # Durable Training progress is bound to one canonical authored
        # ExerciseDefinition. Reject subclasses before storage I/O or any
        # overridable definition attribute can participate in restore.
        if type(definition) is not ExerciseDefinition:
            raise TypeError("definition must be an ExerciseDefinition")
        data = self._read_progress_bytes(missing_ok=True)
        if data is None:
            return None
        try:
            payload = json.loads(
                data.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_object_pairs,
            )
        except RecursionError as exc:
            raise TrainingProgressResourceError(
                "training progress JSON nesting depth exceeds the resource limit"
            ) from exc
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
        # json.loads() produces a built-in dict here. Do not widen this disk
        # boundary back to active Mapping providers before canonical restore.
        if type(snapshot) is not dict:
            raise TypeError("training progress snapshot must be a mapping")
        session = ExerciseSession.restore(definition, snapshot)
        return LoadedTrainingProgress(session=session, revision=_revision(data))

    @staticmethod
    def _require_regular_lock(metadata: os.stat_result) -> None:
        if (
            stat.S_ISLNK(metadata.st_mode)
            or _is_reparse_point(metadata)
            or not stat.S_ISREG(metadata.st_mode)
            or int(getattr(metadata, "st_nlink", 1)) != 1
        ):
            raise TrainingProgressBusyError("training progress store is busy")

    def _require_lock_descriptor_current(self, descriptor: int) -> None:
        try:
            metadata = os.fstat(descriptor)
            current_path = os.lstat(self._lock_path)
        except OSError as exc:
            raise TrainingProgressBusyError("training progress store is busy") from exc
        self._require_regular_lock(metadata)
        self._require_regular_lock(current_path)
        if (
            not self._same_file_identity(metadata, current_path)
            or metadata.st_size != 1
        ):
            raise TrainingProgressBusyError("training progress store is busy")
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            marker = os.read(descriptor, 2)
        except OSError as exc:
            raise TrainingProgressBusyError("training progress store is busy") from exc
        if marker != b"\0":
            raise TrainingProgressBusyError("training progress store is busy")

    def _open_lock_descriptor(
        self,
        *,
        expected_directory_identity: os.stat_result | None = None,
    ) -> int:
        if expected_directory_identity is not None:
            self._require_storage_directory(expected_directory_identity)

        descriptor = -1
        existing: os.stat_result | None = None
        initializing_identity: os.stat_result | None = None
        for attempt in range(250):
            try:
                existing = os.lstat(self._lock_path)
            except FileNotFoundError:
                existing = None
            except OSError as exc:
                raise TrainingProgressBusyError(
                    "training progress store is busy"
                ) from exc
            if existing is not None:
                self._require_regular_lock(existing)
                if (
                    initializing_identity is not None
                    and not self._same_file_identity(initializing_identity, existing)
                ):
                    raise TrainingProgressBusyError("training progress store is busy")
                if existing.st_size == 0:
                    if initializing_identity is None:
                        initializing_identity = existing
                    if attempt == 249:
                        raise TrainingProgressBusyError(
                            "training progress store is busy"
                        )
                    time.sleep(0.002)
                    continue

            if expected_directory_identity is not None:
                self._require_storage_directory(expected_directory_identity)
            try:
                if existing is None:
                    descriptor = _open_no_reparse(
                        self._lock_path,
                        create=True,
                        writable=True,
                        exclusive=True,
                    )
                else:
                    descriptor = _open_no_reparse(
                        self._lock_path,
                        create=False,
                        writable=True,
                    )
                break
            except FileExistsError:
                if attempt == 249:
                    raise TrainingProgressBusyError(
                        "training progress store is busy"
                    ) from None
                time.sleep(0.002)
                continue
            except OSError as exc:
                raise TrainingProgressBusyError(
                    "training progress store is busy"
                ) from exc

        if descriptor < 0:
            raise TrainingProgressBusyError("training progress store is busy")

        created_identity: os.stat_result | None = None
        try:
            metadata = os.fstat(descriptor)
            self._require_regular_lock(metadata)
            if existing is None:
                created_identity = metadata
            elif not self._same_file_identity(existing, metadata):
                raise TrainingProgressBusyError("training progress store is busy")

            try:
                current_path = os.lstat(self._lock_path)
            except OSError as exc:
                raise TrainingProgressBusyError(
                    "training progress store is busy"
                ) from exc
            self._require_regular_lock(current_path)
            if not self._same_file_identity(metadata, current_path):
                raise TrainingProgressBusyError("training progress store is busy")

            if existing is None:
                current_descriptor = os.fstat(descriptor)
                self._require_regular_lock(current_descriptor)
                if (
                    current_descriptor.st_size != 0
                    or not self._same_file_identity(metadata, current_descriptor)
                ):
                    raise TrainingProgressBusyError("training progress store is busy")
                try:
                    written = os.write(descriptor, b"\0")
                    if written != 1:
                        raise OSError("short Training-progress lock marker write")
                    os.fsync(descriptor)
                except OSError as exc:
                    raise TrainingProgressBusyError(
                        "training progress store is busy"
                    ) from exc
                initialized = os.fstat(descriptor)
                self._require_regular_lock(initialized)
                if (
                    initialized.st_size != 1
                    or not self._same_file_identity(metadata, initialized)
                ):
                    raise TrainingProgressBusyError("training progress store is busy")
            else:
                if metadata.st_size != 1:
                    raise TrainingProgressBusyError("training progress store is busy")
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    marker = os.read(descriptor, 2)
                except OSError as exc:
                    raise TrainingProgressBusyError(
                        "training progress store is busy"
                    ) from exc
                if marker != b"\0":
                    raise TrainingProgressBusyError("training progress store is busy")

            try:
                final_path = os.lstat(self._lock_path)
            except OSError as exc:
                raise TrainingProgressBusyError(
                    "training progress store is busy"
                ) from exc
            self._require_regular_lock(final_path)
            if not self._same_file_identity(metadata, final_path):
                raise TrainingProgressBusyError("training progress store is busy")
            if expected_directory_identity is not None:
                self._require_storage_directory(expected_directory_identity)
            return descriptor
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            if existing is None:
                self._quarantine_owned_path(
                    self._lock_path,
                    created_identity,
                    lock_file=True,
                )
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
        # Bind every existing component before mkdir so a swap to a different
        # ordinary directory is detected as well as a symlink/reparse redirect.
        preexisting_components = self._storage_path_component_identities(
            allow_missing=True
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        directory_identity = self._require_storage_directory()
        assert directory_identity is not None
        for component, expected_identity in preexisting_components:
            try:
                current_identity = os.lstat(component)
            except OSError as exc:
                raise ValueError(
                    "training progress storage directory changed during the transaction"
                ) from exc
            if (
                stat.S_ISLNK(current_identity.st_mode)
                or _is_reparse_point(current_identity)
                or not stat.S_ISDIR(current_identity.st_mode)
                or not self._same_file_identity(expected_identity, current_identity)
            ):
                raise ValueError(
                    "training progress storage directory changed during the transaction"
                )
        descriptor = self._open_lock_descriptor(
            expected_directory_identity=directory_identity
        )
        acquired = False
        previous_directory_identity = self._active_storage_directory_identity
        previous_lock_descriptor = self._active_lock_descriptor
        try:
            self._lock_descriptor(descriptor)
            acquired = True
            self._require_lock_descriptor_current(descriptor)
            self._require_storage_directory(directory_identity)
            self._active_storage_directory_identity = directory_identity
            self._active_lock_descriptor = descriptor
            yield
            self._require_active_lock()
            self._require_storage_directory(directory_identity)
        finally:
            self._active_lock_descriptor = previous_lock_descriptor
            self._active_storage_directory_identity = previous_directory_identity
            if acquired:
                self._unlock_descriptor(descriptor)
            try:
                os.close(descriptor)
            except OSError:
                pass

    def save(
        self,
        session: ExerciseSession,
        *,
        expected_revision: str | None,
    ) -> str:
        # Saving durable progress must snapshot the canonical Training session,
        # not a provider-defined subclass with overridable snapshot/state hooks.
        if type(session) is not ExerciseSession:
            raise TypeError("session must be an ExerciseSession")
        expected = _validate_revision(expected_revision)

        temporary: Path | None = None
        temporary_identity: os.stat_result | None = None
        with self._exclusive_access():
            try:
                transaction_identity = self._progress_path_identity(missing_ok=True)
                current_data = self._read_progress_bytes(missing_ok=True)
                observed_identity = self._progress_path_identity(missing_ok=True)
                if (
                    (transaction_identity is None) != (current_data is None)
                    or (observed_identity is None) != (current_data is None)
                ):
                    raise TrainingProgressConflictError(
                        "training progress changed since the caller last observed it"
                    )
                if transaction_identity is not None:
                    if (
                        observed_identity is None
                        or not self._same_file_identity(
                            transaction_identity,
                            observed_identity,
                        )
                    ):
                        raise TrainingProgressConflictError(
                            "training progress changed since the caller last observed it"
                        )
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

                # An identical canonical payload can elide the physical rewrite
                # only after a final transaction-level CAS. Snapshot generation
                # is caller-controlled work and may take long enough for a
                # non-cooperating writer to replace canonical storage.
                if current_data == data:
                    no_op_data = self._read_progress_bytes(missing_ok=True)
                    no_op_identity = self._progress_path_identity(missing_ok=True)
                    if (
                        no_op_data != current_data
                        or transaction_identity is None
                        or no_op_identity is None
                        or not self._same_file_identity(
                            transaction_identity,
                            no_op_identity,
                        )
                    ):
                        raise TrainingProgressConflictError(
                            "training progress changed during no-op save"
                        )
                    return new_revision

                active_directory = self._active_storage_directory_identity
                assert active_directory is not None
                self._require_storage_directory(active_directory)
                fd, raw_path = tempfile.mkstemp(
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                    dir=str(self.path.parent),
                )
                temporary = Path(raw_path)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        created_identity = os.fstat(handle.fileno())
                        temporary_identity = created_identity
                        self._require_private_temp(created_identity)
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                        final_temp_identity = os.fstat(handle.fileno())
                        self._require_private_temp(final_temp_identity)
                        if not self._same_file_identity(
                            created_identity,
                            final_temp_identity,
                        ):
                            raise ValueError(
                                "training progress temporary file changed while being prepared"
                            )
                        temporary_identity = final_temp_identity
                    self._require_storage_directory(active_directory)
                    self._require_active_lock()
                except Exception:
                    raise

                publication_base = self._read_progress_bytes(missing_ok=True)
                publication_identity = self._progress_path_identity(missing_ok=True)
                publication_revision = (
                    None if publication_base is None else _revision(publication_base)
                )
                if (
                    publication_revision != current_revision
                    or publication_base != current_data
                    or (transaction_identity is None) != (publication_base is None)
                    or (publication_identity is None) != (publication_base is None)
                ):
                    raise TrainingProgressConflictError(
                        "training progress changed during publication"
                    )
                if transaction_identity is not None:
                    if (
                        publication_identity is None
                        or not self._same_file_identity(
                            transaction_identity,
                            publication_identity,
                        )
                    ):
                        raise TrainingProgressConflictError(
                            "training progress changed during publication"
                        )

                try:
                    current_temp = os.lstat(temporary)
                except OSError as exc:
                    raise ValueError(
                        "training progress temporary file changed before publication"
                    ) from exc
                self._require_private_temp(current_temp)
                if (
                    temporary_identity is None
                    or not self._same_file_identity(
                        temporary_identity,
                        current_temp,
                    )
                ):
                    raise ValueError(
                        "training progress temporary file changed before publication"
                    )

                self._require_storage_directory(active_directory)
                self._require_active_lock()
                pre_replace_identity = self._progress_path_identity(missing_ok=True)
                if (
                    (transaction_identity is None)
                    != (pre_replace_identity is None)
                    or (
                        transaction_identity is not None
                        and pre_replace_identity is not None
                        and not self._same_file_identity(
                            transaction_identity,
                            pre_replace_identity,
                        )
                    )
                ):
                    raise TrainingProgressConflictError(
                        "training progress changed during publication"
                    )
                _replace_published_path(temporary, self.path)
                temporary = None

                # From this point the canonical pathname has been atomically
                # replaced. Any later failure is not a pre-commit conflict:
                # callers must assume the new bytes may already be visible and
                # reconcile from canonical storage instead of rolling memory
                # back to the stale pre-command snapshot.
                try:
                    # A successful acknowledgement is bound to the exact fsynced
                    # temp inode, not merely to equivalent bytes at the canonical
                    # pathname. This closes same-byte substitution around the
                    # durability barrier.
                    self._require_active_lock()
                    published_identity = os.lstat(self.path)
                    self._require_regular_progress(published_identity)
                    if (
                        temporary_identity is None
                        or not self._same_file_identity(
                            temporary_identity,
                            published_identity,
                        )
                    ):
                        raise TrainingProgressConflictError(
                            "training progress changed after publication"
                        )

                    self._require_storage_directory(active_directory)
                    _sync_published_path(self.path)
                    self._require_storage_directory(active_directory)
                    self._require_active_lock()
                    visible = self._read_progress_bytes(missing_ok=False)
                    final_published_identity = os.lstat(self.path)
                    self._require_regular_progress(final_published_identity)
                    if (
                        temporary_identity is None
                        or not self._same_file_identity(
                            temporary_identity,
                            final_published_identity,
                        )
                        or visible != data
                    ):
                        raise TrainingProgressConflictError(
                            "training progress changed after publication"
                        )
                except Exception as exc:
                    raise TrainingProgressDurabilityUnknownError(
                        "training progress was published but durable canonical storage could not be confirmed",
                        published_revision=new_revision,
                    ) from exc
                return new_revision
            finally:
                if temporary is not None:
                    self._quarantine_owned_path(
                        temporary,
                        temporary_identity,
                        lock_file=False,
                    )
