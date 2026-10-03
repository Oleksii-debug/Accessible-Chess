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
import threading
from typing import Any

from .bookdocument import BookDocument
from .bookreader import BookReader


BOOK_PROGRESS_STORE_SCHEMA_VERSION = 2
LEGACY_BOOK_PROGRESS_STORE_SCHEMA_VERSION = 1
MAX_BOOK_PROGRESS_ENTRIES = 4096
MAX_BOOK_KEY_CHARS = 256
MAX_BOOK_SNAPSHOT_BYTES = 1 * 1024 * 1024
MAX_BOOK_PROGRESS_STORE_BYTES = 8 * 1024 * 1024
MAX_BOOK_PROGRESS_GENERATION = (1 << 63) - 1

_STORE_V1_FIELDS = frozenset({"schema_version", "entries"})
_STORE_V2_FIELDS = frozenset({"schema_version", "generation", "entries"})
_READER_SNAPSHOT_FIELDS = frozenset(
    {"schema_version", "current_target", "return_points", "fallback_digests"}
)

_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}


class BookProgressStoreErrorCode(str, Enum):
    INVALID_ARGUMENT = "invalid_argument"
    CORRUPT_STORE = "corrupt_store"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    RESOURCE_LIMIT = "resource_limit"
    IO_FAILURE = "io_failure"
    STALE_WRITE = "stale_write"


class BookProgressStoreError(ValueError):
    """Stable persistence failure without local path disclosure in its message."""

    def __init__(self, message: str, *, code: BookProgressStoreErrorCode) -> None:
        super().__init__(message)
        self.code = BookProgressStoreErrorCode(code)


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
    result: dict[str, Any] = {}
    for key, value in pairs:
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
    if not isinstance(value, Mapping):
        raise BookProgressStoreError(
            "book progress snapshot must be an object",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        )
    if set(value) != _READER_SNAPSHOT_FIELDS:
        raise BookProgressStoreError(
            "book progress snapshot has unsupported fields",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        )
    snapshot = dict(value)
    if len(_canonical_json_bytes(snapshot)) > MAX_BOOK_SNAPSHOT_BYTES:
        raise BookProgressStoreError(
            "book progress snapshot exceeds the resource limit",
            code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
        )
    return snapshot


def _empty_payload() -> dict[str, object]:
    return {
        "schema_version": BOOK_PROGRESS_STORE_SCHEMA_VERSION,
        "generation": 0,
        "entries": {},
    }


def _validate_payload(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise BookProgressStoreError(
            "book progress store root must be an object",
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
    if not isinstance(raw_entries, Mapping):
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
    if set(value) != expected_fields:
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
        self._path = Path(path)
        self._process_lock = _process_lock_for(self._path)

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

    @staticmethod
    def _same_file_identity(first: os.stat_result, second: os.stat_result) -> bool:
        """Return whether two metadata snapshots identify the same file object."""
        try:
            return os.path.samestat(first, second)
        except (AttributeError, OSError):
            return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)

    def _read_raw_file_unlocked(self, path: Path, *, missing_ok: bool) -> bytes | None:
        """Read through the exact descriptor whose file identity was validated.

        The path is inspected before opening to reject symlinks/reparse points,
        then the opened descriptor and a post-open path snapshot must identify
        the same regular file.  Reads never reopen the path after validation.
        """
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
            self._require_regular_metadata(
                before,
                message="book progress storage is not a regular file",
            )
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
            self._require_regular_metadata(
                opened,
                message="book progress storage is not a regular file",
            )
            if opened.st_size > MAX_BOOK_PROGRESS_STORE_BYTES:
                raise BookProgressStoreError(
                    "book progress store exceeds the resource limit",
                    code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
                )
            if before is not None and not self._same_file_identity(before, opened):
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
            self._require_regular_metadata(
                after_open,
                message="book progress storage is not a regular file",
            )
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
            final_metadata = os.fstat(descriptor)
            if (
                not self._same_file_identity(opened, final_metadata)
                or final_metadata.st_size != opened.st_size
                or getattr(final_metadata, "st_mtime_ns", None)
                != getattr(opened, "st_mtime_ns", None)
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
            self._require_regular_metadata(
                after_read,
                message="book progress storage is not a regular file",
            )
            if not self._same_file_identity(opened, after_read):
                raise BookProgressStoreError(
                    "book progress storage changed while being read",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                )
            return raw
        finally:
            os.close(descriptor)

    @staticmethod
    def _decode_payload(raw: bytes) -> dict[str, object]:
        try:
            text = raw.decode("utf-8")
            parsed = json.loads(text, object_pairs_hook=_reject_duplicate_object_pairs)
        except BookProgressStoreError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            raise BookProgressStoreError(
                "book progress store is corrupt",
                code=BookProgressStoreErrorCode.CORRUPT_STORE,
            ) from None
        return _validate_payload(parsed)

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

    def _load_state_unlocked(
        self,
        *,
        allow_backup_recovery: bool = False,
    ) -> tuple[dict[str, object], bytes | None, str | None]:
        try:
            payload, raw, revision = self._read_state_unlocked(self._path, missing_ok=True)
        except BookProgressStoreError as primary_error:
            if not allow_backup_recovery or primary_error.code != BookProgressStoreErrorCode.CORRUPT_STORE:
                raise
            try:
                backup_payload, backup_raw, _ = self._read_state_unlocked(
                    self.backup_path,
                    missing_ok=False,
                )
            except BookProgressStoreError:
                raise primary_error
            assert backup_payload is not None and backup_raw is not None
            return backup_payload, backup_raw, _revision(backup_raw)

        if payload is None:
            if allow_backup_recovery:
                backup_payload, backup_raw, backup_revision = self._read_state_unlocked(
                    self.backup_path,
                    missing_ok=True,
                )
                if backup_payload is not None:
                    assert backup_raw is not None and backup_revision is not None
                    return backup_payload, backup_raw, backup_revision
            else:
                # Mutation callers must not mistake recoverable orphan state for
                # a clean first run.  The write path repeats this check to close
                # the race where a backup appears after this load.
                self._require_no_orphan_backup_unlocked()
            return _empty_payload(), None, None
        return payload, raw, revision

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
        self._require_regular_metadata(
            metadata,
            message="book progress storage lock is not a regular file",
        )
        self._require_regular_metadata(
            current_path,
            message="book progress storage lock is not a regular file",
        )
        if not self._same_file_identity(metadata, current_path):
            raise BookProgressStoreError(
                "book progress storage lock changed while being acquired",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            )

    def _open_lock_descriptor(self) -> int:
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
            self._require_regular_metadata(
                existing,
                message="book progress storage lock is not a regular file",
            )

        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self._lock_path, flags, 0o600)
        except OSError:
            raise BookProgressStoreError(
                "book progress storage lock is unavailable",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from None
        try:
            metadata = os.fstat(descriptor)
            self._require_regular_metadata(
                metadata,
                message="book progress storage lock is not a regular file",
            )
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
            self._require_regular_metadata(
                current_path,
                message="book progress storage lock is not a regular file",
            )
            if not self._same_file_identity(metadata, current_path):
                raise BookProgressStoreError(
                    "book progress storage lock changed while being opened",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                )
            if metadata.st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            try:
                final_path = os.lstat(self._lock_path)
            except OSError:
                raise BookProgressStoreError(
                    "book progress storage lock changed while being initialized",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                ) from None
            self._require_regular_metadata(
                final_path,
                message="book progress storage lock is not a regular file",
            )
            if not self._same_file_identity(metadata, final_path):
                raise BookProgressStoreError(
                    "book progress storage lock changed while being initialized",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                )
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _cleanup_stale_temps_unlocked(self) -> None:
        parent = self._path.parent
        prefixes = (f".{self._path.name}.", f".{self.backup_path.name}.")
        try:
            candidates = list(parent.iterdir())
        except OSError:
            return
        for candidate in candidates:
            name = candidate.name
            if not name.endswith(".tmp") or not any(name.startswith(prefix) for prefix in prefixes):
                continue
            try:
                metadata = os.lstat(candidate)
                if stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode) and not _is_reparse_point(metadata):
                    candidate.unlink(missing_ok=True)
            except OSError:
                pass

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
            descriptor = self._open_lock_descriptor()
            acquired = False
            try:
                self._lock_file_descriptor(descriptor)
                acquired = True
                self._require_lock_descriptor_current(descriptor)
                self._cleanup_stale_temps_unlocked()
                yield
            finally:
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
    ) -> None:
        if type(require_no_orphan_backup_before_replace) is not bool:
            raise TypeError("require_no_orphan_backup_before_replace must be a boolean")
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
            self._require_regular_metadata(
                existing,
                message="book progress storage is not a regular file",
            )

        temp_path: Path | None = None
        try:
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
            )
            temp_path = Path(temp_name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            if require_no_orphan_backup_before_replace:
                # The previous orphan check happens before temp-file I/O. A
                # non-cooperating writer can create recovery data while this
                # potentially slow write/fsync is in progress. Recheck after
                # the durable temp is complete and immediately before the
                # atomic primary replacement, with no intervening disk work.
                self._require_no_orphan_backup_unlocked()
            os.replace(temp_path, target)
            temp_path = None
        except OSError:
            raise BookProgressStoreError(
                "book progress storage could not be updated",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from None
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

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
    ) -> None:
        validated = _validate_payload(payload)
        encoded = _canonical_json_bytes(validated)

        current_raw = self._read_raw_file_unlocked(self._path, missing_ok=True)
        if _revision(current_raw) != expected_revision or current_raw != previous_raw:
            raise BookProgressStoreError(
                "book progress changed before this update could be committed",
                code=BookProgressStoreErrorCode.STALE_WRITE,
            )

        if previous_raw is None:
            # A missing primary plus an existing backup is not a clean first run.
            # It is recoverable prior state. Never erase that last known-good
            # snapshot as a side effect of an unrelated save.
            self._require_no_orphan_backup_unlocked()
        else:
            self._atomic_publish_bytes_unlocked(self.backup_path, previous_raw)

        current_raw = self._read_raw_file_unlocked(self._path, missing_ok=True)
        if _revision(current_raw) != expected_revision or current_raw != previous_raw:
            raise BookProgressStoreError(
                "book progress changed before this update could be committed",
                code=BookProgressStoreErrorCode.STALE_WRITE,
            )
        if previous_raw is None:
            # Minimize the non-cooperating-writer race window: a backup can
            # appear after the first orphan check while the primary remains
            # absent. Recheck recovery data immediately before publication so
            # an ordinary first-save path does not silently supersede it.
            self._require_no_orphan_backup_unlocked()
        self._atomic_publish_bytes_unlocked(
            self._path,
            encoded,
            require_no_orphan_backup_before_replace=previous_raw is None,
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
        if not isinstance(reader, BookReader):
            raise TypeError("reader must be BookReader")
        snapshot = _snapshot_copy(reader.snapshot())

        with self._exclusive_access():
            payload, previous_raw, revision = self._load_state_unlocked()
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
            )
        return dict(snapshot)

    def restore(self, book_key: str, document: BookDocument) -> BookReader:
        """Restore exact semantic cursor/bookmarks for one BookDocument."""
        key = _book_key(book_key)
        if not isinstance(document, BookDocument):
            raise TypeError("document must be BookDocument")
        with self._exclusive_access():
            payload, _, _ = self._load_state_unlocked(allow_backup_recovery=True)
            entries = payload["entries"]
            assert isinstance(entries, dict)
            if key not in entries:
                raise LookupError("No saved reading progress for this book")
            snapshot = dict(entries[key])
        return BookReader.restore_snapshot(document, snapshot)

    def validated_backup_revision(self, book_key: str, document: BookDocument) -> str:
        """Validate the exact backup for this Book and return its byte revision.

        The returned revision binds later explicit recovery to the same backup
        bytes that were semantically validated before user confirmation.
        """
        key = _book_key(book_key)
        if not isinstance(document, BookDocument):
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
            payload, previous_raw, revision = self._load_state_unlocked()
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
            )
            return True

    def recover_from_backup(
        self,
        *,
        expected_backup_revision: str | None = None,
    ) -> bool:
        """Explicitly replace a missing/corrupt primary with a valid prior snapshot.

        If an expected backup revision is supplied, only those exact previously
        validated backup bytes may be published. Calls without a revision retain
        the historical explicit-recovery contract.
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

        with self._exclusive_access():
            primary_raw = self._read_raw_file_unlocked(self._path, missing_ok=True)
            primary_missing = primary_raw is None
            if not primary_missing:
                try:
                    self._decode_payload(primary_raw)
                except BookProgressStoreError as primary_error:
                    if primary_error.code != BookProgressStoreErrorCode.CORRUPT_STORE:
                        raise
                else:
                    return False

            backup_payload, backup_raw, backup_revision = self._read_state_unlocked(
                self.backup_path,
                missing_ok=primary_missing,
            )
            if backup_payload is None:
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

            self._atomic_publish_bytes_unlocked(self._path, backup_raw)
            return True
