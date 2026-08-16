"""Bounded read-only classic ChessBase file-family evidence projection.

This module composes the evidence-backed fixed-size CBH record window with the
existing neutral CBH/CBG/CBP/CBT evidence adapters. It deliberately does not
decode move, FEN, legality, annotation, or undocumented proprietary semantics.

Classic layout evidence ultimately comes from cbh2pgn pinned at
42b3592738062db1f768239e85df1b98cb1cead9.
Original cbh2pgn copyright (c) 2022 Dominik Klein, MIT License.
No GPL ``python-chess`` runtime dependency is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .chessbase_cbh import iter_cbh_record_window
from .chessbase_cbh_evidence import (
    ClassicCbhEvidenceProjection,
    project_cbh_record_evidence,
)
from .chessbase_integrity import (
    ChessBaseIntegritySnapshot,
    capture_integrity_snapshot,
    verify_integrity_snapshot,
)


@dataclass(frozen=True)
class ClassicChessBaseWindowEvidence:
    """Verified evidence for one exact bounded CBH record window."""

    cbh_path: Path
    cbg_path: Path
    cbp_path: Path
    cbt_path: Path
    start_record_index: int
    max_records: int
    before: ChessBaseIntegritySnapshot
    after: ChessBaseIntegritySnapshot
    records: ClassicCbhEvidenceProjection


def _required_companion(cbh_path: Path, extension: str) -> Path:
    companion = cbh_path.with_suffix(extension)
    if not companion.exists() or not companion.is_file():
        raise FileNotFoundError(companion)
    return companion


def _classic_paths(cbh_path: str | Path) -> tuple[Path, Path, Path, Path]:
    source = Path(cbh_path)
    if source.suffix.lower() != ".cbh":
        raise ValueError(f"classic window evidence requires a .cbh source: {source}")
    return (
        source,
        _required_companion(source, ".cbg"),
        _required_companion(source, ".cbp"),
        _required_companion(source, ".cbt"),
    )


def project_classic_chessbase_window_evidence(
    cbh_path: str | Path,
    *,
    start_record_index: int,
    max_records: int,
) -> ClassicChessBaseWindowEvidence:
    """Project a bounded CBH record window under source-family integrity checks.

    Only the requested fixed-size CBH records are parsed. Existing companion
    adapters receive the exact immutable CBG/CBP/CBT bytes needed to resolve
    record offsets. The complete classic source-family snapshot is captured
    before decoding and must verify unchanged afterwards; if any source changes,
    ``ChessBaseSourceChangedError`` is raised by ``verify_integrity_snapshot``
    and the projection is discarded.
    """

    if start_record_index < 1:
        raise ValueError("start_record_index must be >= 1")
    if max_records < 0:
        raise ValueError("max_records must be >= 0")

    source, cbg_path, cbp_path, cbt_path = _classic_paths(cbh_path)
    before = capture_integrity_snapshot(source)
    records = tuple(
        iter_cbh_record_window(
            source,
            start_record_index=start_record_index,
            max_records=max_records,
        )
    )
    projection = project_cbh_record_evidence(
        records,
        cbg_path.read_bytes(),
        cbp_path.read_bytes(),
        cbt_path.read_bytes(),
    )
    after = verify_integrity_snapshot(before)

    return ClassicChessBaseWindowEvidence(
        cbh_path=source,
        cbg_path=cbg_path,
        cbp_path=cbp_path,
        cbt_path=cbt_path,
        start_record_index=start_record_index,
        max_records=max_records,
        before=before,
        after=after,
        records=projection,
    )
