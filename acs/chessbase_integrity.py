from __future__ import annotations

"""Evidence-backed integrity snapshots for read-only ChessBase-family sources."""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .chessbase_adapter import ChessBaseSourceProbe, probe_chessbase_source
from .import_contract import fingerprint


@dataclass(frozen=True)
class SourceFileEvidence:
    path: Path
    extension: str
    role: str
    size_bytes: int
    sha256: str

    def as_report_fields(self) -> dict[str, object]:
        return {
            "path": self.path.name,
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
            "primary_path": self.primary_path.name,
            "files": [item.as_report_fields() for item in self.files],
        }


class ChessBaseSourceChangedError(RuntimeError):
    """Raised when a source family differs from an earlier integrity snapshot."""


class ChessBaseIntegrityIOError(RuntimeError):
    """Raised when integrity evidence cannot be observed safely."""


def _fingerprint(path: Path, extension: str, role: str) -> SourceFileEvidence:
    try:
        source = fingerprint(path)
    except (OSError, ValueError, RuntimeError) as exc:
        raise ChessBaseIntegrityIOError(
            f"ChessBase source evidence is unavailable for {path.name}"
        ) from exc
    return SourceFileEvidence(
        path=Path(source.path),
        extension=extension,
        role=role,
        size_bytes=source.size,
        sha256=source.sha256,
    )


def _evidence_paths(probe: ChessBaseSourceProbe) -> Iterable[tuple[Path, str, str]]:
    yield probe.path, probe.extension, "primary_source" if probe.is_primary_source else "component_source"
    for component in probe.existing_components:
        yield component.path, component.extension, component.role


def capture_integrity_snapshot(path: str | Path) -> ChessBaseIntegritySnapshot:
    probe = probe_chessbase_source(path)
    if not probe.recognized:
        raise ValueError(f"Unsupported ChessBase-family source: {probe.path.name}")
    if not probe.path.exists() or not probe.path.is_file():
        raise FileNotFoundError(probe.path)

    files = tuple(
        _fingerprint(file_path, extension, role)
        for file_path, extension, role in _evidence_paths(probe)
    )
    return ChessBaseIntegritySnapshot(primary_path=Path(files[0].path), files=files)


def verify_integrity_snapshot(snapshot: ChessBaseIntegritySnapshot) -> ChessBaseIntegritySnapshot:
    """Re-snapshot the family and fail closed on change or unavailable evidence."""
    try:
        current = capture_integrity_snapshot(snapshot.primary_path)
    except (OSError, ValueError, RuntimeError) as exc:
        if isinstance(exc, ChessBaseSourceChangedError):
            raise
        raise ChessBaseIntegrityIOError("ChessBase integrity verification could not read source evidence") from exc
    if current != snapshot:
        raise ChessBaseSourceChangedError(
            "ChessBase source family changed after the integrity snapshot; "
            "discard decoder/import output and keep the original source authoritative."
        )
    return current
