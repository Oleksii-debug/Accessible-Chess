from __future__ import annotations

"""Safe file-level PGN services for Accessible Chess.

This module is deliberately presentation-neutral. It connects the structural
GameTree parser/serializer to real files without teaching the UI about file
encoding, provenance fingerprints, concurrent modification checks, or atomic
replacement.

The source PGN is read-only during inspection/open. Saving always writes a
complete temporary file in the destination directory and then publishes that
complete file through a commit primitive appropriate to the requested safety
contract.
"""

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import stat
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


MAX_PGN_SOURCE_BYTES = 64 * 1024 * 1024
_LOG = logging.getLogger(__name__)


class PgnFileError(RuntimeError):
    """Base error for safe PGN file operations."""


class PgnSourceChangedError(PgnFileError):
    """Raised when a file changes while it is being read."""


class PgnResourceLimitError(PgnFileError):
    """Raised when an external PGN exceeds the bounded import contract."""


class PgnConcurrentWriteError(PgnFileError):
    """Raised when optimistic overwrite protection detects a newer source."""


class PgnUnsafePathError(PgnFileError):
    """Raised when export would traverse filesystem indirection."""


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

        lossy_source = bool(opened.global_warnings)
        for game in opened.games:
            warnings = list(game.warnings)
            if lossy_source:
                warnings.append("Source text required lossy UTF-8 replacement during decoding.")
            report.add(
                ImportedRecord(
                    source_record_id=str(game.source_index),
                    quality=ImportQuality.WARNING if warnings else ImportQuality.FULL,
                    message="PGN game parsed structurally.",
                    warnings=tuple(warnings),
                )
            )
        return report


def _is_reparse_point(st: os.stat_result) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & marker)


def _reject_export_indirection(path: Path) -> None:
    """Fail closed if any existing submitted path component is indirect."""

    absolute = path.absolute()
    parts = absolute.parts
    if not parts:
        raise PgnUnsafePathError("PGN export destination is invalid")

    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise PgnUnsafePathError("PGN export path could not be validated safely") from exc
        if stat.S_ISLNK(current_stat.st_mode) or _is_reparse_point(current_stat):
            raise PgnUnsafePathError("PGN export path must not traverse filesystem indirection")


def _bounded_source_size(path: Path) -> int | None:
    try:
        size = path.lstat().st_size
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PgnFileError("PGN source is unavailable") from exc
    if size > MAX_PGN_SOURCE_BYTES:
        raise PgnResourceLimitError(
            f"PGN source exceeds the {MAX_PGN_SOURCE_BYTES}-byte safety limit"
        )
    return size


def _read_text_snapshot(path: Path) -> tuple[SourceFingerprint, str]:
    _bounded_source_size(path)
    before = fingerprint(path)
    if before.size > MAX_PGN_SOURCE_BYTES:
        raise PgnResourceLimitError(
            f"PGN source exceeds the {MAX_PGN_SOURCE_BYTES}-byte safety limit"
        )
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline=None) as handle:
            text = handle.read(MAX_PGN_SOURCE_BYTES + 1)
    except OSError as exc:
        raise PgnFileError("PGN source could not be read safely") from exc
    if len(text.encode("utf-8", errors="replace")) > MAX_PGN_SOURCE_BYTES:
        raise PgnResourceLimitError("PGN decoded text exceeds the safety limit")
    after = fingerprint(path)
    if before.size != after.size or before.sha256 != after.sha256:
        raise PgnSourceChangedError("PGN changed while being read")
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
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    return fingerprint(path).sha256


def _create_hardlink_snapshot(destination: Path) -> Path:
    """Create a same-directory hard-link snapshot of an existing destination.

    The link keeps the pre-publication inode reachable after ``os.replace``. If
    an in-place competing writer mutates that inode in the final publication
    window, its bytes remain recoverable and the stale save can roll back rather
    than silently destroying the newer edit.
    """

    for _ in range(8):
        fd, raw_name = tempfile.mkstemp(
            dir=str(destination.parent),
            prefix=destination.name + ".cas-",
            suffix=".bak",
        )
        os.close(fd)
        snapshot = Path(raw_name)
        snapshot.unlink()
        try:
            os.link(destination, snapshot)
            return snapshot
        except FileExistsError:
            continue
        except OSError as exc:
            raise PgnFileError("PGN commit snapshot could not be created safely") from exc
    raise PgnFileError("PGN commit snapshot could not reserve a unique path")


def _publish_no_clobber(tmp_path: Path, destination: Path) -> None:
    """Atomically publish ``tmp_path`` only if ``destination`` is still absent."""

    try:
        os.link(tmp_path, destination)
    except FileExistsError:
        raise
    except OSError as exc:
        raise PgnFileError("PGN no-clobber publication is unavailable") from exc

    # Publication is committed once the hard link exists. Cleanup of the
    # redundant temporary pathname is best-effort and must not turn a committed
    # save into a reported failure that invites an unsafe retry.
    try:
        tmp_path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        _LOG.warning("PGN was committed but redundant temporary cleanup could not complete")


def _publish_expected_hash(
    tmp_path: Path,
    destination: Path,
    expected_sha256: str,
) -> None:
    """Publish with recoverable optimistic-CAS semantics for an existing file."""

    if _current_sha256(destination) != expected_sha256:
        raise PgnConcurrentWriteError(f"PGN changed since it was opened: {destination}")

    snapshot = _create_hardlink_snapshot(destination)
    preserve_snapshot = False
    try:
        if _current_sha256(destination) != expected_sha256:
            raise PgnConcurrentWriteError(f"PGN changed since it was opened: {destination}")
        if _current_sha256(snapshot) != expected_sha256:
            raise PgnConcurrentWriteError(f"PGN changed since it was opened: {destination}")

        os.replace(tmp_path, destination)

        # ``snapshot`` references the pre-publication inode. A competing writer
        # that modified that inode immediately before our replace changes this
        # digest too. Restore those newer bytes before reporting the conflict.
        try:
            snapshot_sha256 = _current_sha256(snapshot)
        except (OSError, ValueError, PgnFileError) as exc:
            preserve_snapshot = True
            raise PgnFileError(
                "PGN publication could not be verified safely; recovery snapshot was preserved"
            ) from exc

        if snapshot_sha256 != expected_sha256:
            try:
                os.replace(snapshot, destination)
            except OSError as exc:
                preserve_snapshot = True
                raise PgnFileError(
                    "PGN concurrent-write rollback failed; recovery snapshot was preserved"
                ) from exc
            snapshot = None
            raise PgnConcurrentWriteError(f"PGN changed during publication: {destination}")
    finally:
        if snapshot is not None and not preserve_snapshot:
            try:
                snapshot.unlink()
            except FileNotFoundError:
                pass


def save_pgn_atomic(
    path: str | Path,
    games: Iterable[PgnGame],
    *,
    overwrite: bool = False,
    expected_sha256: str | None = None,
) -> SourceFingerprint:
    """Serialize GameTree content and commit one complete PGN file safely.

    ``overwrite=False`` uses an atomic no-clobber hard-link publication in the
    destination directory. ``expected_sha256`` uses a recoverable pre-commit
    inode snapshot so an in-place writer racing at publication is detected and
    restored instead of silently lost. Plain ``overwrite=True`` without an
    expected digest intentionally requests unconditional replacement.
    """

    destination = Path(path)
    _reject_export_indirection(destination)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"PGN already exists: {destination}")

    current_sha = _current_sha256(destination)
    if expected_sha256 is not None and current_sha != expected_sha256:
        raise PgnConcurrentWriteError(f"PGN changed since it was opened: {destination}")

    payload = serialize_games(tuple(games))
    destination.parent.mkdir(parents=True, exist_ok=True)
    _reject_export_indirection(destination)

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

        _reject_export_indirection(destination)
        if not overwrite:
            _publish_no_clobber(tmp_path, destination)
            tmp_path = None
        elif expected_sha256 is not None:
            _publish_expected_hash(tmp_path, destination, expected_sha256)
            tmp_path = None
        else:
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
