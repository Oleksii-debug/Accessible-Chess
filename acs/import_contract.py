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
import re


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path or "\x00" in self.path:
            raise TypeError("fingerprint path must be non-empty text without NUL")
        if type(self.size) is not int:
            raise TypeError("fingerprint size must be an integer")
        if self.size < 0:
            raise ValueError("fingerprint size must be non-negative")
        if not isinstance(self.sha256, str) or _SHA256_RE.fullmatch(self.sha256) is None:
            raise ValueError("fingerprint sha256 must be 64 lowercase hexadecimal characters")
        if not isinstance(self.suffix, str):
            raise TypeError("fingerprint suffix must be text")
        if self.suffix and (
            not self.suffix.startswith(".")
            or self.suffix != self.suffix.lower()
            or any(character in self.suffix for character in ("/", "\\", "\x00"))
            or any(character.isspace() for character in self.suffix)
        ):
            raise ValueError("fingerprint suffix must be a canonical lowercase extension")


@dataclass(frozen=True)
class ImportedRecord:
    source_record_id: str
    quality: ImportQuality
    game_id: int | None = None
    message: str = ""
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_record_id, str)
            or not self.source_record_id.strip()
            or "\n" in self.source_record_id
            or "\r" in self.source_record_id
        ):
            raise ValueError("source_record_id must be non-empty single-line text")
        if not isinstance(self.quality, ImportQuality):
            raise TypeError("quality must be ImportQuality")
        if self.game_id is not None:
            if type(self.game_id) is not int:
                raise TypeError("game_id must be an integer or None")
            if self.game_id < 0:
                raise ValueError("game_id must be non-negative")
        if not isinstance(self.message, str):
            raise TypeError("record message must be text")
        if (
            not isinstance(self.warnings, tuple)
            or any(
                not isinstance(warning, str) or not warning.strip()
                for warning in self.warnings
            )
        ):
            raise TypeError("record warnings must be a tuple of non-empty text")


@dataclass
class ImportReport:
    source: SourceFingerprint
    format_name: str
    records: list[ImportedRecord] = field(default_factory=list)
    global_warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.validate()
        self.records = list(self.records)
        self.global_warnings = list(self.global_warnings)

    def validate(self) -> None:
        if not isinstance(self.source, SourceFingerprint):
            raise TypeError("report source must be SourceFingerprint")
        if (
            not isinstance(self.format_name, str)
            or not self.format_name.strip()
            or self.format_name != self.format_name.strip()
            or "\n" in self.format_name
            or "\r" in self.format_name
        ):
            raise ValueError("format_name must be stable non-empty single-line text")
        if (
            not isinstance(self.records, list)
            or any(not isinstance(record, ImportedRecord) for record in self.records)
        ):
            raise TypeError("records must be a list of ImportedRecord")
        if (
            not isinstance(self.global_warnings, list)
            or any(
                not isinstance(warning, str) or not warning.strip()
                for warning in self.global_warnings
            )
        ):
            raise TypeError("global_warnings must be a list of non-empty text")

    def add(self, record: ImportedRecord) -> None:
        self.validate()
        if not isinstance(record, ImportedRecord):
            raise TypeError("record must be ImportedRecord")
        self.records.append(record)

    def detached(self) -> "ImportReport":
        self.validate()
        return ImportReport(
            source=self.source,
            format_name=self.format_name,
            records=list(self.records),
            global_warnings=list(self.global_warnings),
        )

    @property
    def counts(self) -> dict[str, int]:
        self.validate()
        result = {quality.value: 0 for quality in ImportQuality}
        for record in self.records:
            result[record.quality.value] += 1
        return result

    @property
    def total(self) -> int:
        self.validate()
        return len(self.records)

    @property
    def has_damage(self) -> bool:
        self.validate()
        return any(record.quality is ImportQuality.DAMAGED for record in self.records)


class ReadOnlyImporter(Protocol):
    format_name: str
    suffixes: tuple[str, ...]

    def inspect(self, path: Path) -> ImportReport:
        ...


def fingerprint(path: str | Path, chunk_size: int = 1024 * 1024) -> SourceFingerprint:
    if not isinstance(path, (str, Path)):
        raise TypeError("path must be text or Path")
    if isinstance(path, str) and "\x00" in path:
        raise ValueError("path must not contain NUL")
    if type(chunk_size) is not int:
        raise TypeError("chunk_size must be an integer")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    p = Path(path)
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    stat = p.stat()
    return SourceFingerprint(
        path=str(p.resolve()),
        size=stat.st_size,
        sha256=digest.hexdigest(),
        suffix=p.suffix.lower(),
    )


def verify_source_unchanged(before: SourceFingerprint, path: str | Path) -> bool:
    if not isinstance(before, SourceFingerprint):
        raise TypeError("before must be SourceFingerprint")
    after = fingerprint(path)
    return (
        before.path == after.path
        and before.size == after.size
        and before.sha256 == after.sha256
        and before.suffix == after.suffix
    )


class UnsupportedChessBaseImporter:
    """Safety placeholder until a verified decoder exists.

    It recognizes ChessBase-family suffixes but intentionally refuses to claim
    successful decoding.  This prevents future UI code from treating an
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
    if isinstance(reports, (str, bytes)):
        raise TypeError("reports must be an iterable of ImportReport")
    try:
        queued = tuple(reports)
    except TypeError as exc:
        raise TypeError("reports must be an iterable of ImportReport") from exc
    for report in queued:
        if not isinstance(report, ImportReport):
            raise TypeError("reports must contain only ImportReport values")
        report.validate()
    total = {quality.value: 0 for quality in ImportQuality}
    for report in queued:
        for key, value in report.counts.items():
            total[key] += value
    return total
