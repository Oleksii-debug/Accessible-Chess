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
from typing import Iterable

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


def default_packaged_user_library_root() -> Path:
    return Path(sys.executable).resolve().parent / "release-content" / "user-library"


def _read_manifest(path: Path) -> dict[str, object]:
    info = _regular_file(path, label="packaged user Library manifest")
    if info.st_size < 2 or info.st_size > MAX_USER_LIBRARY_MANIFEST_BYTES:
        raise UserLibraryPayloadError("packaged user Library manifest size is invalid")
    try:
        payload = path.read_bytes()
        parsed = json.loads(payload.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, _DuplicateKeyError) as exc:
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
