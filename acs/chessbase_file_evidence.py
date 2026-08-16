"""Read-only file-level classic ChessBase evidence projection.

This boundary composes existing neutral CBH/CBG/CBP/CBT adapters only. It
fingerprints the source family before reading and verifies the same snapshot
after projection so decoder output is rejected if any source byte changes.

Classic layout evidence ultimately comes from cbh2pgn pinned at
42b3592738062db1f768239e85df1b98cb1cead9.
Original cbh2pgn copyright (c) 2022 Dominik Klein, MIT License.
No move, FEN, legality, annotation, or undocumented proprietary semantics are
decoded here, and no GPL ``python-chess`` runtime dependency is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .chessbase_cbh import iter_cbh_records
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
class ClassicChessBaseFileEvidence:
    """File-level evidence accepted only when source integrity is unchanged."""

    cbh_path: Path
    cbg_path: Path
    cbp_path: Path
    cbt_path: Path
    before: ChessBaseIntegritySnapshot
    after: ChessBaseIntegritySnapshot
    records: ClassicCbhEvidenceProjection


def _required_companion(cbh_path: Path, extension: str) -> Path:
    companion = cbh_path.with_suffix(extension)
    if not companion.exists() or not companion.is_file():
        raise FileNotFoundError(companion)
    return companion


def project_classic_chessbase_file_evidence(
    cbh_path: str | Path,
) -> ClassicChessBaseFileEvidence:
    """Project one classic CBH family without modifying or trusting changed input.

    The exact source-family snapshot is captured before any decoder reads. The
    current CBH records and exact CBG/CBP/CBT bytes are then passed to existing
    neutral adapters. A second snapshot must equal the first; otherwise
    ``ChessBaseSourceChangedError`` is raised by ``verify_integrity_snapshot``
    and the projection is discarded by the caller.
    """

    source = Path(cbh_path)
    if source.suffix.lower() != ".cbh":
        raise ValueError(f"classic file evidence requires a .cbh source: {source}")

    cbg_path = _required_companion(source, ".cbg")
    cbp_path = _required_companion(source, ".cbp")
    cbt_path = _required_companion(source, ".cbt")

    before = capture_integrity_snapshot(source)
    records = tuple(iter_cbh_records(source))
    cbg_data = cbg_path.read_bytes()
    cbp_data = cbp_path.read_bytes()
    cbt_data = cbt_path.read_bytes()

    projection = project_cbh_record_evidence(
        records,
        cbg_data,
        cbp_data,
        cbt_data,
    )
    after = verify_integrity_snapshot(before)

    return ClassicChessBaseFileEvidence(
        cbh_path=source,
        cbg_path=cbg_path,
        cbp_path=cbp_path,
        cbt_path=cbt_path,
        before=before,
        after=after,
        records=projection,
    )
