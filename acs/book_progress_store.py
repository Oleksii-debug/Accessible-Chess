from __future__ import annotations

"""Durable persistence for semantic :class:`BookReader` progress.

The store deliberately persists only the already-versioned ``BookReader``
snapshot contract.  It does not parse chess, inspect source files, derive book
identity from a local path, or project persistence details into the UI.

A caller supplies an opaque stable ``book_key`` (for example a Library identity
or an importer provenance digest).  The key is data inside one store file, never
a filename, so hostile keys cannot escape the configured application-data path.
"""

from collections.abc import Mapping
from enum import Enum
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
from typing import Any

from .bookdocument import BookDocument
from .bookreader import BookReader


BOOK_PROGRESS_STORE_SCHEMA_VERSION = 1
MAX_BOOK_PROGRESS_ENTRIES = 4096
MAX_BOOK_KEY_CHARS = 256
MAX_BOOK_SNAPSHOT_BYTES = 1 * 1024 * 1024
MAX_BOOK_PROGRESS_STORE_BYTES = 8 * 1024 * 1024

_STORE_FIELDS = frozenset({"schema_version", "entries"})
_READER_SNAPSHOT_FIELDS = frozenset(
    {"schema_version", "current_target", "return_points", "fallback_digests"}
)


class BookProgressStoreErrorCode(str, Enum):
    INVALID_ARGUMENT = "invalid_argument"
    CORRUPT_STORE = "corrupt_store"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    RESOURCE_LIMIT = "resource_limit"
    IO_FAILURE = "io_failure"


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
        "entries": {},
    }


def _validate_payload(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise BookProgressStoreError(
            "book progress store root must be an object",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        )
    if set(value) != _STORE_FIELDS:
        raise BookProgressStoreError(
            "book progress store has unsupported fields",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        )

    schema_version = value["schema_version"]
    if type(schema_version) is not int:
        raise BookProgressStoreError(
            "book progress store schema version must be an integer",
            code=BookProgressStoreErrorCode.CORRUPT_STORE,
        )
    if schema_version != BOOK_PROGRESS_STORE_SCHEMA_VERSION:
        raise BookProgressStoreError(
            "book progress store schema version is unsupported",
            code=BookProgressStoreErrorCode.UNSUPPORTED_SCHEMA,
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

    return {
        "schema_version": BOOK_PROGRESS_STORE_SCHEMA_VERSION,
        "entries": entries,
    }


class BookProgressStore:
    """One atomic JSON store for current BookReader locations and bookmarks.

    The configured path is an infrastructure concern supplied by the composition
    root.  Exceptions intentionally omit that path so an accessibility adapter can
    safely present a concise message without leaking a local user directory.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        if not isinstance(path, (str, os.PathLike)):
            raise TypeError("book progress store path must be path-like")
        self._path = Path(path)
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        """Infrastructure-only configured path; presentation must not project it."""
        return self._path

    def _load_payload_unlocked(self) -> dict[str, object]:
        try:
            metadata = os.lstat(self._path)
        except FileNotFoundError:
            return _empty_payload()
        except OSError as exc:
            raise BookProgressStoreError(
                "book progress storage is unavailable",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            ) from exc

        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise BookProgressStoreError(
                "book progress storage is not a regular file",
                code=BookProgressStoreErrorCode.IO_FAILURE,
            )
        if metadata.st_size > MAX_BOOK_PROGRESS_STORE_BYTES:
            raise BookProgressStoreError(
                "book progress store exceeds the resource limit",
                code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
            )

        try:
            raw = self._path.read_bytes()
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

    def _write_payload_unlocked(self, payload: Mapping[str, object]) -> None:
        validated = _validate_payload(payload)
        encoded = _canonical_json_bytes(validated)
        if len(encoded) > MAX_BOOK_PROGRESS_STORE_BYTES:
            raise BookProgressStoreError(
                "book progress store exceeds the resource limit",
                code=BookProgressStoreErrorCode.RESOURCE_LIMIT,
            )

        parent = self._path.parent
        temp_path: Path | None = None
        try:
            parent.mkdir(parents=True, exist_ok=True)
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                dir=parent,
            )
            temp_path = Path(temp_name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self._path)
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

    def save(self, book_key: str, reader: BookReader) -> dict[str, object]:
        """Atomically save one reader snapshot, preserving all other books."""
        key = _book_key(book_key)
        if not isinstance(reader, BookReader):
            raise TypeError("reader must be BookReader")
        snapshot = _snapshot_copy(reader.snapshot())

        with self._lock:
            payload = self._load_payload_unlocked()
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
                    "entries": entries,
                }
            )
        return dict(snapshot)

    def restore(self, book_key: str, document: BookDocument) -> BookReader:
        """Restore the exact semantic cursor/bookmarks for one BookDocument."""
        key = _book_key(book_key)
        if not isinstance(document, BookDocument):
            raise TypeError("document must be BookDocument")
        with self._lock:
            payload = self._load_payload_unlocked()
            entries = payload["entries"]
            assert isinstance(entries, dict)
            if key not in entries:
                raise LookupError("No saved reading progress for this book")
            snapshot = dict(entries[key])
        return BookReader.restore_snapshot(document, snapshot)

    def has(self, book_key: str) -> bool:
        key = _book_key(book_key)
        with self._lock:
            payload = self._load_payload_unlocked()
            entries = payload["entries"]
            assert isinstance(entries, dict)
            return key in entries

    def remove(self, book_key: str) -> bool:
        """Remove one saved book atomically; return whether an entry existed."""
        key = _book_key(book_key)
        with self._lock:
            payload = self._load_payload_unlocked()
            entries = dict(payload["entries"])
            if key not in entries:
                return False
            del entries[key]
            self._write_payload_unlocked(
                {
                    "schema_version": BOOK_PROGRESS_STORE_SCHEMA_VERSION,
                    "entries": entries,
                }
            )
            return True
