from __future__ import annotations

"""Provider-neutral HTTPS acquisition for downloadable sound-pack ZIP archives.

The catalogue pins exact archive size and SHA-256. This adapter performs bounded
network acquisition and hostile-ZIP validation before the local SoundPackStore gets
the extracted private staging directory for its independent manifest/asset checks.
"""

import hashlib
import os
import shutil
import stat
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urlsplit

from .sound_profiles import SoundPackCatalogEntry


DEFAULT_MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_EXPANDED_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_MEMBER_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_MEMBERS = 128
DEFAULT_MAX_COMPRESSION_RATIO = 200


def _safe_https_url(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("download URL must be text")
    url = value.strip()
    parts = urlsplit(url)
    if (
        parts.scheme.casefold() != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
    ):
        raise ValueError("sound pack download must remain credential-free HTTPS")
    return url


def _safe_member_name(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("ZIP member name must be text")
    if "\\" in value or "\x00" in value:
        raise ValueError("unsafe ZIP member path")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError("ZIP member must stay below staging root")
    if any(part in {"", "."} for part in path.parts):
        raise ValueError("ZIP member contains empty/current-directory path component")
    if ":" in path.parts[0]:
        raise ValueError("ZIP member must not contain a drive prefix")
    return path.as_posix()


def _member_mode(info: zipfile.ZipInfo) -> int:
    return (info.external_attr >> 16) & 0xFFFF


def _unsafe_member_mode(info: zipfile.ZipInfo) -> str | None:
    """Return a stable rejection reason for unsafe Unix ZIP metadata."""

    mode = _member_mode(info)
    if not mode:
        return None
    kind = stat.S_IFMT(mode)
    if info.is_dir():
        return None if kind in {0, stat.S_IFDIR} else "special file"
    if kind not in {0, stat.S_IFREG}:
        return "special file"
    executable = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    if mode & executable:
        return "executable file mode"
    return None


class HttpsZipSoundPackAcquirer:
    """Download and safely extract one catalogue-pinned sound-pack archive."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
        timeout_seconds: float = 30.0,
        max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
        max_expanded_bytes: int = DEFAULT_MAX_EXPANDED_BYTES,
        max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
        max_members: int = DEFAULT_MAX_MEMBERS,
        max_compression_ratio: int = DEFAULT_MAX_COMPRESSION_RATIO,
    ) -> None:
        if not callable(opener):
            raise TypeError("opener must be callable")
        if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds, (int, float)
        ) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        for name, value in (
            ("max_archive_bytes", max_archive_bytes),
            ("max_expanded_bytes", max_expanded_bytes),
            ("max_member_bytes", max_member_bytes),
            ("max_members", max_members),
            ("max_compression_ratio", max_compression_ratio),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if max_member_bytes > max_expanded_bytes:
            raise ValueError("max_member_bytes cannot exceed max_expanded_bytes")
        self._opener = opener
        self.timeout_seconds = float(timeout_seconds)
        self.max_archive_bytes = max_archive_bytes
        self.max_expanded_bytes = max_expanded_bytes
        self.max_member_bytes = max_member_bytes
        self.max_members = max_members
        self.max_compression_ratio = max_compression_ratio

    @staticmethod
    def _header(response: Any, name: str) -> str | None:
        headers = getattr(response, "headers", None)
        if headers is None:
            return None
        getter = getattr(headers, "get", None)
        if not callable(getter):
            return None
        value = getter(name)
        return str(value).strip() if value is not None else None

    @staticmethod
    def _response_url(response: Any, requested: str) -> str:
        getter = getattr(response, "geturl", None)
        if not callable(getter):
            return requested
        value = getter()
        return requested if value is None else str(value)

    def _download_archive(
        self,
        entry: SoundPackCatalogEntry,
        destination: Path,
    ) -> None:
        if entry.archive_size_bytes > self.max_archive_bytes:
            raise ValueError("sound pack archive exceeds configured size limit")
        requested = _safe_https_url(entry.download_url)
        request = urllib.request.Request(
            requested,
            headers={
                "Accept": "application/zip, application/octet-stream",
                "User-Agent": "AccessibleChess-SoundPack/1",
            },
            method="GET",
        )
        digest = hashlib.sha256()
        count = 0
        with self._opener(request, timeout=self.timeout_seconds) as response:
            final_url = _safe_https_url(self._response_url(response, requested))
            if urlsplit(final_url).scheme.casefold() != "https":
                raise ValueError("sound pack redirect downgraded HTTPS")
            declared = self._header(response, "Content-Length")
            if declared:
                try:
                    declared_size = int(declared)
                except ValueError as exc:
                    raise ValueError("invalid sound pack Content-Length") from exc
                if declared_size != entry.archive_size_bytes:
                    raise ValueError("sound pack Content-Length does not match catalogue")
                if declared_size > self.max_archive_bytes:
                    raise ValueError("sound pack Content-Length exceeds size limit")

            with destination.open("xb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray)):
                        raise TypeError("sound pack response returned non-bytes data")
                    count += len(chunk)
                    if count > self.max_archive_bytes or count > entry.archive_size_bytes:
                        raise ValueError("sound pack archive exceeded declared size")
                    handle.write(chunk)
                    digest.update(chunk)
                handle.flush()
                os.fsync(handle.fileno())

        if count != entry.archive_size_bytes:
            raise ValueError("sound pack archive size does not match catalogue")
        if digest.hexdigest() != entry.archive_sha256:
            raise ValueError("sound pack archive digest does not match catalogue")

    def _validate_members(self, archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, str]]:
        infos = archive.infolist()
        files = [info for info in infos if not info.is_dir()]
        if len(files) > self.max_members:
            raise ValueError("sound pack archive contains too many files")

        total = 0
        normalized: list[tuple[zipfile.ZipInfo, str]] = []
        seen_casefold: set[str] = set()
        manifest_seen = False
        for info in infos:
            name = _safe_member_name(info.filename.rstrip("/") if info.is_dir() else info.filename)
            key = name.casefold()
            if key in seen_casefold:
                raise ValueError("sound pack archive contains duplicate/colliding paths")
            seen_casefold.add(key)
            unsafe_mode = _unsafe_member_mode(info)
            if unsafe_mode is not None:
                raise ValueError(
                    f"sound pack archive contains unsafe {unsafe_mode}: {name}"
                )
            if info.flag_bits & 0x1:
                raise ValueError("encrypted sound pack archives are not supported")

            if info.is_dir():
                normalized.append((info, name))
                continue

            if name == "manifest.json":
                manifest_seen = True
            elif not name.casefold().endswith(".wav"):
                raise ValueError("sound pack archive contains unsupported payload type")

            if info.file_size <= 0:
                raise ValueError("sound pack archive contains an empty file")
            if info.file_size > self.max_member_bytes:
                raise ValueError("sound pack archive member exceeds size limit")
            total += info.file_size
            if total > self.max_expanded_bytes:
                raise ValueError("sound pack archive exceeds expanded size limit")
            compressed = max(1, info.compress_size)
            if info.file_size > compressed * self.max_compression_ratio:
                raise ValueError("sound pack archive member has unsafe compression ratio")
            normalized.append((info, name))

        if not manifest_seen:
            raise ValueError("sound pack archive is missing root manifest.json")
        return normalized

    def _extract(
        self,
        archive_path: Path,
        staging: Path,
    ) -> None:
        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                members = self._validate_members(archive)
                root = staging.resolve()
                for info, name in members:
                    target = (staging / Path(name)).resolve()
                    if target != root and root not in target.parents:
                        raise ValueError("sound pack ZIP member escaped staging root")
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    written = 0
                    with archive.open(info, "r") as source, target.open("xb") as sink:
                        while True:
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > info.file_size or written > self.max_member_bytes:
                                raise ValueError(
                                    "sound pack archive member exceeded validated size"
                                )
                            sink.write(chunk)
                        sink.flush()
                        os.fsync(sink.fileno())
                    if written != info.file_size:
                        raise ValueError("sound pack archive member size changed during extraction")
        except zipfile.BadZipFile as exc:
            raise ValueError("sound pack archive is not a valid ZIP file") from exc

    def acquire(
        self,
        entry: SoundPackCatalogEntry,
        *,
        staging_parent: Path,
    ) -> Path:
        if not isinstance(entry, SoundPackCatalogEntry):
            raise TypeError("entry must be SoundPackCatalogEntry")
        parent = Path(staging_parent)
        parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".sound-download-", dir=parent))
        archive_path = staging / ".archive.zip"
        try:
            self._download_archive(entry, archive_path)
            self._extract(archive_path, staging)
            archive_path.unlink()
            # The install service owns and later removes this returned private tree.
            return staging
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
