from __future__ import annotations

"""Evidence-backed integrity snapshots for read-only ChessBase-family sources."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable
import os
import stat

from .chessbase_adapter import ChessBaseSourceProbe, probe_chessbase_source
from .report_paths import report_safe_name


@dataclass(frozen=True)
class SourceFileEvidence:
    path: Path
    extension: str
    role: str
    size_bytes: int
    sha256: str

    def as_report_fields(self) -> dict[str, object]:
        return {
            "path": report_safe_name(self.path),
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
            "primary_path": report_safe_name(self.primary_path),
            "files": [item.as_report_fields() for item in self.files],
        }


class ChessBaseSourceChangedError(RuntimeError):
    """Raised when a source family differs from an earlier integrity snapshot."""


class ChessBaseIntegrityIOError(RuntimeError):
    """Raised when integrity evidence cannot be observed safely."""


def _is_reparse_point(st: os.stat_result) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & marker)


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _stable_file_metadata(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        _same_file_identity(left, right)
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
    )


def _fingerprint(path: Path, extension: str, role: str) -> SourceFileEvidence:
    safe_name = report_safe_name(path)
    try:
        before = path.lstat()
    except OSError as exc:
        raise ChessBaseIntegrityIOError(
            f"ChessBase source evidence is unavailable for {safe_name}"
        ) from exc
    if stat.S_ISLNK(before.st_mode) or _is_reparse_point(before):
        raise ChessBaseIntegrityIOError(
            "ChessBase source evidence must not follow filesystem indirection"
        )
    if not stat.S_ISREG(before.st_mode):
        raise ChessBaseIntegrityIOError(
            "ChessBase source evidence must be a regular file"
        )

    first_digest = sha256()
    second_digest = sha256()
    first_size = 0
    second_size = 0
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or _is_reparse_point(opened)
                or not _same_file_identity(before, opened)
            ):
                raise ChessBaseSourceChangedError(
                    "ChessBase source changed before integrity evidence could be collected"
                )

            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                first_size += len(chunk)
                first_digest.update(chunk)

            after_first = os.fstat(stream.fileno())
            if not _stable_file_metadata(opened, after_first):
                raise ChessBaseSourceChangedError(
                    "ChessBase source changed while integrity evidence was being collected"
                )

            stream.seek(0)
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                second_size += len(chunk)
                second_digest.update(chunk)

            after_second = os.fstat(stream.fileno())
            if not _stable_file_metadata(after_first, after_second):
                raise ChessBaseSourceChangedError(
                    "ChessBase source changed while integrity evidence was being collected"
                )
    except ChessBaseSourceChangedError:
        raise
    except OSError as exc:
        raise ChessBaseIntegrityIOError(
            f"ChessBase source evidence is unavailable for {safe_name}"
        ) from exc

    try:
        after = path.lstat()
    except OSError as exc:
        raise ChessBaseIntegrityIOError(
            f"ChessBase source evidence disappeared for {safe_name}"
        ) from exc
    if (
        not _stable_file_metadata(before, after)
        or not _same_file_identity(after_second, after)
        or stat.S_ISLNK(after.st_mode)
        or _is_reparse_point(after)
    ):
        raise ChessBaseSourceChangedError(
            "ChessBase source changed while integrity evidence was being collected"
        )
    if (
        first_size != second_size
        or first_size != after_second.st_size
        or first_digest.hexdigest() != second_digest.hexdigest()
    ):
        raise ChessBaseSourceChangedError(
            "ChessBase source content changed while integrity evidence was being collected"
        )

    return SourceFileEvidence(
        path=Path(os.path.abspath(os.fspath(path))),
        extension=extension,
        role=role,
        size_bytes=second_size,
        sha256=second_digest.hexdigest(),
    )


def _evidence_paths(
    probe: ChessBaseSourceProbe,
) -> Iterable[tuple[Path, str, str]]:
    yield (
        probe.path,
        probe.extension,
        "primary_source" if probe.is_primary_source else "component_source",
    )
    for component in probe.existing_components:
        yield component.path, component.extension, component.role


def _require_complete_legacy_cbf_pair(probe: ChessBaseSourceProbe) -> None:
    """Fail closed before any future CBF decoder sees an incomplete family."""
    if probe.extension != ".cbf":
        return
    cbi = tuple(
        component for component in probe.components if component.extension == ".cbi"
    )
    if len(cbi) != 1 or not cbi[0].exists:
        raise ChessBaseIntegrityIOError(
            "Legacy CBF source requires one same-stem .cbi index companion"
        )


def capture_integrity_snapshot(
    path: str | Path,
) -> ChessBaseIntegritySnapshot:
    probe = probe_chessbase_source(path)
    if not probe.recognized:
        raise ValueError(
            f"Unsupported ChessBase-family source: {report_safe_name(probe.path)}"
        )
    if probe.path.is_symlink():
        raise ChessBaseIntegrityIOError(
            "ChessBase primary source must not be a symlink"
        )
    if not probe.path.exists() or not probe.path.is_file():
        raise FileNotFoundError(probe.path)
    _require_complete_legacy_cbf_pair(probe)

    files = tuple(
        _fingerprint(file_path, extension, role)
        for file_path, extension, role in _evidence_paths(probe)
    )
    return ChessBaseIntegritySnapshot(
        primary_path=files[0].path,
        files=files,
    )


def verify_integrity_snapshot(
    snapshot: ChessBaseIntegritySnapshot,
) -> ChessBaseIntegritySnapshot:
    try:
        current = capture_integrity_snapshot(snapshot.primary_path)
    except ChessBaseSourceChangedError:
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        raise ChessBaseIntegrityIOError(
            "ChessBase integrity verification could not read source evidence"
        ) from exc
    if current != snapshot:
        raise ChessBaseSourceChangedError(
            "ChessBase source family changed after the integrity snapshot; "
            "discard decoder/import output and keep the original source authoritative."
        )
    return current
