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


def fingerprint(path: str | Path, chunk_size: int = 1024 * 1024) -> SourceFingerprint:
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
    after = fingerprint(path)
    return before.size == after.size and before.sha256 == after.sha256


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
    total = {quality.value: 0 for quality in ImportQuality}
    for report in reports:
        for key, value in report.counts.items():
            total[key] += value
    return total
