from __future__ import annotations

"""Local real-video catalog and integrity boundary for Sections 47 and 50.

The catalog is metadata only. Third-party video bytes are never committed to the
public source tree by this module. Test/owner bundles may materialize verified
copies in an explicitly chosen library directory.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import urlparse

CATALOG_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SUPPORTED = frozenset({".webm", ".mp4"})
_ALLOWED_SOURCE_HOSTS = frozenset({"upload.wikimedia.org"})


class LocalVideoCatalogError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RealVideoEntry:
    video_id: str
    filename: str
    title: str
    source_page: str
    download_url: str
    author: str
    license_id: str
    license_url: str
    duration_seconds: float
    media_type: str
    expected_sha256: str | None
    last_checked: str

    def __post_init__(self) -> None:
        for name in ("video_id", "filename", "title", "source_page", "download_url",
                     "author", "license_id", "license_url", "media_type", "last_checked"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip() or value != value.strip() or "\x00" in value:
                raise LocalVideoCatalogError(f"invalid {name}")
        if Path(self.filename).name != self.filename or Path(self.filename).suffix.lower() not in _SUPPORTED:
            raise LocalVideoCatalogError("video filename must be a safe MP4/WebM basename")
        parsed = urlparse(self.download_url)
        if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_SOURCE_HOSTS:
            raise LocalVideoCatalogError("real-video source must be an approved HTTPS Wikimedia host")
        if not self.source_page.startswith("https://commons.wikimedia.org/wiki/File:"):
            raise LocalVideoCatalogError("source_page must be a Wikimedia Commons File page")
        if type(self.duration_seconds) not in (int, float) or not 0 < float(self.duration_seconds) < 24 * 60 * 60:
            raise LocalVideoCatalogError("duration_seconds is invalid")
        if self.expected_sha256 is not None and (
            type(self.expected_sha256) is not str or _SHA256.fullmatch(self.expected_sha256) is None
        ):
            raise LocalVideoCatalogError("expected_sha256 must be lowercase SHA-256 or null")

    @property
    def qualified(self) -> bool:
        return self.expected_sha256 is not None


def _entry(value: Mapping[str, object]) -> RealVideoEntry:
    required = {
        "video_id", "filename", "title", "source_page", "download_url", "author",
        "license_id", "license_url", "duration_seconds", "media_type",
        "expected_sha256", "last_checked",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise LocalVideoCatalogError("invalid real-video catalog entry")
    return RealVideoEntry(**value)  # type: ignore[arg-type]


def load_real_video_catalog(path: str | Path) -> tuple[RealVideoEntry, ...]:
    source = Path(path)
    try:
        raw = source.read_text(encoding="utf-8")
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LocalVideoCatalogError("real-video catalog is unreadable") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "videos"}:
        raise LocalVideoCatalogError("invalid real-video catalog")
    if value["schema_version"] != CATALOG_SCHEMA_VERSION or type(value["videos"]) is not list:
        raise LocalVideoCatalogError("unsupported real-video catalog schema")
    entries = tuple(_entry(item) for item in value["videos"])
    if not entries or len(entries) > 32:
        raise LocalVideoCatalogError("real-video catalog size is invalid")
    ids = [item.video_id for item in entries]
    names = [item.filename.casefold() for item in entries]
    if len(ids) != len(set(ids)) or len(names) != len(set(names)):
        raise LocalVideoCatalogError("real-video catalog contains duplicate identities")
    return entries


def sha256_file(path: str | Path, *, max_bytes: int = 512 * 1024 * 1024) -> str:
    source = Path(path)
    size = source.stat().st_size
    if not 0 < size <= max_bytes:
        raise LocalVideoCatalogError("video size is outside the safety bound")
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        remaining = max_bytes + 1
        while True:
            chunk = stream.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
            if remaining < 0:
                raise LocalVideoCatalogError("video exceeds the hash bound")
    return digest.hexdigest()


def verify_real_video(entry: RealVideoEntry, path: str | Path) -> dict[str, object]:
    if type(entry) is not RealVideoEntry:
        raise TypeError("entry must be RealVideoEntry")
    source = Path(path)
    if source.name != entry.filename:
        raise LocalVideoCatalogError("video filename does not match catalog")
    if not entry.qualified:
        raise LocalVideoCatalogError("video has not been SHA-256 qualified")
    actual = sha256_file(source)
    if actual != entry.expected_sha256:
        raise LocalVideoCatalogError("real-video SHA-256 mismatch")
    prefix = source.read_bytes()[:16]
    suffix = source.suffix.lower()
    if suffix == ".webm" and not prefix.startswith(b"\x1aE\xdf\xa3"):
        raise LocalVideoCatalogError("WebM EBML signature is invalid")
    if suffix == ".mp4" and b"ftyp" not in prefix:
        raise LocalVideoCatalogError("MP4 ftyp signature is invalid")
    return {
        "video_id": entry.video_id,
        "filename": entry.filename,
        "sha256": actual,
        "size_bytes": source.stat().st_size,
        "media_type": entry.media_type,
        "license_id": entry.license_id,
    }
