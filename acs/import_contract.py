from __future__ import annotations

"""Read-only import contract for external chess database families.

This module deliberately does not decode proprietary ChessBase formats yet.
It establishes the safety and reporting boundary every future decoder must
obey: never mutate the source, preserve provenance, and report full/partial/
damaged outcomes explicitly instead of silently dropping records.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Protocol
import hashlib
import os
import stat


class ImportQuality(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    DAMAGED = "damaged"
    WARNING = "warning"


@dataclass(frozen=True)
class SourceFingerprint:
    path: str
    size: int
    sha256: str
    suffix: str


@dataclass(frozen=True)
class ImportedRecord:
    source_record_id: str
    quality: ImportQuality
    game_id: int | None = None
    message: str = ""
    warnings: tuple[str, ...] = ()


@dataclass
class ImportReport:
    source: SourceFingerprint
    format_name: str
    records: list[ImportedRecord] = field(default_factory=list)
    global_warnings: list[str] = field(default_factory=list)

    def add(self, record: ImportedRecord) -> None:
        self.records.append(record)

    @property
    def counts(self) -> dict[str, int]:
        result = {quality.value: 0 for quality in ImportQuality}
        for record in self.records:
            result[record.quality.value] += 1
        return result

    @property
    def total(self) -> int:
        return len(self.records)

    @property
    def has_damage(self) -> bool:
        return any(record.quality is ImportQuality.DAMAGED for record in self.records)


class ReadOnlyImporter(Protocol):
    format_name: str
    suffixes: tuple[str, ...]

    def inspect(self, path: Path) -> ImportReport:
        ...


def _is_reparse_point(st: os.stat_result) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & marker)


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _validate_source_path(path: Path) -> tuple[Path, os.stat_result]:
    """Reject filesystem indirection and non-regular external sources.

    Validation is intentionally lexical: it must not call ``resolve()`` before
    deciding whether any path component is a symlink/reparse point.
    """

    absolute = _lexical_absolute(path)
    parts = absolute.parts
    if not parts:
        raise ValueError("Import source path is empty")

    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        try:
            st = current.lstat()
        except FileNotFoundError:
            if current == absolute:
                raise
            continue
        if stat.S_ISLNK(st.st_mode) or _is_reparse_point(st):
            raise ValueError("Import source must not traverse filesystem indirection")

    leaf = absolute.lstat()
    if stat.S_ISLNK(leaf.st_mode) or _is_reparse_point(leaf):
        raise ValueError("Import source must not be a symlink or reparse point")
    if not stat.S_ISREG(leaf.st_mode):
        raise ValueError("Import source must be a regular file")
    return absolute, leaf


def fingerprint(path: str | Path, chunk_size: int = 1024 * 1024) -> SourceFingerprint:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    submitted = Path(path)
    absolute, path_before = _validate_source_path(submitted)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(os.fspath(absolute), flags)
    try:
        fd_before = os.fstat(fd)
        if not stat.S_ISREG(fd_before.st_mode):
            raise ValueError("Import source must be a regular file")
        if (fd_before.st_dev, fd_before.st_ino) != (path_before.st_dev, path_before.st_ino):
            raise ValueError("Import source changed before it could be opened safely")

        def digest_open_inode() -> str:
            digest = hashlib.sha256()
            while True:
                chunk = os.read(fd, chunk_size)
                if not chunk:
                    return digest.hexdigest()
                digest.update(chunk)

        first_sha256 = digest_open_inode()

        # A same-size in-place writer can race inside the first hash pass and,
        # on filesystems with coarse timestamp updates, leave mtime_ns looking
        # unchanged. Re-hash the exact already-open inode so provenance is
        # published only when two complete byte snapshots agree.
        os.lseek(fd, 0, os.SEEK_SET)
        verified_sha256 = digest_open_inode()
        if first_sha256 != verified_sha256:
            raise ValueError("Import source changed while fingerprinting")
        fd_after = os.fstat(fd)
    finally:
        os.close(fd)

    path_after = absolute.lstat()
    stable_fd = (
        fd_before.st_dev == fd_after.st_dev
        and fd_before.st_ino == fd_after.st_ino
        and fd_before.st_size == fd_after.st_size
        and fd_before.st_mtime_ns == fd_after.st_mtime_ns
    )
    stable_path = (
        path_before.st_dev == path_after.st_dev
        and path_before.st_ino == path_after.st_ino
        and path_before.st_size == path_after.st_size
        and path_before.st_mtime_ns == path_after.st_mtime_ns
        and not stat.S_ISLNK(path_after.st_mode)
        and not _is_reparse_point(path_after)
    )
    if not stable_fd or not stable_path:
        raise ValueError("Import source changed while fingerprinting")

    return SourceFingerprint(
        path=str(absolute),
        size=fd_after.st_size,
        sha256=verified_sha256,
        suffix=submitted.suffix.lower(),
    )


def verify_source_unchanged(before: SourceFingerprint, path: str | Path) -> bool:
    after = fingerprint(path)
    return before.size == after.size and before.sha256 == after.sha256


class UnsupportedChessBaseImporter:
    """Safety placeholder until a verified decoder exists.

    It recognizes ChessBase-family suffixes but intentionally refuses to claim
    successful decoding. This prevents future UI code from treating an
    unimplemented or heuristic parser as full compatibility.
    """

    format_name = "ChessBase family (decoder pending verification)"
    suffixes = (".cbh", ".cbv", ".cbf", ".2cbh")

    def inspect(self, path: Path) -> ImportReport:
        source = fingerprint(path)
        report = ImportReport(source=source, format_name=self.format_name)
        if source.suffix not in self.suffixes:
            report.global_warnings.append(f"Unsupported suffix: {source.suffix or '<none>'}")
            return report
        report.add(
            ImportedRecord(
                source_record_id="container",
                quality=ImportQuality.WARNING,
                message="Recognized ChessBase-family container; verified decoder not implemented yet.",
                warnings=("No source bytes were modified.",),
            )
        )
        return report


def summarize_reports(reports: Iterable[ImportReport]) -> dict[str, int]:
    total = {quality.value: 0 for quality in ImportQuality}
    for report in reports:
        for key, value in report.counts.items():
            total[key] += value
    return total
