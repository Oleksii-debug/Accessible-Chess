"""Deterministic neutral reports for verified classic ChessBase file outcomes.

This layer serializes only evidence already established by the read-only file
inspection boundary: source fingerprints, per-record outcome counts, and exact
failure fields. It does not expose opaque payload bytes or decode new ChessBase
semantics.

Classic layout evidence ultimately comes from cbh2pgn pinned at
42b3592738062db1f768239e85df1b98cb1cead9.
Original cbh2pgn copyright (c) 2022 Dominik Klein, MIT License.
No GPL ``python-chess`` runtime dependency is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass

from .chessbase_file_evidence import ClassicChessBaseFileOutcome


@dataclass(frozen=True)
class ClassicChessBaseSourceReport:
    path: str
    extension: str
    role: str
    size_bytes: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "extension": self.extension,
            "role": self.role,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class ClassicChessBaseFileReport:
    status: str
    primary_path: str
    sources: tuple[ClassicChessBaseSourceReport, ...]
    record_count: int | None
    complete_count: int | None
    partial_count: int | None
    skipped_count: int | None
    failed_count: int | None
    error_type: str | None
    error_message: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "primary_path": self.primary_path,
            "sources": [source.as_dict() for source in self.sources],
            "record_count": self.record_count,
            "complete_count": self.complete_count,
            "partial_count": self.partial_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


def project_classic_chessbase_file_report(
    outcome: ClassicChessBaseFileOutcome,
) -> ClassicChessBaseFileReport:
    """Project a verified outcome into a stable higher-layer report DTO.

    The outcome must already have passed source-family integrity verification.
    Successful projections expose only aggregate record statuses. Decoder-level
    failures keep record counts unavailable instead of inventing partial facts.
    Exact exception class name and message are preserved unchanged.
    """

    if outcome.before != outcome.after:
        raise ValueError("file report requires matching verified integrity snapshots")

    sources = tuple(
        ClassicChessBaseSourceReport(
            path=str(item.path),
            extension=item.extension,
            role=item.role,
            size_bytes=item.size_bytes,
            sha256=item.sha256,
        )
        for item in outcome.after.files
    )

    if outcome.records is None:
        if outcome.error_type is None:
            raise ValueError("failed file outcome requires an explicit decoder error type")
        return ClassicChessBaseFileReport(
            status="failed",
            primary_path=str(outcome.cbh_path),
            sources=sources,
            record_count=None,
            complete_count=None,
            partial_count=None,
            skipped_count=None,
            failed_count=None,
            error_type=outcome.error_type,
            error_message=outcome.error_message,
        )

    if outcome.error_type is not None or outcome.error_message is not None:
        raise ValueError("successful file outcome cannot carry decoder failure fields")

    records = outcome.records
    return ClassicChessBaseFileReport(
        status="succeeded",
        primary_path=str(outcome.cbh_path),
        sources=sources,
        record_count=len(records.items),
        complete_count=records.complete_count,
        partial_count=records.partial_count,
        skipped_count=records.skipped_count,
        failed_count=records.failed_count,
        error_type=None,
        error_message=None,
    )
