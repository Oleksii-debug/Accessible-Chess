from __future__ import annotations

"""Neutral, read-only inspection reports for ChessBase-family sources.

Inspection is intentionally not decoding.  This module combines filename/family
probing with immutable source evidence and exposes one presentation-neutral DTO
that UI, import workflows and ACSDB provenance code can consume without learning
proprietary file-layout details.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .chessbase_adapter import probe_chessbase_source
from .chessbase_manifest import (
    MANIFEST_SCHEMA_VERSION,
    ChessBaseBundleManifest,
    build_chessbase_manifest,
    total_manifest_bytes,
)

INSPECTION_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ChessBaseInspectionReport:
    schema_version: int
    source_path: str
    source_kind: str
    family_name: str
    extension: str
    recognized: bool
    is_primary_source: bool
    read_only: bool
    decoder_available: bool
    source_status: str
    decode_status: str
    evidence_schema_version: int
    evidence_files: int
    evidence_bytes: int
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def can_decode(self) -> bool:
        return self.recognized and self.is_primary_source and self.decoder_available

    @property
    def safe_for_source_preserving_workflow(self) -> bool:
        return self.read_only and self.source_status not in {"damaged", "unsupported"}

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_path": self.source_path,
            "source_kind": self.source_kind,
            "family_name": self.family_name,
            "extension": self.extension,
            "recognized": self.recognized,
            "is_primary_source": self.is_primary_source,
            "read_only": self.read_only,
            "decoder_available": self.decoder_available,
            "can_decode": self.can_decode,
            "safe_for_source_preserving_workflow": self.safe_for_source_preserving_workflow,
            "source_status": self.source_status,
            "decode_status": self.decode_status,
            "evidence_schema_version": self.evidence_schema_version,
            "evidence_files": self.evidence_files,
            "evidence_bytes": self.evidence_bytes,
            "warnings": list(self.warnings),
        }


def _decode_status(decoder_available: bool) -> str:
    return "available" if decoder_available else "unavailable"


def _build_report(path: str | Path, manifest: ChessBaseBundleManifest) -> ChessBaseInspectionReport:
    probe = probe_chessbase_source(path)
    warnings = list(manifest.warnings)

    # Never allow evidence collection to be mistaken for successful format support.
    if probe.recognized and probe.is_primary_source and not probe.decoder_available:
        warnings.append(
            "Source recognition/evidence collection is not decoding; no games were imported."
        )

    return ChessBaseInspectionReport(
        schema_version=INSPECTION_SCHEMA_VERSION,
        source_path=manifest.primary_path,
        source_kind=probe.source_kind,
        family_name=probe.family_name,
        extension=probe.extension,
        recognized=probe.recognized,
        is_primary_source=probe.is_primary_source,
        read_only=probe.read_only,
        decoder_available=probe.decoder_available,
        source_status=manifest.status,
        decode_status=_decode_status(probe.decoder_available),
        evidence_schema_version=manifest.schema_version,
        evidence_files=len(manifest.all_evidence),
        evidence_bytes=total_manifest_bytes(manifest),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def inspect_chessbase_source(path: str | Path) -> ChessBaseInspectionReport:
    """Inspect one source without modifying it or claiming unsupported decoding."""
    manifest = build_chessbase_manifest(path)
    return _build_report(path, manifest)


def inspect_many_chessbase_sources(
    paths: Iterable[str | Path],
) -> tuple[ChessBaseInspectionReport, ...]:
    """Inspect sources independently so one damaged item cannot hide later items."""
    return tuple(inspect_chessbase_source(path) for path in paths)


def summarize_chessbase_inspections(
    reports: Iterable[ChessBaseInspectionReport],
) -> dict[str, int]:
    """Return stable status counts suitable for import/source-report surfaces."""
    counts: dict[str, int] = {
        "evidence_collected": 0,
        "partial": 0,
        "damaged": 0,
        "component_only": 0,
        "unsupported": 0,
        "decoder_available": 0,
        "decoder_unavailable": 0,
    }
    for report in reports:
        counts.setdefault(report.source_status, 0)
        counts[report.source_status] += 1
        key = "decoder_available" if report.decoder_available else "decoder_unavailable"
        counts[key] += 1
    return counts


__all__ = [
    "INSPECTION_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "ChessBaseInspectionReport",
    "inspect_chessbase_source",
    "inspect_many_chessbase_sources",
    "summarize_chessbase_inspections",
]
