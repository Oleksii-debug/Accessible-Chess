from __future__ import annotations

"""Integrity-verified bounded file evidence for classic ChessBase families.

The source family remains authoritative and read-only. This module returns
only evidence-backed metadata and exact opaque CBG payload bytes. It does not
decode moves, variations, annotations, legality, FEN, or PGN, and a successful
evidence window is never an import-success claim.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .chessbase_cbg_payload_evidence import MAX_CLASSIC_CBG_PAYLOAD_BYTES
from .chessbase_cbh import iter_cbh_record_window
from .chessbase_cbh_cbg_batch import read_cbh_records_cbg_payload_evidence
from .chessbase_cbh_evidence import (
    ClassicCbhEvidenceProjection,
    compose_cbh_evidence_projections,
)
from .chessbase_cbh_metadata import read_cbh_records_metadata_projection
from .chessbase_integrity import (
    ChessBaseIntegritySnapshot,
    capture_integrity_snapshot,
    verify_integrity_snapshot,
)


MAX_CLASSIC_EVIDENCE_WINDOW_RECORDS = 1024
_REQUIRED_COMPONENT_EXTENSIONS = (".cbg", ".cbp", ".cbt")


class ChessBaseEvidenceWindowError(ValueError):
    """Raised when a bounded evidence request is invalid."""


class ChessBaseEvidenceBlockedError(ChessBaseEvidenceWindowError):
    """Raised when required evidence sources are unavailable."""

    status = "BLOCKED"


@dataclass(frozen=True)
class ClassicChessBaseEvidenceWindow:
    """Verified partial evidence for one explicit CBH record window."""

    source_snapshot: ChessBaseIntegritySnapshot
    start_record_index: int
    max_records: int
    projection: ClassicCbhEvidenceProjection
    capability_status: Literal["PARTIAL"] = "PARTIAL"
    source_read_only: bool = True
    integrity_verified: bool = True
    decoder_available: bool = False
    safe_to_import: bool = False

    @property
    def returned_count(self) -> int:
        return len(self.projection.items)


def _require_window_bounds(
    *,
    start_record_index: int,
    max_records: int,
    max_payload_bytes: int,
) -> None:
    if (
        not isinstance(start_record_index, int)
        or isinstance(start_record_index, bool)
        or start_record_index < 1
    ):
        raise ChessBaseEvidenceWindowError(
            "start_record_index must be an integer >= 1"
        )
    if (
        not isinstance(max_records, int)
        or isinstance(max_records, bool)
        or max_records < 0
    ):
        raise ChessBaseEvidenceWindowError(
            "max_records must be a non-negative integer"
        )
    if max_records > MAX_CLASSIC_EVIDENCE_WINDOW_RECORDS:
        raise ChessBaseEvidenceWindowError(
            "max_records exceeds the configured evidence-window bound: "
            f"{max_records} > {MAX_CLASSIC_EVIDENCE_WINDOW_RECORDS}"
        )
    if (
        not isinstance(max_payload_bytes, int)
        or isinstance(max_payload_bytes, bool)
        or max_payload_bytes < 0
    ):
        raise ChessBaseEvidenceWindowError(
            "max_payload_bytes must be a non-negative integer"
        )


def _required_component_paths(
    snapshot: ChessBaseIntegritySnapshot,
) -> dict[str, Path]:
    by_extension = {
        item.extension: item.path
        for item in snapshot.files
        if item.extension in _REQUIRED_COMPONENT_EXTENSIONS
    }
    missing = [
        extension
        for extension in _REQUIRED_COMPONENT_EXTENSIONS
        if extension not in by_extension
    ]
    if missing:
        raise ChessBaseEvidenceBlockedError(
            "BLOCKED: classic CBH evidence requires companion files: "
            + ", ".join(missing)
        )
    return by_extension


def read_classic_chessbase_evidence_window(
    cbh_path: str | Path,
    *,
    start_record_index: int,
    max_records: int,
    max_payload_bytes: int = MAX_CLASSIC_CBG_PAYLOAD_BYTES,
) -> ClassicChessBaseEvidenceWindow:
    """Read one bounded window and reject all output if the family changes.

    A pre-read integrity snapshot covers the primary CBH and every discovered
    companion, including optional components. The same family is fingerprinted
    again after all bounded reads. Any membership, size, or byte change raises
    ``ChessBaseSourceChangedError`` before evidence can be returned.
    """

    _require_window_bounds(
        start_record_index=start_record_index,
        max_records=max_records,
        max_payload_bytes=max_payload_bytes,
    )
    source = Path(cbh_path)
    if source.suffix.lower() != ".cbh":
        raise ChessBaseEvidenceBlockedError(
            "BLOCKED: classic file evidence requires the primary .cbh source"
        )

    before = capture_integrity_snapshot(source)
    components = _required_component_paths(before)
    records = tuple(
        iter_cbh_record_window(
            source,
            start_record_index=start_record_index,
            max_records=max_records,
        )
    )
    payload_projection = read_cbh_records_cbg_payload_evidence(
        records,
        components[".cbg"],
        max_payload_bytes=max_payload_bytes,
    )
    metadata_projection = read_cbh_records_metadata_projection(
        records,
        components[".cbp"],
        components[".cbt"],
    )
    projection = compose_cbh_evidence_projections(
        payload_projection,
        metadata_projection,
    )
    verified = verify_integrity_snapshot(before)
    return ClassicChessBaseEvidenceWindow(
        source_snapshot=verified,
        start_record_index=start_record_index,
        max_records=max_records,
        projection=projection,
    )
