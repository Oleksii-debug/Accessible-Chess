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
    if len(value) > MAX_BOOK_KEY_CHARS or any(ord(character) < 32 for character in value):
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
    except (TypeError, ValueError) as exc:
        raise BookProgressStoreError(
            "book progress data is not valid JSON data",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        ) from exc


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

    def _read_raw_file_unlocked(self, path: Path, *, missing_ok: bool) -> bytes | None:
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise BookProgressStoreError(
                "book progress recovery data is unavailable",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            )
        except OSError as exc:
            raise BookProgressStoreError(
                "book progress storage is unavailable",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from exc

        self._require_regular_metadata(
            metadata,
            message="book progress storage is not a regular file",
        )
        if metadata.st_size > MAX_BOOK_PROGRESS_STORE_BYTES:
            raise BookProgressStoreError(
                "book progress store exceeds the resource limit",
                code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
            )
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise BookProgressStoreError(
                "book progress storage could not be read",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from exc
        if len(raw) > MAX_BOOK_PROGRESS_STORE_BYTES:
            raise BookProgressStoreError(
                "book progress store exceeds the resource limit",
                code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
            )
        return raw

    @staticmethod
    def _decode_payload(raw: bytes) -> dict[str, object]:
        try:
            text = raw.decode("utf-8")
            parsed = json.loads(text, object_pairs_hook=_reject_duplicate_object_pairs)
        except BookProgressStoreError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BookProgressStoreError(
                "book progress store is corrupt",
                code=BookProgressStoreErrorCode.CORRUPT_STORE,
            ) from exc
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
        except OSError as exc:
            raise BookProgressStoreError(
                "book progress storage is busy",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from exc

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

    def _open_lock_descriptor(self) -> int:
        try:
            existing = os.lstat(self._lock_path)
        except FileNotFoundError:
            existing = None
        except OSError as exc:
            raise BookProgressStoreError(
                "book progress storage lock is unavailable",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from exc
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
        except OSError as exc:
            raise BookProgressStoreError(
                "book progress storage lock is unavailable",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from exc
        try:
            metadata = os.fstat(descriptor)
            self._require_regular_metadata(
                metadata,
                message="book progress storage lock is not a regular file",
            )
            if metadata.st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
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
            except OSError as exc:
                raise BookProgressStoreError(
                    "book progress storage is unavailable",
                    code=BookProgressStoreErrorCode.IO_FAILURE,
                ) from exc
            descriptor = self._open_lock_descriptor()
            acquired = False
            try:
                self._lock_file_descriptor(descriptor)
                acquired = True
                self._cleanup_stale_temps_unlocked()
                yield
            finally:
                if acquired:
                    self._unlock_file_descriptor(descriptor)
                os.close(descriptor)

    def _atomic_publish_bytes_unlocked(self, target: Path, encoded: bytes) -> None:
        if len(encoded) > MAX_BOOK_PROGRESS_STORE_BYTES:
            raise BookProgressStoreError(
                "book progress store exceeds the resource limit",
                code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
            )
        try:
            existing = os.lstat(target)
        except FileNotFoundError:
            existing = None
        except OSError as exc:
            raise BookProgressStoreError(
                "book progress storage is unavailable",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from exc
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
            os.replace(temp_path, target)
            temp_path = None
        except OSError as exc:
            raise BookProgressStoreError(
                "book progress storage could not be updated",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _clear_backup_unlocked(self) -> None:
        try:
            metadata = os.lstat(self.backup_path)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise BookProgressStoreError(
                "book progress recovery data is unavailable",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from exc
        self._require_regular_metadata(
            metadata,
            message="book progress recovery data is not a regular file",
        )
        try:
            self.backup_path.unlink()
        except OSError as exc:
            raise BookProgressStoreError(
                "book progress recovery data could not be reset",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from exc

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
            self._clear_backup_unlocked()
        else:
            self._atomic_publish_bytes_unlocked(self.backup_path, previous_raw)

        current_raw = self._read_raw_file_unlocked(self._path, missing_ok=True)
        if _revision(current_raw) != expected_revision or current_raw != previous_raw:
            raise BookProgressStoreError(
                "book progress changed before this update could be committed",
                code=BookProgressStoreErrorCode.STALE_WRITE,
            )
        self._atomic_publish_bytes_unlocked(self._path, encoded)

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

    def recover_from_backup(self) -> bool:
        """Explicitly replace a corrupt primary with its previous valid snapshot.

        Returns ``False`` when the current primary is already valid or absent.
        Future/unknown primary schemas are never rolled back through this method.
        """
        with self._exclusive_access():
            primary_raw = self._read_raw_file_unlocked(self._path, missing_ok=True)
            if primary_raw is None:
                return False
            try:
                self._decode_payload(primary_raw)
            except BookProgressStoreError as primary_error:
                if primary_error.code != BookProgressStoreErrorCode.CORRUPT_STORE:
                    raise
                backup_payload, backup_raw, _ = self._read_state_unlocked(
                    self.backup_path,
                    missing_ok=False,
                )
                assert backup_payload is not None and backup_raw is not None
                current_raw = self._read_raw_file_unlocked(self._path, missing_ok=False)
                if _revision(current_raw) != _revision(primary_raw):
                    raise BookProgressStoreError(
                        "book progress changed before recovery could be committed",
                        code=BookProgressStoreErrorCode.STALE_WRITE,
                    )
                self._atomic_publish_bytes_unlocked(self._path, backup_raw)
                return True
            return False
