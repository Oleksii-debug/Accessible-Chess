from __future__ import annotations

"""Safe file-level PGN services for Accessible Chess.

This module is deliberately presentation-neutral. It connects the structural
GameTree parser/serializer to real files without teaching the UI about file
encoding, provenance fingerprints, concurrent modification checks, or atomic
replacement.

The source PGN is read-only during inspection/open. Saving always writes a
complete temporary file in the destination directory and then atomically
replaces the destination, so a crash cannot leave a half-written PGN.

Expected-SHA overwrite protection uses a destination-local sidecar lock to
serialize cooperating Accessible Chess writers from the version check through
commit. A second hash check immediately before replacement also detects a
non-cooperating writer that changes the destination while the temporary file is
being prepared. Filesystems do not expose a portable compare-and-swap replace,
so software that bypasses this lock protocol is not claimed to participate in
the cooperative transaction.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Iterable, Iterator

from .gametree import PgnGame, parse_games, serialize_games
from .gametree_legality import link_game_legality
from .import_contract import (
    ImportQuality,
    ImportReport,
    ImportedRecord,
    SourceFingerprint,
)


MAX_PGN_FILE_BYTES = 64 * 1024 * 1024
MAX_PGN_EXPORT_BYTES = 64 * 1024 * 1024
PGN_READ_CHUNK_BYTES = 1024 * 1024
PGN_TEXT_CHUNK_CHARACTERS = 256 * 1024


class PgnFileError(RuntimeError):
    """Base error for safe PGN file operations."""


class PgnSourceChangedError(PgnFileError):
    """Raised when a file changes while it is being read."""


class PgnConcurrentWriteError(PgnFileError):
    """Raised when overwrite protection detects concurrent/newer content."""


class PgnFileErrorCode(str, Enum):
    SOURCE_BYTE_LIMIT = "source_byte_limit"
    OUTPUT_BYTE_LIMIT = "output_byte_limit"


class PgnResourceLimitError(PgnFileError):
    """Stable failure raised before oversized PGN I/O can allocate unboundedly."""

    def __init__(self, message: str, *, code: PgnFileErrorCode) -> None:
        super().__init__(message)
        self.code = PgnFileErrorCode(code)


def _bounded_utf8_size(text: str, *, limit: int) -> int:
    total = 0
    for start in range(0, len(text), PGN_TEXT_CHUNK_CHARACTERS):
        total += len(
            text[start : start + PGN_TEXT_CHUNK_CHARACTERS].encode("utf-8")
        )
        if total > limit:
            return total
    return total


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
            legality = link_game_legality(game)
            legality_warnings = tuple(
                diagnostic.summary for diagnostic in legality.diagnostics
            )
            warnings = tuple(game.warnings) + legality_warnings
            structural_damage = any(
                issue.blocks_export for issue in game.recovery_issues
            )
            legality_damage = legality.has_errors or not legality.all_moves_legal
            damaged = structural_damage or legality_damage
            report.add(
                ImportedRecord(
                    source_record_id=str(game.source_index),
                    quality=(
                        ImportQuality.DAMAGED
                        if damaged
                        else ImportQuality.WARNING if warnings else ImportQuality.FULL
                    ),
                    message=(
                        "PGN game requires explicit repair of structural damage before export."
                        if structural_damage
                        else "PGN game has unresolved chess-legality diagnostics."
                        if legality_damage
                        else "PGN game is legal with preserved warnings."
                        if warnings
                        else "PGN game parsed and linked legally."
                    ),
                    warnings=warnings,
                )
            )
        return report


def _bounded_binary_snapshot(
    path: Path,
    *,
    capture_payload: bool,
) -> tuple[SourceFingerprint, bytearray | None]:
    initial_size = path.stat().st_size
    if initial_size > MAX_PGN_FILE_BYTES:
        raise PgnResourceLimitError(
            f"PGN exceeds the source byte safety limit: {path}",
            code=PgnFileErrorCode.SOURCE_BYTE_LIMIT,
        )

    digest = hashlib.sha256()
    payload = bytearray() if capture_payload else None
    total = 0
    with path.open("rb") as handle:
        while True:
            remaining = MAX_PGN_FILE_BYTES - total
            chunk = handle.read(min(PGN_READ_CHUNK_BYTES, remaining + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_PGN_FILE_BYTES:
                raise PgnResourceLimitError(
                    f"PGN exceeds the source byte safety limit: {path}",
                    code=PgnFileErrorCode.SOURCE_BYTE_LIMIT,
                )
            digest.update(chunk)
            if payload is not None:
                payload.extend(chunk)

    final_size = path.stat().st_size
    if initial_size != total or final_size != total:
        raise PgnSourceChangedError(f"PGN changed while being read: {path}")
    return (
        SourceFingerprint(
            path=str(path.resolve()),
            size=total,
            sha256=digest.hexdigest(),
            suffix=path.suffix.lower(),
        ),
        payload,
    )


def _read_text_snapshot(path: Path) -> tuple[SourceFingerprint, str]:
    before, payload = _bounded_binary_snapshot(path, capture_payload=True)
    after, _ = _bounded_binary_snapshot(path, capture_payload=False)
    if (
        before.path != after.path
        or before.size != after.size
        or before.sha256 != after.sha256
        or before.suffix != after.suffix
    ):
        raise PgnSourceChangedError(f"PGN changed while being read: {path}")
    assert payload is not None
    return before, payload.decode("utf-8-sig", errors="replace")


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
    source, _ = _bounded_binary_snapshot(path, capture_payload=False)
    return source.sha256


def _save_lock_path(destination: Path) -> Path:
    return destination.with_name(f".{destination.name}.acs-save.lock")


@contextmanager
def _exclusive_save_lock(destination: Path) -> Iterator[None]:
    """Serialize cooperating save transactions for one destination.

    Lock acquisition is non-blocking and fail-closed. A retained lock file after
    an unclean process exit is intentionally not guessed stale; an operator can
    inspect/remove it after confirming no writer is active.
    """

    lock_path = _save_lock_path(destination)
    try:
        fd = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError as exc:
        raise PgnConcurrentWriteError(
            f"PGN save transaction is already active: {destination}"
        ) from exc

    try:
        payload = f"pid={os.getpid()}\n".encode("ascii", errors="strict")
        os.write(fd, payload)
        os.fsync(fd)
        yield
    finally:
        os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _verify_expected_version(destination: Path, expected_sha256: str | None) -> None:
    if expected_sha256 is None:
        return
    if _current_sha256(destination) != expected_sha256:
        raise PgnConcurrentWriteError(f"PGN changed since it was opened: {destination}")


def save_pgn_atomic(
    path: str | Path,
    games: Iterable[PgnGame],
    *,
    overwrite: bool = False,
    expected_sha256: str | None = None,
) -> SourceFingerprint:
    """Serialize GameTree content and atomically commit one complete PGN file.

    ``overwrite=False`` protects existing files by default. When overwriting a
    file that was previously opened, callers may pass ``expected_sha256`` from
    :class:`PgnOpenResult`. Accessible Chess writers serialize on a destination-
    local sidecar lock from version preflight through commit. The destination is
    hashed again after the temporary file is fsynced and immediately before
    replacement, so a concurrent non-cooperating edit observed during that
    preparation window fails closed instead of being silently overwritten.
    """

    destination = Path(path)
    payload = serialize_games(games)
    payload_size = _bounded_utf8_size(payload, limit=MAX_PGN_EXPORT_BYTES)
    if payload_size > MAX_PGN_EXPORT_BYTES:
        raise PgnResourceLimitError(
            f"PGN exceeds the output byte safety limit: {destination}",
            code=PgnFileErrorCode.OUTPUT_BYTE_LIMIT,
        )
    destination.parent.mkdir(parents=True, exist_ok=True)

    with _exclusive_save_lock(destination):
        if destination.exists() and not overwrite:
            raise FileExistsError(f"PGN already exists: {destination}")
        _verify_expected_version(destination, expected_sha256)

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=str(destination.parent),
                prefix=destination.name + ".",
                suffix=".tmp",
                delete=False,
            ) as handle:
                tmp_path = Path(handle.name)
                for start in range(0, len(payload), PGN_TEXT_CHUNK_CHARACTERS):
                    handle.write(
                        payload[start : start + PGN_TEXT_CHUNK_CHARACTERS].encode(
                            "utf-8"
                        )
                    )
                handle.flush()
                os.fsync(handle.fileno())

            # Recheck after the potentially long serialize/write/fsync phase.
            # This is the deterministic lost-update barrier for expected-SHA
            # callers; another library writer cannot enter because of the lock.
            _verify_expected_version(destination, expected_sha256)
            if destination.exists() and not overwrite:
                raise FileExistsError(f"PGN already exists: {destination}")

            os.replace(tmp_path, destination)
            tmp_path = None
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink()
                except FileNotFoundError:
                    pass

    saved, _ = _bounded_binary_snapshot(destination, capture_payload=False)
    return saved


def export_game_atomic(
    path: str | Path,
    game: PgnGame,
    *,
    overwrite: bool = False,
    expected_sha256: str | None = None,
) -> SourceFingerprint:
    """Convenience wrapper for exporting one game with the same safety rules."""

    return save_pgn_atomic(path, (game,), overwrite=overwrite, expected_sha256=expected_sha256)
