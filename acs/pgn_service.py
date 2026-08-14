from __future__ import annotations

"""Safe file-level PGN services for Accessible Chess.

This module is deliberately presentation-neutral.  It connects the structural
GameTree parser/serializer to real files without teaching the UI about file
encoding, provenance fingerprints, concurrent modification checks, or atomic
replacement.

The source PGN is read-only during inspection/open.  Saving always writes a
complete temporary file in the destination directory and then atomically
replaces the destination, so a crash cannot leave a half-written PGN.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Iterable

from .gametree import PgnGame, parse_games, serialize_games
from .import_contract import (
    ImportQuality,
    ImportReport,
    ImportedRecord,
    SourceFingerprint,
    fingerprint,
)


class PgnFileError(RuntimeError):
    """Base error for safe PGN file operations."""


class PgnSourceChangedError(PgnFileError):
    """Raised when a file changes while it is being read."""


class PgnConcurrentWriteError(PgnFileError):
    """Raised when optimistic overwrite protection detects a newer source."""


@dataclass(frozen=True)
class PgnOpenResult:
    source: SourceFingerprint
    games: tuple[PgnGame, ...]
    global_warnings: tuple[str, ...] = ()

    @property
    def total_games(self) -> int:
        return len(self.games)

    @property
    def warning_games(self) -> int:
        return sum(1 for game in self.games if game.warnings)


class PgnFileImporter:
    """Read-only PGN importer adapter for ImportRegistry preflight/reporting."""

    format_name = "PGN"
    suffixes = (".pgn",)

    def inspect(self, path: Path) -> ImportReport:
        opened = open_pgn(path)
        report = ImportReport(source=opened.source, format_name=self.format_name)
        report.global_warnings.extend(opened.global_warnings)
        if not opened.games:
            report.add(
                ImportedRecord(
                    source_record_id="source",
                    quality=ImportQuality.DAMAGED,
                    message="PGN contains no parseable games.",
                )
            )
            return report

        for game in opened.games:
            warnings = tuple(game.warnings)
            report.add(
                ImportedRecord(
                    source_record_id=str(game.source_index),
                    quality=ImportQuality.WARNING if warnings else ImportQuality.FULL,
                    message="PGN game parsed structurally.",
                    warnings=warnings,
                )
            )
        return report


def _read_text_snapshot(path: Path) -> tuple[SourceFingerprint, str]:
    before = fingerprint(path)
    with path.open("r", encoding="utf-8-sig", errors="replace", newline=None) as handle:
        text = handle.read()
    after = fingerprint(path)
    if before.size != after.size or before.sha256 != after.sha256:
        raise PgnSourceChangedError(f"PGN changed while being read: {path}")
    return before, text


def open_pgn(path: str | Path) -> PgnOpenResult:
    """Open a PGN without mutating it and preserve recursive GameTree content."""

    source_path = Path(path)
    source, text = _read_text_snapshot(source_path)
    games = tuple(parse_games(text))
    warnings: list[str] = []
    if "\ufffd" in text:
        warnings.append(
            "Invalid UTF-8 bytes were replaced while reading; save to a new file before editing the source."
        )
    return PgnOpenResult(source=source, games=games, global_warnings=tuple(warnings))


def _current_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return fingerprint(path).sha256


def save_pgn_atomic(
    path: str | Path,
    games: Iterable[PgnGame],
    *,
    overwrite: bool = False,
    expected_sha256: str | None = None,
) -> SourceFingerprint:
    """Serialize GameTree content and atomically commit one complete PGN file.

    ``overwrite=False`` protects existing files by default.  When overwriting a
    file that was previously opened, callers may pass ``expected_sha256`` from
    :class:`PgnOpenResult`; a mismatch refuses the write instead of silently
    replacing someone else's newer edits.
    """

    destination = Path(path)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"PGN already exists: {destination}")

    current_sha = _current_sha256(destination)
    if expected_sha256 is not None and current_sha != expected_sha256:
        raise PgnConcurrentWriteError(f"PGN changed since it was opened: {destination}")

    payload = serialize_games(tuple(games))
    destination.parent.mkdir(parents=True, exist_ok=True)

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=str(destination.parent),
            prefix=destination.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, destination)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass

    return fingerprint(destination)


def export_game_atomic(
    path: str | Path,
    game: PgnGame,
    *,
    overwrite: bool = False,
    expected_sha256: str | None = None,
) -> SourceFingerprint:
    """Convenience wrapper for exporting one game with the same safety rules."""

    return save_pgn_atomic(path, (game,), overwrite=overwrite, expected_sha256=expected_sha256)
