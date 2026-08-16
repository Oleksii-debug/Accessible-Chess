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


@dataclass(frozen=True)
class ClassicChessBaseFileOutcome:
    """Verified file-family integrity plus either projection or decoder error.

    Decoder failures are data, not guessed semantics. An outcome is returned
    only when the source-family snapshot still verifies after the failed read.
    If the family changed, ``ChessBaseSourceChangedError`` remains authoritative
    and no stale decoder outcome is returned.
    """

    cbh_path: Path
    cbg_path: Path
    cbp_path: Path
    cbt_path: Path
    before: ChessBaseIntegritySnapshot
    after: ChessBaseIntegritySnapshot
    records: ClassicCbhEvidenceProjection | None
    error_type: str | None
    error_message: str | None

    @property
    def succeeded(self) -> bool:
        return self.records is not None and self.error_type is None


def _required_companion(cbh_path: Path, extension: str) -> Path:
    companion = cbh_path.with_suffix(extension)
    if not companion.exists() or not companion.is_file():
        raise FileNotFoundError(companion)
    return companion


def _classic_paths(cbh_path: str | Path) -> tuple[Path, Path, Path, Path]:
    source = Path(cbh_path)
    if source.suffix.lower() != ".cbh":
        raise ValueError(f"classic file evidence requires a .cbh source: {source}")
    return (
        source,
        _required_companion(source, ".cbg"),
        _required_companion(source, ".cbp"),
        _required_companion(source, ".cbt"),
    )


def _read_classic_projection(
    source: Path,
    cbg_path: Path,
    cbp_path: Path,
    cbt_path: Path,
) -> ClassicCbhEvidenceProjection:
    records = tuple(iter_cbh_records(source))
    return project_cbh_record_evidence(
        records,
        cbg_path.read_bytes(),
        cbp_path.read_bytes(),
        cbt_path.read_bytes(),
    )


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

    source, cbg_path, cbp_path, cbt_path = _classic_paths(cbh_path)
    before = capture_integrity_snapshot(source)
    projection = _read_classic_projection(source, cbg_path, cbp_path, cbt_path)
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


def inspect_classic_chessbase_file_evidence(
    cbh_path: str | Path,
) -> ClassicChessBaseFileOutcome:
    """Return verified integrity evidence even when neutral decoding fails.

    Required-family validation remains explicit before the snapshot. Once the
    family is valid, decoder exceptions are preserved by exact exception class
    name and message. The source snapshot is always verified after the attempt;
    a source mutation raises the existing integrity error instead of returning
    an outcome that could describe bytes that are no longer authoritative.
    """

    source, cbg_path, cbp_path, cbt_path = _classic_paths(cbh_path)
    before = capture_integrity_snapshot(source)

    projection: ClassicCbhEvidenceProjection | None = None
    error_type: str | None = None
    error_message: str | None = None
    try:
        projection = _read_classic_projection(source, cbg_path, cbp_path, cbt_path)
    except Exception as error:
        error_type = type(error).__name__
        error_message = str(error)

    after = verify_integrity_snapshot(before)
    return ClassicChessBaseFileOutcome(
        cbh_path=source,
        cbg_path=cbg_path,
        cbp_path=cbp_path,
        cbt_path=cbt_path,
        before=before,
        after=after,
        records=projection,
        error_type=error_type,
        error_message=error_message,
    )
