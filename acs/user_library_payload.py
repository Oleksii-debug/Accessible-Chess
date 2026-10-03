from __future__ import annotations

"""Verified owner-private Library payload discovery for packaged releases.

The payload is deliberately separate from the redistributable starter corpus.
It carries files supplied by the owner for that owner's private package. Runtime
verification publishes no filesystem paths or book bytes to WebView surfaces.
Only PGN is enabled until another format has an equally deterministic packaged
decoder path.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import sys

from .import_contract import fingerprint


USER_LIBRARY_SCHEMA_VERSION = 1
USER_LIBRARY_SCOPE = "owner-private"
MAX_USER_LIBRARY_SOURCES = 4096
MAX_USER_LIBRARY_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_USER_LIBRARY_SOURCE_BYTES = 4 * 1024 * 1024 * 1024


class UserLibraryPayloadError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PackagedUserLibrarySource:
    path: Path
    name: str
    source_format: str
    size_bytes: int
    sha256: str


class _DuplicateKeyError(ValueError):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(key)
        result[key] = value
    return result


def _is_reparse(info: os.stat_result) -> bool:
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & marker)


def _regular_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise UserLibraryPayloadError("packaged user Library root is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
        raise UserLibraryPayloadError("packaged user Library root must be a regular directory")


def _regular_file(path: Path, *, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise UserLibraryPayloadError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or _is_reparse(info) or not stat.S_ISREG(info.st_mode):
        raise UserLibraryPayloadError(f"{label} must be a regular non-reparse file")
    return info


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    left_ino = getattr(left, "st_ino", 0)
    right_ino = getattr(right, "st_ino", 0)
    if left_ino and right_ino:
        return (getattr(left, "st_dev", None), left_ino) == (
            getattr(right, "st_dev", None),
            right_ino,
        )
    return True


def _identity_pinned_bytes(
    path: Path,
    *,
    label: str,
    minimum_bytes: int,
    maximum_bytes: int,
) -> bytes:
    """Read one bounded regular file without following a pathname replacement."""

    before = _regular_file(path, label=label)
    if not minimum_bytes <= before.st_size <= maximum_bytes:
        raise UserLibraryPayloadError(f"{label} size is invalid")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(os.fspath(path), flags)
    except OSError as exc:
        raise UserLibraryPayloadError(f"{label} could not be opened safely") from exc

    try:
        opened = os.fstat(fd)
        if _is_reparse(opened) or not stat.S_ISREG(opened.st_mode):
            raise UserLibraryPayloadError(f"{label} opened object is not a regular file")
        if not _same_file_identity(before, opened):
            raise UserLibraryPayloadError(f"{label} changed before verified read")
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining > 0:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        opened_after = os.fstat(fd)
    except UserLibraryPayloadError:
        raise
    except OSError as exc:
        raise UserLibraryPayloadError(f"{label} could not be read safely") from exc
    finally:
        os.close(fd)

    after = _regular_file(path, label=label)
    stable_open_file = (
        _same_file_identity(opened, opened_after)
        and opened.st_size == opened_after.st_size
        and getattr(opened, "st_mtime_ns", None) == getattr(opened_after, "st_mtime_ns", None)
    )
    stable_path = (
        _same_file_identity(opened_after, after)
        and opened_after.st_size == after.st_size
        and getattr(opened_after, "st_mtime_ns", None) == getattr(after, "st_mtime_ns", None)
    )
    if not stable_open_file or not stable_path:
        raise UserLibraryPayloadError(f"{label} changed during verified read")
    if not minimum_bytes <= len(payload) <= maximum_bytes or len(payload) != opened_after.st_size:
        raise UserLibraryPayloadError(f"{label} changed size during verified read")
    return payload


def default_packaged_user_library_root() -> Path:
    return Path(sys.executable).resolve().parent / "release-content" / "user-library"


def _read_manifest(path: Path) -> dict[str, object]:
    payload = _identity_pinned_bytes(
        path,
        label="packaged user Library manifest",
        minimum_bytes=2,
        maximum_bytes=MAX_USER_LIBRARY_MANIFEST_BYTES,
    )
    try:
        parsed = json.loads(payload.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKeyError) as exc:
        raise UserLibraryPayloadError("packaged user Library manifest is invalid") from exc
    if not isinstance(parsed, dict):
        raise UserLibraryPayloadError("packaged user Library manifest root is invalid")
    return parsed


def _source_entry(root: Path, item: object) -> PackagedUserLibrarySource:
    if not isinstance(item, dict):
        raise UserLibraryPayloadError("packaged user Library source entry is invalid")
    if set(item) != {"name", "format", "bytes", "sha256"}:
        raise UserLibraryPayloadError("packaged user Library source fields are invalid")
    name = item["name"]
    source_format = item["format"]
    size_bytes = item["bytes"]
    digest = item["sha256"]
    if type(name) is not str or not name or len(name) > 240:
        raise UserLibraryPayloadError("packaged user Library source name is invalid")
    if Path(name).name != name or "/" in name or "\\" in name or name in {".", ".."}:
        raise UserLibraryPayloadError("packaged user Library source name must be a basename")
    if type(source_format) is not str or source_format.casefold() != "pgn":
        raise UserLibraryPayloadError("packaged user Library source format is unsupported")
    if not name.casefold().endswith(".pgn"):
        raise UserLibraryPayloadError("packaged user Library source extension is inconsistent")
    if type(size_bytes) is not int or not 1 <= size_bytes <= MAX_USER_LIBRARY_SOURCE_BYTES:
        raise UserLibraryPayloadError("packaged user Library source size is invalid")
    if (
        type(digest) is not str
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise UserLibraryPayloadError("packaged user Library source SHA-256 is invalid")

    path = root / name
    info = _regular_file(path, label="packaged user Library source")
    if info.st_size != size_bytes:
        raise UserLibraryPayloadError("packaged user Library source size does not match manifest")
    try:
        evidence = fingerprint(path)
    except (OSError, ValueError) as exc:
        raise UserLibraryPayloadError("packaged user Library source could not be verified") from exc
    if evidence.size != size_bytes or evidence.sha256 != digest:
        raise UserLibraryPayloadError("packaged user Library source bytes do not match manifest")
    return PackagedUserLibrarySource(path, name, "pgn", size_bytes, digest)


def load_packaged_user_library(
    root: str | Path | None = None,
) -> tuple[PackagedUserLibrarySource, ...]:
    resolved = Path(root) if root is not None else default_packaged_user_library_root()
    _regular_directory(resolved)
    manifest = _read_manifest(resolved / "manifest.json")
    if manifest.get("schema_version") != USER_LIBRARY_SCHEMA_VERSION:
        raise UserLibraryPayloadError("packaged user Library schema is unsupported")
    if manifest.get("scope") != USER_LIBRARY_SCOPE:
        raise UserLibraryPayloadError("packaged user Library scope is invalid")
    raw_sources = manifest.get("sources")
    if not isinstance(raw_sources, list) or not 1 <= len(raw_sources) <= MAX_USER_LIBRARY_SOURCES:
        raise UserLibraryPayloadError("packaged user Library source inventory is invalid")
    sources = tuple(_source_entry(resolved, item) for item in raw_sources)
    names = tuple(source.name for source in sources)
    if len(names) != len(set(name.casefold() for name in names)):
        raise UserLibraryPayloadError("packaged user Library source names collide")
    if names != tuple(sorted(names, key=str.casefold)):
        raise UserLibraryPayloadError("packaged user Library source inventory must be sorted")

    expected = {"manifest.json", *names}
    try:
        actual = {entry.name for entry in resolved.iterdir()}
    except OSError as exc:
        raise UserLibraryPayloadError("packaged user Library inventory is unavailable") from exc
    if actual != expected:
        raise UserLibraryPayloadError("packaged user Library contains undeclared files")
    return sources


__all__ = [
    "MAX_USER_LIBRARY_MANIFEST_BYTES",
    "MAX_USER_LIBRARY_SOURCE_BYTES",
    "MAX_USER_LIBRARY_SOURCES",
    "PackagedUserLibrarySource",
    "USER_LIBRARY_SCHEMA_VERSION",
    "USER_LIBRARY_SCOPE",
    "UserLibraryPayloadError",
    "default_packaged_user_library_root",
    "load_packaged_user_library",
]
