from __future__ import annotations

"""Durable persistence for semantic :class:`BookReader` progress.

The store deliberately persists only the already-versioned ``BookReader``
snapshot contract. It does not parse chess, inspect source files, derive book
identity from a local path, or project persistence details into the UI.

A caller supplies an opaque stable ``book_key`` (for example a Library identity
or an importer provenance digest). The key is data inside one store file, never
a filename, so hostile keys cannot escape the configured application-data path.

Version 2 adds a monotonic store generation plus process-wide and interprocess
serialization. Version-1 store files are read losslessly and are upgraded on the
next successful mutation; reader snapshot semantics remain owned by BookReader.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import secrets
import threading
import time
from typing import Any

from .bookdocument import BookDocument
from .bookreader import BookReader


BOOK_PROGRESS_STORE_SCHEMA_VERSION = 2
LEGACY_BOOK_PROGRESS_STORE_SCHEMA_VERSION = 1
MAX_BOOK_PROGRESS_ENTRIES = 4096
MAX_BOOK_KEY_CHARS = 256
MAX_BOOK_PROGRESS_JSON_KEY_CHARS = 4096
MAX_BOOK_SNAPSHOT_BYTES = 1 * 1024 * 1024
MAX_BOOK_PROGRESS_STORE_BYTES = 8 * 1024 * 1024
MAX_BOOK_PROGRESS_GENERATION = (1 << 63) - 1
_MAX_BOOK_PROGRESS_JSON_OBJECT_MEMBERS = MAX_BOOK_PROGRESS_ENTRIES

_STORE_V1_FIELDS = frozenset({"schema_version", "entries"})
_STORE_V2_FIELDS = frozenset({"schema_version", "generation", "entries"})
_READER_SNAPSHOT_FIELDS = frozenset(
    {"schema_version", "current_target", "return_points", "fallback_digests"}
)

_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_EXPECTED_TARGET_UNSET = object()
_EXPECTED_IDENTITY_UNSET = object()


class BookProgressStoreErrorCode(str, Enum):
    INVALID_ARGUMENT = "invalid_argument"
    CORRUPT_STORE = "corrupt_store"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    RESOURCE_LIMIT = "resource_limit"
    IO_FAILURE = "io_failure"
    DURABILITY_UNKNOWN = "durability_unknown"
    STALE_WRITE = "stale_write"


class BookProgressStoreError(ValueError):
    """Stable persistence failure without local path disclosure in its message."""

    def __init__(self, message: str, *, code: BookProgressStoreErrorCode) -> None:
        super().__init__(message)
        self.code = BookProgressStoreErrorCode(code)


_MOVEFILE_REPLACE_EXISTING = 0x00000001
_MOVEFILE_WRITE_THROUGH = 0x00000008


def _windows_replace_write_through(source: Path, destination: Path) -> None:
    """Atomically replace one Book-progress file with Windows write-through."""

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
            f"durable Windows Book-progress replacement failed (Win32 {error_code})",
            os.fspath(destination),
        )


def _replace_published_path(source: Path, destination: Path) -> None:
    """Publish one prepared file with platform durability intent."""

    if os.name == "nt":
        _windows_replace_write_through(source, destination)
        return
    os.replace(source, destination)


def _windows_open_existing_writable_no_reparse(path: Path) -> int:
    """Open an existing Windows disk file read/write without following reparse points."""

    import ctypes
    from ctypes import wintypes
    import msvcrt

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    OPEN_EXISTING = 3
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
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid:
        error = ctypes.get_last_error()
        if error in {ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND}:
            raise FileNotFoundError(
                error,
                "could not open book progress storage",
                str(path),
            )
        raise OSError(error, "could not open book progress storage")

    transferred = False
    try:
        if get_file_type(handle) != FILE_TYPE_DISK:
            raise OSError("book progress storage is not a disk file")
        info = FILE_ATTRIBUTE_TAG_INFO()
        if not get_info(
            handle,
            FILE_ATTRIBUTE_TAG_INFO_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            error = ctypes.get_last_error()
            raise OSError(error, "could not inspect opened book progress storage")
        if info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError("book progress storage is a reparse point")

        flags = os.O_RDWR
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        descriptor = msvcrt.open_osfhandle(int(handle), flags)
        transferred = True
        return descriptor
    finally:
        if not transferred:
            close_handle(handle)


def _sync_published_path(path: Path) -> None:
    """Confirm the published namespace entry reached stable storage."""

    if os.name == "nt":
        # MoveFileExW above requests write-through for the namespace move. Reopen
        # the exact namespace entry without following a junction/symlink-like
        # reparse point, while retaining the write access FlushFileBuffers needs.
        descriptor = _windows_open_existing_writable_no_reparse(path)
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


def _book_key(value: object) -> str:
    if type(value) is not str:
        raise BookProgressStoreError(
            "book progress key must be text",
            code=BookProgressStoreErrorCode.INVALID_ARGUMENT,
        )
    if not value or value != value.strip():
        raise BookProgressStoreError(
            "book progress key must be non-empty canonical text",
            code=BookProgressStoreErrorCode.INVALID_ARGUMENT,
        )
    if (
        len(value) > MAX_BOOK_KEY_CHARS
        or any(
            ord(character) < 32
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in value
        )
    ):
        raise BookProgressStoreError(
            "book progress key is outside the supported bounds",
            code=BookProgressStoreErrorCode.INVALID_ARGUMENT,
        )
    return value


def _reject_duplicate_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    # object_pairs_hook receives the parser's unhashed pair list. Bound its
    # cardinality before the first membership test/insertion so an 8 MiB JSON
    # object containing tens of thousands of tiny unique keys cannot amplify
    # into unbounded hash work. The widest legitimate object is the entries map.
    if len(pairs) > _MAX_BOOK_PROGRESS_JSON_OBJECT_MEMBERS:
        raise BookProgressStoreError(
            "book progress JSON object contains too many members",
            code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
        )
    result: dict[str, Any] = {}
    for key, value in pairs:
        # json's object_pairs_hook receives an unhashed sequence of pairs.
        # Enforce a scalar bound before the first dict membership/insertion so a
        # malformed file cannot make duplicate detection hash an arbitrarily
        # large object key first. Legitimate BookReader target keys are already
        # bounded to 4096 characters, while book keys are stricter (256).
        if len(key) > MAX_BOOK_PROGRESS_JSON_KEY_CHARS:
            raise BookProgressStoreError(
                "book progress JSON object key exceeds the resource limit",
                code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
            )
        if key in result:
            raise BookProgressStoreError(
                "book progress store contains duplicate JSON object keys",
                code=BookProgressStoreErrorCode.CORRUPT_STORE,
            )
        result[key] = value
    return result


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise BookProgressStoreError(
            "book progress data is not valid JSON data",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        ) from None


def _snapshot_copy(value: object) -> dict[str, object]:
    # Persisted snapshots are JSON objects and must cross this boundary as exact
    # built-in dictionaries.  Reject Mapping subclasses before iteration so
    # provider-defined hooks cannot execute inside progress validation.
    if type(value) is not dict:
        raise BookProgressStoreError(
            "book progress snapshot must be an object",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        )
    snapshot_fields = tuple(value)
    if any(type(field) is not str for field in snapshot_fields):
        raise BookProgressStoreError(
            "book progress snapshot has invalid field names",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        )
    if set(snapshot_fields) != _READER_SNAPSHOT_FIELDS:
        raise BookProgressStoreError(
            "book progress snapshot has unsupported fields",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        )
    snapshot = value.copy()
    try:
        validated = BookReader.validate_snapshot_contract(snapshot)
    except (TypeError, ValueError):
        raise BookProgressStoreError(
            "book progress snapshot is corrupt",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        ) from None
    # Size the already-passive validated snapshot. Serializing before nested
    # validation would let a dict subclass in return_points/fallback_digests
    # execute provider-defined items()/iteration hooks inside json.dumps.
    if len(_canonical_json_bytes(validated)) > MAX_BOOK_SNAPSHOT_BYTES:
        raise BookProgressStoreError(
            "book progress snapshot exceeds the resource limit",
            code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
        )
    return validated


def _empty_payload() -> dict[str, object]:
    return {
        "schema_version": BOOK_PROGRESS_STORE_SCHEMA_VERSION,
        "generation": 0,
        "entries": {},
    }


def _validate_payload(value: object) -> dict[str, object]:
    # The JSON decoder and all store-owned payload builders produce exact dicts.
    # Keep ingress passive: arbitrary Mapping implementations may execute code
    # from membership, indexing, length, or iteration hooks.
    if type(value) is not dict:
        raise BookProgressStoreError(
            "book progress store root must be an object",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        )
    root_fields = tuple(value)
    if any(type(field) is not str for field in root_fields):
        raise BookProgressStoreError(
            "book progress store has invalid field names",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        )
    if "schema_version" not in value:
        raise BookProgressStoreError(
            "book progress store schema version is missing",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        )

    schema_version = value["schema_version"]
    if type(schema_version) is not int:
        raise BookProgressStoreError(
            "book progress store schema version must be an integer",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        )
    if schema_version not in {
        LEGACY_BOOK_PROGRESS_STORE_SCHEMA_VERSION,
        BOOK_PROGRESS_STORE_SCHEMA_VERSION,
    }:
        raise BookProgressStoreError(
            "book progress store schema version is unsupported",
            code=BookProgressStoreErrorCode.UNSUPPORTED_SCHEMA,
        )

    if "entries" not in value:
        raise BookProgressStoreError(
            "book progress entries are missing",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        )
    raw_entries = value["entries"]
    if type(raw_entries) is not dict:
        raise BookProgressStoreError(
            "book progress entries must be an object",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        )
    if len(raw_entries) > MAX_BOOK_PROGRESS_ENTRIES:
        raise BookProgressStoreError(
            "book progress store contains too many books",
            code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
        )

    entries: dict[str, dict[str, object]] = {}
    for raw_key, raw_snapshot in raw_entries.items():
        try:
            key = _book_key(raw_key)
        except BookProgressStoreError as exc:
            raise BookProgressStoreError(
                "book progress store contains an invalid book key",
                code=BookProgressStoreErrorCode.CORRUPT_STORE,
            ) from exc
        entries[key] = _snapshot_copy(raw_snapshot)

    expected_fields = _STORE_V1_FIELDS if schema_version == 1 else _STORE_V2_FIELDS
    if set(root_fields) != expected_fields:
        raise BookProgressStoreError(
            "book progress store has unsupported fields",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        )

    if schema_version == LEGACY_BOOK_PROGRESS_STORE_SCHEMA_VERSION:
        generation = 0
    else:
        generation = value["generation"]
        if type(generation) is not int or not 0 <= generation <= MAX_BOOK_PROGRESS_GENERATION:
            raise BookProgressStoreError(
                "book progress store generation is invalid",
                code=BookProgressStoreErrorCode.CORRUPT_STORE,
            )

    return {
        "schema_version": BOOK_PROGRESS_STORE_SCHEMA_VERSION,
        "generation": generation,
        "entries": entries,
    }


def _is_reparse_point(metadata: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(flag and attributes & flag)


def _process_lock_for(path: Path) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_LOCKS[key] = lock
        return lock


def _revision(raw: bytes | None) -> str | None:
    if raw is None:
        return None
    return hashlib.sha256(raw).hexdigest()


class BookProgressStore:
    """Atomic, serialized JSON store for current BookReader locations/bookmarks.

    The configured path is an infrastructure concern supplied by the composition
    root. Exceptions intentionally omit that path so an accessibility adapter can
    safely present a concise message without leaking a local user directory.

    All writers for a canonical path share a process lock and an OS file lock.
    The lock is held across load/merge/backup/replace, so independent store
    instances and independent processes cannot both commit from the same base.
    A raw revision check immediately before publication additionally rejects an
    external stale-base change made by a non-cooperating writer.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        if not isinstance(path, (str, os.PathLike)):
            raise TypeError("book progress store path must be path-like")
        raw_path = os.fspath(path)
        if type(raw_path) is not str:
            raise TypeError("book progress store path must resolve to text")
        if not raw_path or "\x00" in raw_path:
            raise BookProgressStoreError(
                "book progress store path is invalid",
                code=BookProgressStoreErrorCode.INVALID_ARGUMENT,
            )
        # Bind relative configuration to the construction-time working
        # directory and collapse lexical dot-segments without resolving symlinks.
        # The process-lock key uses the same abspath normalization; keeping either
        # I/O relative or an uncollapsed "pivot/../file" path could otherwise let
        # a later chdir or a symlink pivot split lock authority from actual data.
        try:
            bound_path = Path(os.path.abspath(raw_path))
        except OSError:
            raise BookProgressStoreError(
                "book progress storage is unavailable",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from None
        if not bound_path.name:
            raise BookProgressStoreError(
                "book progress store path must name a file",
                code=BookProgressStoreErrorCode.INVALID_ARGUMENT,
            )
        self._path = bound_path
        self._process_lock = _process_lock_for(self._path)
        self._active_storage_directory_identity: os.stat_result | None = None
        self._active_lock_descriptor: int | None = None

    @property
    def path(self) -> Path:
        """Infrastructure-only configured path; presentation must not project it."""
        return self._path

    @property
    def backup_path(self) -> Path:
        """Infrastructure-only previous-valid snapshot used for bounded recovery."""
        return self._path.with_name(self._path.name + ".bak")

    @property
    def _lock_path(self) -> Path:
        return self._path.with_name(self._path.name + ".lock")

    @staticmethod
    def _require_regular_metadata(metadata: os.stat_result, *, message: str) -> None:
        if stat.S_ISLNK(metadata.st_mode) or _is_reparse_point(metadata) or not stat.S_ISREG(metadata.st_mode):
            raise BookProgressStoreError(message, code=BookProgressStoreErrorCode.IO_FAILURE)

    @classmethod
    def _require_private_lock_metadata(cls, metadata: os.stat_result) -> None:
        cls._require_regular_metadata(
            metadata,
            message="book progress storage lock is not a regular file",
        )
        if int(getattr(metadata, "st_nlink", 1)) != 1:
            raise BookProgressStoreError(
                "book progress storage lock is not private",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            )

    @classmethod
    def _require_private_temp_metadata(cls, metadata: os.stat_result) -> None:
        cls._require_regular_metadata(
            metadata,
            message="book progress temporary file is not a regular file",
        )
        if int(getattr(metadata, "st_nlink", 1)) != 1:
            raise BookProgressStoreError(
                "book progress temporary file is not private",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            )

    @classmethod
    def _require_private_data_metadata(cls, metadata: os.stat_result) -> None:
        cls._require_regular_metadata(
            metadata,
            message="book progress storage is not a regular file",
        )
        if int(getattr(metadata, "st_nlink", 1)) != 1:
            raise BookProgressStoreError(
                "book progress storage is not private",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            )

    @staticmethod
    def _same_file_identity(first: os.stat_result, second: os.stat_result) -> bool:
        """Return whether two metadata snapshots identify the same file object."""
        try:
            return os.path.samestat(first, second)
        except (AttributeError, OSError):
            return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)

    @classmethod
    def _quarantine_owned_cleanup_unlocked(
        cls,
        path: Path,
        expected: os.stat_result | None,
        *,
        lock_file: bool,
    ) -> None:
        """Vacate an owned cleanup pathname without a check-then-unlink race.

        Cleanup runs only on failed/abandoned publication paths.  Moving the
        candidate to a high-entropy same-directory quarantine makes the
        canonical temp/lock pathname reusable without ever unlinking after a
        pathname identity check.  The quarantine is intentionally retained:
        if a non-cooperating actor wins the final check->rename window, its
        bytes may be what moved.  Preserving rare residue is safer than a
        second destructive pathname operation.
        """
        if expected is None:
            return
        validator = (
            cls._require_private_lock_metadata
            if lock_file
            else cls._require_private_temp_metadata
        )
        try:
            current = os.lstat(path)
            validator(current)
        except (FileNotFoundError, OSError, BookProgressStoreError):
            return
        if not cls._same_file_identity(expected, current):
            return

        quarantine: Path | None = None
        for _ in range(8):
            candidate = path.parent / (
                f".{path.name}.cleanup-quarantine-{secrets.token_hex(8)}"
            )
            if candidate.exists() or candidate.is_symlink():
                continue
            quarantine = candidate
            break
        if quarantine is None:
            return

        try:
            os.replace(path, quarantine)
        except OSError:
            return

        try:
            moved = os.lstat(quarantine)
            validator(moved)
        except (FileNotFoundError, OSError, BookProgressStoreError):
            return
        # Do not unlink quarantine even when it is still our inode.  A second
        # pathname check followed by unlink would simply recreate the same
        # substitution race this helper exists to eliminate.
        if not cls._same_file_identity(expected, moved):
            return

    @classmethod
    def _discard_owned_temp_unlocked(
        cls,
        path: Path,
        expected: os.stat_result | None,
    ) -> None:
        """Vacate only a writer-owned temp pathname; never unlink by pathname."""
        cls._quarantine_owned_cleanup_unlocked(
            path,
            expected,
            lock_file=False,
        )

    @classmethod
    def _discard_owned_lock_unlocked(
        cls,
        path: Path,
        expected: os.stat_result | None,
    ) -> None:
        """Vacate only a failed writer-owned lock pathname safely."""
        cls._quarantine_owned_cleanup_unlocked(
            path,
            expected,
            lock_file=True,
        )

    def _read_raw_file_unlocked(self, path: Path, *, missing_ok: bool) -> bytes | None:
        """Read through the exact descriptor whose file identity was validated.

        The path is inspected before opening to reject symlinks/reparse points,
        then the opened descriptor and a post-open path snapshot must identify
        the same regular file.  Reads never reopen the path after validation.
        """
        self._require_active_lock_unlocked()
        active_directory = self._active_storage_directory_identity
        if active_directory is not None:
            self._require_storage_directory_unlocked(active_directory)
        try:
            before = os.lstat(path)
        except FileNotFoundError:
            before = None
        except OSError:
            raise BookProgressStoreError(
                "book progress storage is unavailable",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from None

        if before is not None:
            self._require_private_data_metadata(before)
            if before.st_size > MAX_BOOK_PROGRESS_STORE_BYTES:
                raise BookProgressStoreError(
                    "book progress store exceeds the resource limit",
                    code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
                )

        flags = os.O_RDONLY
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            # If this exact pathname existed at the pre-open inspection, its
            # disappearance is a namespace race, not an ordinary missing state.
            # Treating it as missing would let a read-only query or a writer's
            # load/CAS phase silently reclassify concurrent deletion as a clean
            # first run.
            if before is not None:
                raise BookProgressStoreError(
                    "book progress storage changed while being opened",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                ) from None
            if missing_ok:
                return None
            raise BookProgressStoreError(
                "book progress recovery data is unavailable",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            )
        except OSError:
            raise BookProgressStoreError(
                "book progress storage could not be read",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from None

        try:
            opened = os.fstat(descriptor)
            self._require_private_data_metadata(opened)
            if opened.st_size > MAX_BOOK_PROGRESS_STORE_BYTES:
                raise BookProgressStoreError(
                    "book progress store exceeds the resource limit",
                    code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
                )
            if before is None:
                # The canonical pathname was absent at the pre-open inspection,
                # so accepting a file that appeared before descriptor open would
                # let a non-cooperating namespace mutation inject authoritative
                # state into an operation that began from a missing snapshot.
                raise BookProgressStoreError(
                    "book progress storage changed while being opened",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                )
            if not self._same_file_identity(before, opened):
                raise BookProgressStoreError(
                    "book progress storage changed while being opened",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                )

            try:
                after_open = os.lstat(path)
            except OSError:
                raise BookProgressStoreError(
                    "book progress storage changed while being opened",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                ) from None
            self._require_private_data_metadata(after_open)
            if not self._same_file_identity(opened, after_open):
                raise BookProgressStoreError(
                    "book progress storage changed while being opened",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                )

            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(MAX_BOOK_PROGRESS_STORE_BYTES + 1)
                if len(raw) > MAX_BOOK_PROGRESS_STORE_BYTES:
                    raise BookProgressStoreError(
                        "book progress store exceeds the resource limit",
                        code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
                    )
                if os.name == "nt":
                    # Windows pathname-stat ctime cannot be compared reliably
                    # with descriptor fstat ctime. Confirm byte stability on the
                    # already-authenticated open descriptor instead, so a
                    # same-inode/same-size writer cannot hide an in-place change
                    # merely by restoring mtime during this read.
                    stream.seek(0)
                    confirmed_raw = stream.read(MAX_BOOK_PROGRESS_STORE_BYTES + 1)
                    if confirmed_raw != raw:
                        raise BookProgressStoreError(
                            "book progress storage changed while being read",
                            code=BookProgressStoreErrorCode.IO_FAILURE,
                        )
            final_metadata = os.fstat(descriptor)
            if (
                not self._same_file_identity(opened, final_metadata)
                or final_metadata.st_size != opened.st_size
                or getattr(final_metadata, "st_mtime_ns", None)
                != getattr(opened, "st_mtime_ns", None)
                or getattr(final_metadata, "st_ctime_ns", None)
                != getattr(opened, "st_ctime_ns", None)
            ):
                raise BookProgressStoreError(
                    "book progress storage changed while being read",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                )
            try:
                after_read = os.lstat(path)
            except OSError:
                raise BookProgressStoreError(
                    "book progress storage changed while being read",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                ) from None
            self._require_private_data_metadata(after_read)
            # Windows exposes incompatible/deprecated st_ctime semantics
            # between pathname stat and descriptor fstat.  Binding a stable read
            # to cross-interface ctime therefore turns valid publications into
            # false IO_FAILURE/DURABILITY_UNKNOWN results on Windows.  Keep the
            # portable identity/size/mtime checks across interfaces; descriptor
            # metadata above still observes ctime on one interface while the
            # exact inode remains open.
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
                raise BookProgressStoreError(
                    "book progress storage changed while being read",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                )
            if active_directory is not None:
                self._require_storage_directory_unlocked(active_directory)
            self._require_active_lock_unlocked()
            return raw
        except BookProgressStoreError:
            raise
        except OSError:
            raise BookProgressStoreError(
                "book progress storage could not be read",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from None
        finally:
            # Reading/identity validation is the operation authority. A late
            # close failure on this read-only descriptor cannot invalidate
            # bytes already read and must not replace a stable store result.
            try:
                os.close(descriptor)
            except OSError:
                pass

    @staticmethod
    def _decode_payload_with_source_schema(
        raw: bytes,
    ) -> tuple[dict[str, object], int]:
        """Decode one store while retaining its on-disk schema generation."""
        try:
            text = raw.decode("utf-8")
            parsed = json.loads(text, object_pairs_hook=_reject_duplicate_object_pairs)
        except BookProgressStoreError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            # Python's JSON decoder may raise a plain ValueError when an
            # integer token exceeds the interpreter's int-string digit limit.
            # That malformed on-disk value must stay inside the store's stable
            # corruption contract instead of leaking an implementation error.
            raise BookProgressStoreError(
                "book progress store is corrupt",
                code=BookProgressStoreErrorCode.CORRUPT_STORE,
            ) from None
        validated = _validate_payload(parsed)
        assert type(parsed) is dict
        source_schema_version = parsed["schema_version"]
        assert type(source_schema_version) is int
        return validated, source_schema_version

    @staticmethod
    def _decode_payload(raw: bytes) -> dict[str, object]:
        validated, _ = BookProgressStore._decode_payload_with_source_schema(raw)
        return validated

    def _read_state_unlocked(
        self,
        path: Path,
        *,
        missing_ok: bool,
    ) -> tuple[dict[str, object] | None, bytes | None, str | None]:
        raw = self._read_raw_file_unlocked(path, missing_ok=missing_ok)
        if raw is None:
            return None, None, None
        return self._decode_payload(raw), raw, _revision(raw)

    def _data_path_identity_unlocked(
        self,
        path: Path,
        *,
        missing_ok: bool,
    ) -> os.stat_result | None:
        """Return one authenticated private data-path identity or stable missing state."""
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise BookProgressStoreError(
                "book progress recovery data is unavailable",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from None
        except OSError:
            raise BookProgressStoreError(
                "book progress storage is unavailable",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from None
        self._require_private_data_metadata(metadata)
        return metadata

    def _require_recovery_path_unchanged_unlocked(
        self,
        path: Path,
        *,
        expected_identity: os.stat_result | None,
        expected_raw: bytes | None,
        message: str,
    ) -> None:
        """Bind a recovery decision to exact bytes and exact canonical file identity."""
        current_raw = self._read_raw_file_unlocked(path, missing_ok=True)
        current_identity = self._data_path_identity_unlocked(path, missing_ok=True)
        changed = (
            (expected_identity is None) != (expected_raw is None)
            or (current_identity is None) != (current_raw is None)
            or current_raw != expected_raw
        )
        if (
            not changed
            and expected_identity is not None
            and current_identity is not None
            and not self._same_file_identity(expected_identity, current_identity)
        ):
            changed = True
        if changed:
            raise BookProgressStoreError(
                message,
                code=BookProgressStoreErrorCode.IO_FAILURE,
            )

    def _require_recovery_primary_unchanged_unlocked(
        self,
        expected_identity: os.stat_result | None,
        expected_raw: bytes | None,
    ) -> None:
        self._require_recovery_path_unchanged_unlocked(
            self._path,
            expected_identity=expected_identity,
            expected_raw=expected_raw,
            message="book progress primary data changed during recovery read",
        )

    def _require_recovery_backup_unchanged_unlocked(
        self,
        expected_identity: os.stat_result | None,
        expected_raw: bytes | None,
    ) -> None:
        self._require_recovery_path_unchanged_unlocked(
            self.backup_path,
            expected_identity=expected_identity,
            expected_raw=expected_raw,
            message="book progress recovery data changed during recovery read",
        )

    def _require_write_path_unchanged_unlocked(
        self,
        path: Path,
        *,
        expected_identity: os.stat_result | None,
        expected_raw: bytes | None,
        message: str,
    ) -> None:
        """Require one mutation CAS to retain both bytes and canonical inode."""
        current_raw = self._read_raw_file_unlocked(path, missing_ok=True)
        current_identity = self._data_path_identity_unlocked(path, missing_ok=True)
        changed = (
            (expected_identity is None) != (expected_raw is None)
            or (current_identity is None) != (current_raw is None)
            or current_raw != expected_raw
        )
        if (
            not changed
            and expected_identity is not None
            and current_identity is not None
            and not self._same_file_identity(expected_identity, current_identity)
        ):
            changed = True
        if changed:
            raise BookProgressStoreError(
                message,
                code=BookProgressStoreErrorCode.STALE_WRITE,
            )

    def _load_state_unlocked(
        self,
        *,
        allow_backup_recovery: bool = False,
    ) -> tuple[dict[str, object], bytes | None, str | None]:
        primary_identity = (
            self._data_path_identity_unlocked(self._path, missing_ok=True)
            if allow_backup_recovery
            else None
        )
        primary_raw = self._read_raw_file_unlocked(self._path, missing_ok=True)
        if allow_backup_recovery:
            self._require_recovery_primary_unchanged_unlocked(
                primary_identity,
                primary_raw,
            )

        if primary_raw is not None:
            try:
                primary_payload = self._decode_payload(primary_raw)
            except BookProgressStoreError as primary_error:
                if (
                    not allow_backup_recovery
                    or primary_error.code != BookProgressStoreErrorCode.CORRUPT_STORE
                ):
                    raise
                try:
                    backup_identity = self._data_path_identity_unlocked(
                        self.backup_path,
                        missing_ok=False,
                    )
                    backup_payload, backup_raw, _ = self._read_state_unlocked(
                        self.backup_path,
                        missing_ok=False,
                    )
                except BookProgressStoreError:
                    raise primary_error
                assert backup_payload is not None and backup_raw is not None
                self._require_recovery_primary_unchanged_unlocked(
                    primary_identity,
                    primary_raw,
                )
                self._require_recovery_backup_unchanged_unlocked(
                    backup_identity,
                    backup_raw,
                )
                return backup_payload, backup_raw, _revision(backup_raw)
            return primary_payload, primary_raw, _revision(primary_raw)

        if allow_backup_recovery:
            backup_identity = self._data_path_identity_unlocked(
                self.backup_path,
                missing_ok=True,
            )
            backup_payload, backup_raw, backup_revision = self._read_state_unlocked(
                self.backup_path,
                missing_ok=True,
            )
            self._require_recovery_primary_unchanged_unlocked(
                primary_identity,
                None,
            )
            self._require_recovery_backup_unchanged_unlocked(
                backup_identity,
                backup_raw,
            )
            if backup_payload is not None:
                assert backup_raw is not None and backup_revision is not None
                return backup_payload, backup_raw, backup_revision
        else:
            # Mutation callers must not mistake recoverable orphan state for
            # a clean first run. The write path repeats this check to close
            # the race where a backup appears after this load.
            self._require_no_orphan_backup_unlocked()
        return _empty_payload(), None, None

    def _load_payload_unlocked(self) -> dict[str, object]:
        payload, _, _ = self._load_state_unlocked()
        return payload

    @staticmethod
    def _lock_file_descriptor(descriptor: int) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError:
            raise BookProgressStoreError(
                "book progress storage is busy",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from None

    @staticmethod
    def _unlock_file_descriptor(descriptor: int) -> None:
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

    def _require_lock_descriptor_current(self, descriptor: int) -> None:
        """Require the locked descriptor to still be the configured lock pathname."""
        try:
            metadata = os.fstat(descriptor)
            current_path = os.lstat(self._lock_path)
        except OSError:
            raise BookProgressStoreError(
                "book progress storage lock changed while being acquired",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from None
        self._require_private_lock_metadata(metadata)
        self._require_private_lock_metadata(current_path)
        if not self._same_file_identity(metadata, current_path):
            raise BookProgressStoreError(
                "book progress storage lock changed while being acquired",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            )
        if metadata.st_size != 1:
            raise BookProgressStoreError(
                "book progress storage lock changed while being acquired",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            )
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            marker = os.read(descriptor, 2)
        except OSError:
            raise BookProgressStoreError(
                "book progress storage lock changed while being acquired",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from None
        if marker != b"\0":
            raise BookProgressStoreError(
                "book progress storage lock changed while being acquired",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            )

    def _require_active_lock_unlocked(self) -> None:
        descriptor = self._active_lock_descriptor
        if descriptor is not None:
            self._require_lock_descriptor_current(descriptor)

    def _open_lock_descriptor(
        self,
        *,
        expected_directory_identity: os.stat_result | None = None,
    ) -> int:
        if expected_directory_identity is not None:
            self._require_storage_directory_unlocked(expected_directory_identity)
        # A first-use race between two cooperating processes is expected:
        # both may observe a missing pathname, while exactly one wins O_EXCL.
        # Never initialize the raced-in file. Instead, briefly wait for the
        # exclusive creator to finish writing the canonical marker, then reopen
        # it through the same private-inode validation used for pre-existing
        # locks. A noncanonical raced-in file still fails closed unchanged.
        descriptor = -1
        existing: os.stat_result | None = None
        initializing_identity: os.stat_result | None = None
        # An O_EXCL creator exposes an empty inode briefly before its one-byte
        # marker is durable. Another process may first observe that inode after
        # creation, without itself seeing FileExistsError. Wait only for the
        # exact private inode to become initialized; never write into it.
        for attempt in range(250):
            try:
                existing = os.lstat(self._lock_path)
            except FileNotFoundError:
                existing = None
            except OSError:
                raise BookProgressStoreError(
                    "book progress storage lock is unavailable",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                ) from None
            if existing is not None:
                self._require_private_lock_metadata(existing)
                if (
                    initializing_identity is not None
                    and not self._same_file_identity(initializing_identity, existing)
                ):
                    raise BookProgressStoreError(
                        "book progress storage lock changed while being initialized",
                        code=BookProgressStoreErrorCode.IO_FAILURE,
                    )
                if existing.st_size == 0:
                    if initializing_identity is None:
                        initializing_identity = existing
                    if attempt == 249:
                        raise BookProgressStoreError(
                            "book progress storage lock was not initialized by its creator",
                            code=BookProgressStoreErrorCode.IO_FAILURE,
                        )
                    time.sleep(0.002)
                    continue

            flags = os.O_RDWR
            flags |= getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOINHERIT", 0)
            flags |= getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            if existing is None:
                # Only an exclusive creator may initialize a missing lock.
                flags |= os.O_CREAT | os.O_EXCL
            try:
                descriptor = os.open(self._lock_path, flags, 0o600)
                break
            except FileExistsError:
                if attempt == 249:
                    raise BookProgressStoreError(
                        "book progress storage lock changed while being opened",
                        code=BookProgressStoreErrorCode.IO_FAILURE,
                    ) from None
                time.sleep(0.002)
                continue
            except OSError:
                raise BookProgressStoreError(
                    "book progress storage lock is unavailable",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                ) from None
        if descriptor < 0:
            raise BookProgressStoreError(
                "book progress storage lock is unavailable",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            )
        created_lock_identity: os.stat_result | None = None
        try:
            metadata = os.fstat(descriptor)
            self._require_private_lock_metadata(metadata)
            if existing is None:
                # From this point onward cleanup may remove the lock only while
                # the pathname still names this exact O_EXCL-created private inode.
                created_lock_identity = metadata
            if existing is not None and not self._same_file_identity(existing, metadata):
                raise BookProgressStoreError(
                    "book progress storage lock changed while being opened",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                )
            try:
                current_path = os.lstat(self._lock_path)
            except OSError:
                raise BookProgressStoreError(
                    "book progress storage lock changed while being opened",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                ) from None
            self._require_private_lock_metadata(current_path)
            if not self._same_file_identity(metadata, current_path):
                raise BookProgressStoreError(
                    "book progress storage lock changed while being opened",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                )
            if existing is not None:
                # A stable existing lock must already carry the marker written
                # by the exclusive creator. Never initialize or normalize an
                # arbitrary pre-existing file in place.
                if metadata.st_size != 1:
                    raise BookProgressStoreError(
                        "book progress storage lock is not initialized",
                        code=BookProgressStoreErrorCode.IO_FAILURE,
                    )
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    marker = os.read(descriptor, 2)
                except OSError:
                    raise BookProgressStoreError(
                        "book progress storage lock could not be validated",
                        code=BookProgressStoreErrorCode.IO_FAILURE,
                    ) from None
                if marker != b"\0":
                    raise BookProgressStoreError(
                        "book progress storage lock is not initialized",
                        code=BookProgressStoreErrorCode.IO_FAILURE,
                    )
            else:
                # Only this process's O_EXCL-created empty inode may be
                # initialized. Revalidate privacy/identity immediately before
                # writing the marker so a foreign alias cannot be normalized.
                current_descriptor = os.fstat(descriptor)
                self._require_private_lock_metadata(current_descriptor)
                if (
                    current_descriptor.st_size != 0
                    or not self._same_file_identity(metadata, current_descriptor)
                ):
                    raise BookProgressStoreError(
                        "book progress storage lock changed while being initialized",
                        code=BookProgressStoreErrorCode.IO_FAILURE,
                    )
                try:
                    written = os.write(descriptor, b"\0")
                    if written != 1:
                        raise OSError("short Book-progress lock marker write")
                    os.fsync(descriptor)
                except OSError:
                    raise BookProgressStoreError(
                        "book progress storage lock could not be initialized",
                        code=BookProgressStoreErrorCode.IO_FAILURE,
                    ) from None
                try:
                    initialized = os.fstat(descriptor)
                    self._require_private_lock_metadata(initialized)
                    if (
                        initialized.st_size != 1
                        or not self._same_file_identity(metadata, initialized)
                    ):
                        raise BookProgressStoreError(
                            "book progress storage lock changed while being initialized",
                            code=BookProgressStoreErrorCode.IO_FAILURE,
                        )
                except OSError:
                    raise BookProgressStoreError(
                        "book progress storage lock could not be validated",
                        code=BookProgressStoreErrorCode.IO_FAILURE,
                    ) from None
                # The creator already proved a one-byte write and fsync on this
                # exact private inode. Avoid a pre-lock Windows CRT readback
                # race here; _require_lock_descriptor_current() re-reads the
                # canonical marker immediately after the OS lock is acquired.
            try:
                final_path = os.lstat(self._lock_path)
            except OSError:
                raise BookProgressStoreError(
                    "book progress storage lock changed while being initialized",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                ) from None
            self._require_private_lock_metadata(final_path)
            if not self._same_file_identity(metadata, final_path):
                raise BookProgressStoreError(
                    "book progress storage lock changed while being initialized",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                )
            if expected_directory_identity is not None:
                self._require_storage_directory_unlocked(
                    expected_directory_identity
                )
            return descriptor
        except BaseException as error:
            # Preserve the validation/initialization failure as the public
            # authority. If this attempt exclusively created the lock, remove
            # only that exact inode after closing it so a transient write/fsync
            # failure cannot poison every later startup. A substituted or
            # hard-linked pathname is deliberately preserved.
            try:
                os.close(descriptor)
            except OSError:
                pass
            if existing is None:
                self._discard_owned_lock_unlocked(
                    self._lock_path,
                    created_lock_identity,
                )
            if isinstance(error, OSError):
                raise BookProgressStoreError(
                    "book progress storage lock is unavailable",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                ) from None
            raise

    def _require_storage_directory_unlocked(
        self,
        expected_identity: os.stat_result | None = None,
    ) -> os.stat_result:
        """Require and optionally identity-bind the configured storage parent."""
        try:
            metadata = os.lstat(self._path.parent)
        except OSError:
            raise BookProgressStoreError(
                "book progress storage directory is unavailable",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from None
        if (
            stat.S_ISLNK(metadata.st_mode)
            or _is_reparse_point(metadata)
            or not stat.S_ISDIR(metadata.st_mode)
        ):
            raise BookProgressStoreError(
                "book progress storage directory is not a regular directory",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            )
        if (
            expected_identity is not None
            and not self._same_file_identity(expected_identity, metadata)
        ):
            raise BookProgressStoreError(
                "book progress storage directory changed during the transaction",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            )
        return metadata

    def _cleanup_stale_temps_unlocked(self) -> None:
        """Leave crash-left temp pathnames untouched.

        Across process lifetimes there is no portable, race-free proof that an
        exact-looking pathname is still the inode created by this store. The
        active writer already removes only its own identity-bound temp in its
        publication finally block. Cross-run scavenging therefore remains
        deliberately non-destructive instead of guessing ownership and risking
        deletion of a substituted or user-owned file.
        """
        return

    @contextmanager
    def _exclusive_access(self) -> Iterator[None]:
        with self._process_lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                raise BookProgressStoreError(
                    "book progress storage is unavailable",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                ) from None
            directory_identity = self._require_storage_directory_unlocked()
            descriptor = self._open_lock_descriptor(
                expected_directory_identity=directory_identity
            )
            acquired = False
            previous_directory_identity = self._active_storage_directory_identity
            previous_lock_descriptor = self._active_lock_descriptor
            try:
                self._lock_file_descriptor(descriptor)
                acquired = True
                self._require_lock_descriptor_current(descriptor)
                self._require_storage_directory_unlocked(directory_identity)
                self._active_storage_directory_identity = directory_identity
                self._active_lock_descriptor = descriptor
                self._cleanup_stale_temps_unlocked()
                self._require_active_lock_unlocked()
                yield
                self._require_active_lock_unlocked()
            finally:
                self._active_lock_descriptor = previous_lock_descriptor
                self._active_storage_directory_identity = previous_directory_identity
                # The protected body is the transaction authority. A save can
                # already have atomically published primary progress bytes when
                # lock-release cleanup runs. Cleanup failure cannot undo that
                # publication, so do not turn committed state into a false
                # save failure or mask an earlier body exception.
                if acquired:
                    try:
                        self._unlock_file_descriptor(descriptor)
                    except Exception:
                        pass
                try:
                    os.close(descriptor)
                except Exception:
                    pass

    def _atomic_publish_bytes_unlocked(
        self,
        target: Path,
        encoded: bytes,
        *,
        require_no_orphan_backup_before_replace: bool = False,
        expected_target_raw: bytes | None | object = _EXPECTED_TARGET_UNSET,
        expected_target_identity: os.stat_result | None | object = _EXPECTED_IDENTITY_UNSET,
        expected_guard_path: Path | None = None,
        expected_guard_raw: bytes | None | object = _EXPECTED_TARGET_UNSET,
        expected_guard_identity: os.stat_result | None | object = _EXPECTED_IDENTITY_UNSET,
    ) -> os.stat_result:
        self._require_active_lock_unlocked()
        if type(require_no_orphan_backup_before_replace) is not bool:
            raise TypeError("require_no_orphan_backup_before_replace must be a boolean")
        if (
            expected_target_raw is not _EXPECTED_TARGET_UNSET
            and expected_target_raw is not None
            and type(expected_target_raw) is not bytes
        ):
            raise TypeError("expected_target_raw must be bytes, None, or omitted")
        if expected_target_identity is not _EXPECTED_IDENTITY_UNSET:
            if expected_target_raw is _EXPECTED_TARGET_UNSET:
                raise TypeError("expected_target_identity requires expected_target_raw")
            if expected_target_identity is not None and not isinstance(
                expected_target_identity,
                os.stat_result,
            ):
                raise TypeError("expected_target_identity must be os.stat_result, None, or omitted")
            if (expected_target_identity is None) != (expected_target_raw is None):
                raise TypeError("expected_target_identity must match expected_target_raw presence")
        if expected_guard_path is None:
            if expected_guard_raw is not _EXPECTED_TARGET_UNSET:
                raise TypeError("expected_guard_raw requires expected_guard_path")
            if expected_guard_identity is not _EXPECTED_IDENTITY_UNSET:
                raise TypeError("expected_guard_identity requires expected_guard_path")
        else:
            if not isinstance(expected_guard_path, Path):
                raise TypeError("expected_guard_path must be a Path or None")
            if expected_guard_raw is _EXPECTED_TARGET_UNSET:
                raise TypeError("expected_guard_raw is required with expected_guard_path")
            if expected_guard_raw is not None and type(expected_guard_raw) is not bytes:
                raise TypeError("expected_guard_raw must be bytes or None")
            if expected_guard_identity is not _EXPECTED_IDENTITY_UNSET:
                if expected_guard_identity is not None and not isinstance(
                    expected_guard_identity,
                    os.stat_result,
                ):
                    raise TypeError("expected_guard_identity must be os.stat_result, None, or omitted")
                if (expected_guard_identity is None) != (expected_guard_raw is None):
                    raise TypeError("expected_guard_identity must match expected_guard_raw presence")

        guard_base_identity: os.stat_result | None = None
        if expected_guard_path is not None:
            try:
                observed_guard_identity = os.lstat(expected_guard_path)
            except FileNotFoundError:
                observed_guard_identity = None
            except OSError:
                raise BookProgressStoreError(
                    "book progress recovery data changed during publication preparation",
                    code=BookProgressStoreErrorCode.STALE_WRITE,
                ) from None
            if observed_guard_identity is not None:
                self._require_private_data_metadata(observed_guard_identity)
            guard_base_identity = (
                observed_guard_identity
                if expected_guard_identity is _EXPECTED_IDENTITY_UNSET
                else expected_guard_identity
            )
            if (observed_guard_identity is None) != (guard_base_identity is None):
                raise BookProgressStoreError(
                    "book progress recovery data changed during publication preparation",
                    code=BookProgressStoreErrorCode.STALE_WRITE,
                )
            if (
                observed_guard_identity is not None
                and guard_base_identity is not None
                and not self._same_file_identity(
                    guard_base_identity,
                    observed_guard_identity,
                )
            ):
                raise BookProgressStoreError(
                    "book progress recovery data changed during publication preparation",
                    code=BookProgressStoreErrorCode.STALE_WRITE,
                )
            if (guard_base_identity is None) != (expected_guard_raw is None):
                raise BookProgressStoreError(
                    "book progress recovery data changed during publication preparation",
                    code=BookProgressStoreErrorCode.STALE_WRITE,
                )

        if len(encoded) > MAX_BOOK_PROGRESS_STORE_BYTES:
            raise BookProgressStoreError(
                "book progress store exceeds the resource limit",
                code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
            )
        try:
            existing = os.lstat(target)
        except FileNotFoundError:
            existing = None
        except OSError:
            raise BookProgressStoreError(
                "book progress storage is unavailable",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from None
        if existing is not None:
            self._require_private_data_metadata(existing)
        publication_base_identity = (
            existing
            if expected_target_identity is _EXPECTED_IDENTITY_UNSET
            else expected_target_identity
        )
        if (existing is None) != (publication_base_identity is None):
            raise BookProgressStoreError(
                "book progress changed during publication preparation",
                code=BookProgressStoreErrorCode.STALE_WRITE,
            )
        if (
            existing is not None
            and publication_base_identity is not None
            and not self._same_file_identity(publication_base_identity, existing)
        ):
            raise BookProgressStoreError(
                "book progress changed during publication preparation",
                code=BookProgressStoreErrorCode.STALE_WRITE,
            )

        if expected_target_raw is _EXPECTED_TARGET_UNSET:
            # Even callers that intentionally replace the current target (the
            # rolling backup path) must not silently overwrite a change that
            # happens while the durable temp file is being prepared.
            publication_base_raw = self._read_raw_file_unlocked(
                target,
                missing_ok=True,
            )
        else:
            publication_base_raw = expected_target_raw

        if publication_base_identity is not None:
            try:
                current_base_identity = os.lstat(target)
            except OSError:
                raise BookProgressStoreError(
                    "book progress changed during publication preparation",
                    code=BookProgressStoreErrorCode.STALE_WRITE,
                ) from None
            self._require_private_data_metadata(current_base_identity)
            if not self._same_file_identity(
                publication_base_identity,
                current_base_identity,
            ):
                raise BookProgressStoreError(
                    "book progress changed during publication preparation",
                    code=BookProgressStoreErrorCode.STALE_WRITE,
                )

        active_directory = self._active_storage_directory_identity
        if active_directory is not None:
            self._require_storage_directory_unlocked(active_directory)

        temp_path: Path | None = None
        temp_identity: os.stat_result | None = None
        try:
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
            )
            temp_path = Path(temp_name)
            with os.fdopen(descriptor, "wb") as stream:
                created_identity = os.fstat(stream.fileno())
                temp_identity = created_identity
                self._require_private_temp_metadata(created_identity)
                if active_directory is not None:
                    self._require_storage_directory_unlocked(active_directory)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
                temp_identity = os.fstat(stream.fileno())
                self._require_private_temp_metadata(temp_identity)
                self._require_active_lock_unlocked()
                if not self._same_file_identity(created_identity, temp_identity):
                    raise BookProgressStoreError(
                        "book progress temporary file changed while being prepared",
                        code=BookProgressStoreErrorCode.IO_FAILURE,
                    )
            if require_no_orphan_backup_before_replace:
                # The previous orphan check happens before temp-file I/O. A
                # non-cooperating writer can create recovery data while this
                # potentially slow write/fsync is in progress. Recheck after
                # the durable temp is complete. The temp pathname is then
                # rebound to the exact fsynced inode immediately before replace.
                self._require_no_orphan_backup_unlocked()
            try:
                current_temp = os.lstat(temp_path)
            except OSError:
                raise BookProgressStoreError(
                    "book progress temporary file changed before publication",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                ) from None
            self._require_private_temp_metadata(current_temp)
            if temp_identity is None or not self._same_file_identity(
                temp_identity,
                current_temp,
            ):
                raise BookProgressStoreError(
                    "book progress temporary file changed before publication",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                )
            if expected_guard_path is not None:
                current_guard_raw = self._read_raw_file_unlocked(
                    expected_guard_path,
                    missing_ok=True,
                )
                if current_guard_raw != expected_guard_raw:
                    raise BookProgressStoreError(
                        "book progress recovery data changed during publication preparation",
                        code=BookProgressStoreErrorCode.STALE_WRITE,
                    )
                if guard_base_identity is not None:
                    try:
                        current_guard_identity = os.lstat(expected_guard_path)
                    except OSError:
                        raise BookProgressStoreError(
                            "book progress recovery data changed during publication preparation",
                            code=BookProgressStoreErrorCode.STALE_WRITE,
                        ) from None
                    self._require_private_data_metadata(current_guard_identity)
                    if not self._same_file_identity(
                        guard_base_identity,
                        current_guard_identity,
                    ):
                        raise BookProgressStoreError(
                            "book progress recovery data changed during publication preparation",
                            code=BookProgressStoreErrorCode.STALE_WRITE,
                        )
            current_target_raw = self._read_raw_file_unlocked(
                target,
                missing_ok=True,
            )
            if current_target_raw != publication_base_raw:
                raise BookProgressStoreError(
                    "book progress changed during publication preparation",
                    code=BookProgressStoreErrorCode.STALE_WRITE,
                )
            if publication_base_identity is not None:
                try:
                    current_target_identity = os.lstat(target)
                except OSError:
                    raise BookProgressStoreError(
                        "book progress changed during publication preparation",
                        code=BookProgressStoreErrorCode.STALE_WRITE,
                    ) from None
                self._require_private_data_metadata(current_target_identity)
                if not self._same_file_identity(
                    publication_base_identity,
                    current_target_identity,
                ):
                    raise BookProgressStoreError(
                        "book progress changed during publication preparation",
                        code=BookProgressStoreErrorCode.STALE_WRITE,
                    )
            if active_directory is not None:
                self._require_storage_directory_unlocked(active_directory)
            self._require_active_lock_unlocked()
            _replace_published_path(temp_path, target)
            temp_path = None
            try:
                self._require_active_lock_unlocked()
                # Publication success is bound to the exact fsynced temp inode,
                # not merely to equivalent bytes at the canonical pathname.
                # A non-cooperating same-user writer can substitute the temp
                # pathname in the final lstat -> replace window with a different
                # private inode carrying identical bytes. Byte readback alone
                # would otherwise report a false successful commit.
                published_identity = os.lstat(target)
                self._require_private_data_metadata(published_identity)
                if temp_identity is None or not self._same_file_identity(
                    temp_identity,
                    published_identity,
                ):
                    raise BookProgressStoreError(
                        "book progress was published but canonical storage changed before confirmation",
                        code=BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
                    )
                if active_directory is not None:
                    self._require_storage_directory_unlocked(active_directory)
                self._require_active_lock_unlocked()
                _sync_published_path(target)
                self._require_active_lock_unlocked()
                visible = self._read_raw_file_unlocked(target, missing_ok=False)
                # Byte equality is not sufficient confirmation: a same-user
                # non-cooperating writer can replace the canonical pathname
                # with an equivalent private inode while the durability sync is
                # in progress. Bind the final visible pathname back to the exact
                # fsynced temp inode that this transaction published.
                final_published_identity = os.lstat(target)
                self._require_private_data_metadata(final_published_identity)
                if temp_identity is None or not self._same_file_identity(
                    temp_identity,
                    final_published_identity,
                ):
                    raise BookProgressStoreError(
                        "book progress was published but canonical storage changed before confirmation",
                        code=BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
                    )
                self._require_active_lock_unlocked()
                if expected_guard_path is not None:
                    # The guard authorized publication before replace. Recheck
                    # the same bytes+inode snapshot after our target is already
                    # visible so a guard mutation in the final check->replace
                    # window cannot be acknowledged as a clean commit.
                    self._require_recovery_path_unchanged_unlocked(
                        expected_guard_path,
                        expected_identity=guard_base_identity,
                        expected_raw=expected_guard_raw,
                        message="book progress recovery data changed after publication",
                    )
            except (OSError, BookProgressStoreError):
                # Replacement already succeeded. The published bytes may be
                # visible even though crash durability or canonical pathname
                # identity could not be confirmed. Callers must reload visible
                # canonical state before deciding whether UI rollback is safe.
                raise BookProgressStoreError(
                    "book progress was published but durable storage could not be confirmed",
                    code=BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
                ) from None
            if visible != encoded:
                # A non-cooperating writer replaced the canonical pathname after
                # our atomic publication. Our bytes were published, but they are
                # no longer authoritative; force the application down the same
                # canonical-reload path as any other post-replace ambiguity.
                raise BookProgressStoreError(
                    "book progress was published but canonical storage changed before confirmation",
                    code=BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
                )
            return final_published_identity
        except BookProgressStoreError:
            raise
        except OSError:
            raise BookProgressStoreError(
                "book progress storage could not be updated",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from None
        finally:
            if temp_path is not None:
                self._discard_owned_temp_unlocked(temp_path, temp_identity)

    def _require_no_orphan_backup_unlocked(self) -> None:
        """Do not destroy recoverable history when the primary store is missing."""
        backup_payload, _, _ = self._read_state_unlocked(
            self.backup_path,
            missing_ok=True,
        )
        if backup_payload is not None:
            raise BookProgressStoreError(
                "book progress primary data is missing while recovery data remains",
                code=BookProgressStoreErrorCode.CORRUPT_STORE,
            )

    def _write_payload_unlocked(
        self,
        payload: Mapping[str, object],
        *,
        expected_revision: str | None,
        previous_raw: bytes | None,
        previous_identity: os.stat_result | None,
    ) -> None:
        self._require_active_lock_unlocked()
        validated = _validate_payload(payload)
        encoded = _canonical_json_bytes(validated)

        # Bind rolling-backup publication to the exact backup pathname bytes
        # observed at the start of this write phase. Without this transaction-
        # scoped CAS, a non-cooperating writer can advance both primary and
        # backup after our primary snapshot; blindly rebasing the backup CAS at
        # publication time could then overwrite that newer recovery snapshot
        # before the later primary stale-write check aborts this save.
        if (previous_identity is None) != (previous_raw is None):
            raise BookProgressStoreError(
                "book progress changed before this update could be committed",
                code=BookProgressStoreErrorCode.STALE_WRITE,
            )
        if _revision(previous_raw) != expected_revision:
            raise BookProgressStoreError(
                "book progress changed before this update could be committed",
                code=BookProgressStoreErrorCode.STALE_WRITE,
            )

        backup_base_raw: bytes | None = None
        backup_base_identity: os.stat_result | None = None
        if previous_raw is not None:
            backup_base_identity = self._data_path_identity_unlocked(
                self.backup_path,
                missing_ok=True,
            )
            backup_base_raw = self._read_raw_file_unlocked(
                self.backup_path,
                missing_ok=True,
            )
            self._require_write_path_unchanged_unlocked(
                self.backup_path,
                expected_identity=backup_base_identity,
                expected_raw=backup_base_raw,
                message="book progress recovery data changed before this update could be committed",
            )
            if backup_base_raw is not None:
                # A valid primary does not authorize destroying recovery data
                # that belongs to a newer/ambiguous store generation. In
                # particular, a future-schema backup must survive an older
                # application's ordinary save instead of being silently
                # downgraded to the current primary.
                try:
                    (
                        backup_payload,
                        backup_source_schema,
                    ) = self._decode_payload_with_source_schema(backup_base_raw)
                except BookProgressStoreError as backup_error:
                    if backup_error.code != BookProgressStoreErrorCode.CORRUPT_STORE:
                        raise
                    # A structurally corrupt backup is not usable recovery
                    # authority while the primary is valid; the rolling backup
                    # publication below is allowed to repair it from that exact
                    # current primary.
                else:
                    (
                        primary_payload,
                        primary_source_schema,
                    ) = self._decode_payload_with_source_schema(previous_raw)
                    backup_generation = backup_payload["generation"]
                    primary_generation = primary_payload["generation"]
                    assert type(backup_generation) is int
                    assert type(primary_generation) is int
                    legacy_pair = (
                        primary_source_schema
                        == LEGACY_BOOK_PROGRESS_STORE_SCHEMA_VERSION
                        and backup_source_schema
                        == LEGACY_BOOK_PROGRESS_STORE_SCHEMA_VERSION
                    )
                    if backup_generation > primary_generation or (
                        backup_generation == primary_generation
                        and backup_base_raw != previous_raw
                        and not legacy_pair
                    ):
                        raise BookProgressStoreError(
                            "book progress recovery data is newer or divergent",
                            code=BookProgressStoreErrorCode.STALE_WRITE,
                        )

        self._require_write_path_unchanged_unlocked(
            self._path,
            expected_identity=previous_identity,
            expected_raw=previous_raw,
            message="book progress changed before this update could be committed",
        )

        published_backup_identity: os.stat_result | None = None
        if previous_raw is None:
            # A missing primary plus an existing backup is not a clean first run.
            # It is recoverable prior state. Never erase that last known-good
            # snapshot as a side effect of an unrelated save.
            self._require_no_orphan_backup_unlocked()
        else:
            published_backup_identity = self._atomic_publish_bytes_unlocked(
                self.backup_path,
                previous_raw,
                expected_target_raw=backup_base_raw,
                expected_target_identity=backup_base_identity,
                expected_guard_path=self._path,
                expected_guard_raw=previous_raw,
                expected_guard_identity=previous_identity,
            )

        self._require_write_path_unchanged_unlocked(
            self._path,
            expected_identity=previous_identity,
            expected_raw=previous_raw,
            message="book progress changed before this update could be committed",
        )
        if previous_raw is None:
            # Minimize the non-cooperating-writer race window: a backup can
            # appear after the first orphan check while the primary remains
            # absent. Recheck recovery data immediately before publication so
            # an ordinary first-save path does not silently supersede it.
            self._require_no_orphan_backup_unlocked()
        if previous_raw is None:
            self._atomic_publish_bytes_unlocked(
                self._path,
                encoded,
                require_no_orphan_backup_before_replace=True,
                expected_target_raw=None,
                expected_target_identity=previous_identity,
                expected_guard_path=self.backup_path,
                expected_guard_raw=None,
                expected_guard_identity=None,
            )
        else:
            assert published_backup_identity is not None
            self._atomic_publish_bytes_unlocked(
                self._path,
                encoded,
                expected_target_raw=previous_raw,
                expected_target_identity=previous_identity,
                expected_guard_path=self.backup_path,
                expected_guard_raw=previous_raw,
                expected_guard_identity=published_backup_identity,
            )

    @staticmethod
    def _next_generation(payload: Mapping[str, object]) -> int:
        generation = payload["generation"]
        assert type(generation) is int
        if generation >= MAX_BOOK_PROGRESS_GENERATION:
            raise BookProgressStoreError(
                "book progress generation limit was reached",
                code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
            )
        return generation + 1

    def save(self, book_key: str, reader: BookReader) -> dict[str, object]:
        """Save one reader snapshot without losing other concurrent book updates."""
        key = _book_key(book_key)
        if type(reader) is not BookReader:
            raise TypeError("reader must be BookReader")
        snapshot = _snapshot_copy(reader.snapshot())

        with self._exclusive_access():
            previous_identity = self._data_path_identity_unlocked(
                self._path,
                missing_ok=True,
            )
            payload, previous_raw, revision = self._load_state_unlocked()
            self._require_write_path_unchanged_unlocked(
                self._path,
                expected_identity=previous_identity,
                expected_raw=previous_raw,
                message="book progress changed before this update could be committed",
            )
            entries = dict(payload["entries"])
            if key not in entries and len(entries) >= MAX_BOOK_PROGRESS_ENTRIES:
                raise BookProgressStoreError(
                    "book progress store contains too many books",
                    code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
                )
            entries[key] = snapshot
            self._write_payload_unlocked(
                {
                    "schema_version": BOOK_PROGRESS_STORE_SCHEMA_VERSION,
                    "generation": self._next_generation(payload),
                    "entries": entries,
                },
                expected_revision=revision,
                previous_raw=previous_raw,
                previous_identity=previous_identity,
            )
        return dict(snapshot)

    def restore(self, book_key: str, document: BookDocument) -> BookReader:
        """Restore exact semantic cursor/bookmarks for one BookDocument."""
        key = _book_key(book_key)
        if type(document) is not BookDocument:
            raise TypeError("document must be BookDocument")
        with self._exclusive_access():
            payload, _, _ = self._load_state_unlocked(allow_backup_recovery=True)
            entries = payload["entries"]
            assert isinstance(entries, dict)
            if key not in entries:
                raise LookupError("No saved reading progress for this book")
            snapshot = dict(entries[key])
        return BookReader.restore_snapshot(document, snapshot)

    def restore_primary(self, book_key: str, document: BookDocument) -> BookReader:
        """Restore only the current canonical primary; never fall back to backup."""
        key = _book_key(book_key)
        if type(document) is not BookDocument:
            raise TypeError("document must be BookDocument")
        with self._exclusive_access():
            payload, _, _ = self._read_state_unlocked(
                self._path,
                missing_ok=False,
            )
            assert payload is not None
            entries = payload["entries"]
            assert isinstance(entries, dict)
            if key not in entries:
                raise LookupError("No saved reading progress for this book")
            snapshot = dict(entries[key])
        return BookReader.restore_snapshot(document, snapshot)

    def validated_recovery_revisions(
        self,
        book_key: str,
        document: BookDocument,
    ) -> tuple[str | None, str]:
        """Validate the exact primary/backup state offered for explicit rollback.

        The primary revision is None only when the primary was stably absent.
        Otherwise it identifies the exact corrupt primary bytes whose loss the
        caller may ask the user to confirm. The backup revision identifies the
        exact semantically valid snapshot that may later be published.
        """
        key = _book_key(book_key)
        if type(document) is not BookDocument:
            raise TypeError("document must be BookDocument")
        with self._exclusive_access():
            primary_identity = self._data_path_identity_unlocked(
                self._path,
                missing_ok=True,
            )
            primary_raw = self._read_raw_file_unlocked(
                self._path,
                missing_ok=True,
            )
            self._require_recovery_primary_unchanged_unlocked(
                primary_identity,
                primary_raw,
            )
            if primary_raw is not None:
                try:
                    self._decode_payload(primary_raw)
                except BookProgressStoreError as primary_error:
                    if primary_error.code != BookProgressStoreErrorCode.CORRUPT_STORE:
                        raise
                else:
                    raise BookProgressStoreError(
                        "book progress changed before recovery could be validated",
                        code=BookProgressStoreErrorCode.STALE_WRITE,
                    )

            backup_identity = self._data_path_identity_unlocked(
                self.backup_path,
                missing_ok=False,
            )
            payload, raw, revision = self._read_state_unlocked(
                self.backup_path,
                missing_ok=False,
            )
            assert payload is not None and raw is not None and revision is not None
            entries = payload["entries"]
            assert isinstance(entries, dict)
            if key not in entries:
                raise LookupError("No saved reading progress for this book")
            snapshot = dict(entries[key])
            BookReader.restore_snapshot(document, snapshot)
            # At this user-decision boundary, a non-cooperating namespace
            # mutation is a stale recovery offer, not an opaque read failure.
            # Preserve bytes+inode CAS for both sides of the validated pair so
            # the application can follow its canonical STALE_WRITE reload path.
            self._require_write_path_unchanged_unlocked(
                self._path,
                expected_identity=primary_identity,
                expected_raw=primary_raw,
                message="book progress changed before recovery could be validated",
            )
            self._require_write_path_unchanged_unlocked(
                self.backup_path,
                expected_identity=backup_identity,
                expected_raw=raw,
                message="book progress backup changed before recovery could be validated",
            )
            return _revision(primary_raw), revision

    def validated_backup_revision(self, book_key: str, document: BookDocument) -> str:
        """Validate a backup snapshot and return its exact byte revision.

        This compatibility helper deliberately preserves the historical contract.
        Product recovery that crosses a user-confirmation boundary should use
        validated_recovery_revisions() so the discarded primary state is bound too.
        """
        key = _book_key(book_key)
        if type(document) is not BookDocument:
            raise TypeError("document must be BookDocument")
        with self._exclusive_access():
            payload, raw, revision = self._read_state_unlocked(
                self.backup_path,
                missing_ok=False,
            )
            assert payload is not None and raw is not None and revision is not None
            entries = payload["entries"]
            assert isinstance(entries, dict)
            if key not in entries:
                raise LookupError("No saved reading progress for this book")
            snapshot = dict(entries[key])
            BookReader.restore_snapshot(document, snapshot)
            return revision

    def has(self, book_key: str) -> bool:
        key = _book_key(book_key)
        with self._exclusive_access():
            payload, _, _ = self._load_state_unlocked(allow_backup_recovery=True)
            entries = payload["entries"]
            assert isinstance(entries, dict)
            return key in entries

    def remove(self, book_key: str) -> bool:
        """Remove one saved book atomically; return whether an entry existed."""
        key = _book_key(book_key)
        with self._exclusive_access():
            previous_identity = self._data_path_identity_unlocked(
                self._path,
                missing_ok=True,
            )
            payload, previous_raw, revision = self._load_state_unlocked()
            self._require_write_path_unchanged_unlocked(
                self._path,
                expected_identity=previous_identity,
                expected_raw=previous_raw,
                message="book progress changed before this update could be committed",
            )
            entries = dict(payload["entries"])
            if key not in entries:
                return False
            del entries[key]
            self._write_payload_unlocked(
                {
                    "schema_version": BOOK_PROGRESS_STORE_SCHEMA_VERSION,
                    "generation": self._next_generation(payload),
                    "entries": entries,
                },
                expected_revision=revision,
                previous_raw=previous_raw,
                previous_identity=previous_identity,
            )
            return True

    def recover_from_backup(
        self,
        *,
        expected_backup_revision: str | None = None,
        expected_primary_revision: str | None | object = _EXPECTED_TARGET_UNSET,
    ) -> bool:
        """Explicitly replace a missing/corrupt primary with a valid prior snapshot.

        A supplied backup revision binds the bytes to publish. A supplied primary
        revision binds the corrupt/missing state the caller agreed may be lost;
        None means the primary was expected to remain absent. Calls that omit both
        expectations retain the historical explicit-recovery contract.
        """
        if expected_backup_revision is not None:
            if (
                type(expected_backup_revision) is not str
                or len(expected_backup_revision) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in expected_backup_revision
                )
            ):
                raise BookProgressStoreError(
                    "book progress backup revision is invalid",
                    code=BookProgressStoreErrorCode.INVALID_ARGUMENT,
                )
        if (
            expected_primary_revision is not _EXPECTED_TARGET_UNSET
            and expected_primary_revision is not None
        ):
            if (
                type(expected_primary_revision) is not str
                or len(expected_primary_revision) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in expected_primary_revision
                )
            ):
                raise BookProgressStoreError(
                    "book progress primary revision is invalid",
                    code=BookProgressStoreErrorCode.INVALID_ARGUMENT,
                )

        with self._exclusive_access():
            primary_identity = self._data_path_identity_unlocked(
                self._path,
                missing_ok=True,
            )
            primary_raw = self._read_raw_file_unlocked(self._path, missing_ok=True)
            self._require_recovery_primary_unchanged_unlocked(
                primary_identity,
                primary_raw,
            )
            if (
                expected_primary_revision is not _EXPECTED_TARGET_UNSET
                and _revision(primary_raw) != expected_primary_revision
            ):
                raise BookProgressStoreError(
                    "book progress changed before recovery could be committed",
                    code=BookProgressStoreErrorCode.STALE_WRITE,
                )
            primary_missing = primary_raw is None
            if not primary_missing:
                try:
                    self._decode_payload(primary_raw)
                except BookProgressStoreError as primary_error:
                    if primary_error.code != BookProgressStoreErrorCode.CORRUPT_STORE:
                        raise
                else:
                    # A revision-bound recovery request represents a backup that
                    # was already semantically validated before user confirmation.
                    # If the primary is valid by the time that request reaches the
                    # commit boundary, another writer/recovery has changed the
                    # canonical authority. Returning the historical no-op False
                    # would make the application re-raise its earlier CORRUPT_STORE
                    # snapshot and skip the existing STALE_WRITE canonical reload.
                    # Treat this as a stale recovery decision instead. Calls without
                    # an expected revision retain the historical idempotent no-op.
                    if (
                        expected_backup_revision is not None
                        or expected_primary_revision is not _EXPECTED_TARGET_UNSET
                    ):
                        raise BookProgressStoreError(
                            "book progress changed before recovery could be committed",
                            code=BookProgressStoreErrorCode.STALE_WRITE,
                        )
                    return False

            revision_bound_backup = expected_backup_revision is not None
            backup_missing_ok = primary_missing or revision_bound_backup
            try:
                backup_identity = self._data_path_identity_unlocked(
                    self.backup_path,
                    missing_ok=backup_missing_ok,
                )
                backup_payload, backup_raw, backup_revision = self._read_state_unlocked(
                    self.backup_path,
                    missing_ok=backup_missing_ok,
                )
                self._require_recovery_backup_unchanged_unlocked(
                    backup_identity,
                    backup_raw,
                )
            except BookProgressStoreError:
                if revision_bound_backup:
                    raise BookProgressStoreError(
                        "book progress backup changed before recovery could be committed",
                        code=BookProgressStoreErrorCode.STALE_WRITE,
                    ) from None
                raise
            if backup_payload is None:
                if revision_bound_backup:
                    raise BookProgressStoreError(
                        "book progress backup changed before recovery could be committed",
                        code=BookProgressStoreErrorCode.STALE_WRITE,
                    )
                return False
            assert backup_raw is not None and backup_revision is not None
            if (
                expected_backup_revision is not None
                and backup_revision != expected_backup_revision
            ):
                raise BookProgressStoreError(
                    "book progress backup changed before recovery could be committed",
                    code=BookProgressStoreErrorCode.STALE_WRITE,
                )

            current_raw = self._read_raw_file_unlocked(
                self._path,
                missing_ok=primary_missing,
            )
            if primary_missing:
                if current_raw is not None:
                    raise BookProgressStoreError(
                        "book progress changed before recovery could be committed",
                        code=BookProgressStoreErrorCode.STALE_WRITE,
                    )
            elif (
                _revision(current_raw) != _revision(primary_raw)
                or current_raw != primary_raw
            ):
                raise BookProgressStoreError(
                    "book progress changed before recovery could be committed",
                    code=BookProgressStoreErrorCode.STALE_WRITE,
                )

            self._atomic_publish_bytes_unlocked(
                self._path,
                backup_raw,
                expected_target_raw=primary_raw,
                expected_target_identity=primary_identity,
                expected_guard_path=self.backup_path,
                expected_guard_raw=backup_raw,
                expected_guard_identity=backup_identity,
            )
            return True
