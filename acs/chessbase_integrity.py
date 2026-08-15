from __future__ import annotations

"""Evidence-backed integrity snapshots for read-only ChessBase-family sources.

This module does not decode proprietary formats.  It fingerprints the selected
primary source and any discovered classic CBH companions so adapters can prove
that every source byte remained unchanged across inspection/import attempts.
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable

from .chessbase_adapter import ChessBaseSourceProbe, probe_chessbase_source


@dataclass(frozen=True)
class SourceFileEvidence:
    path: Path
    extension: str
    role: str
    size_bytes: int
    sha256: str

    def as_report_fields(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "extension": self.extension,
            "role": self.role,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class ChessBaseIntegritySnapshot:
    primary_path: Path
    files: tuple[SourceFileEvidence, ...]

    def as_report_fields(self) -> dict[str, object]:
        return {
            "primary_path": str(self.primary_path),
            "files": [item.as_report_fields() for item in self.files],
        }


class ChessBaseSourceChangedError(RuntimeError):
    """Raised when a source family differs from an earlier integrity snapshot."""


def _fingerprint(path: Path, extension: str, role: str) -> SourceFileEvidence:
    digest = sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return SourceFileEvidence(
        path=path,
        extension=extension,
        role=role,
        size_bytes=size,
        sha256=digest.hexdigest(),
    )


def _evidence_paths(probe: ChessBaseSourceProbe) -> Iterable[tuple[Path, str, str]]:
    yield probe.path, probe.extension, "primary_source" if probe.is_primary_source else "component_source"
    for component in probe.existing_components:
        yield component.path, component.extension, component.role


def capture_integrity_snapshot(path: str | Path) -> ChessBaseIntegritySnapshot:
    """Fingerprint a recognized source family without modifying any source file."""
    probe = probe_chessbase_source(path)
    if not probe.recognized:
        raise ValueError(f"Unsupported ChessBase-family source: {probe.path}")
    if not probe.path.exists() or not probe.path.is_file():
        raise FileNotFoundError(probe.path)

    files = tuple(
        _fingerprint(file_path, extension, role)
        for file_path, extension, role in _evidence_paths(probe)
    )
    return ChessBaseIntegritySnapshot(primary_path=probe.path, files=files)


def verify_integrity_snapshot(snapshot: ChessBaseIntegritySnapshot) -> ChessBaseIntegritySnapshot:
    """Re-snapshot the family and fail if membership, size, or content changed."""
    current = capture_integrity_snapshot(snapshot.primary_path)
    if current != snapshot:
        raise ChessBaseSourceChangedError(
            "ChessBase source family changed after the integrity snapshot; "
            "discard decoder/import output and keep the original source authoritative."
        )
    return current
