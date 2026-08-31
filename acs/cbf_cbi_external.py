from __future__ import annotations

"""Bounded external CBF/CBI reader seam; not a support-promotion switch.

The legacy ChessBase decoder remains an optional out-of-process dependency.
Accessible Chess never interprets CBF binary records here. A complete immutable
``.cbf + .cbi`` family is converted by the pinned Scidb ``cbh2si4`` tool into a
private SI4 database, exported read-only by a pinned Scid ``tcscid`` runtime
executing the pinned ``scidpgn.tcl`` script, and only then admitted through the
canonical PGN/GameTree path.

This module is deliberately not registered as a user-facing importer while the
real-corpus/license/oracle acceptance gate is incomplete. Its purpose is to
remove the Product-side bounded-execution blocker without inventing support.
"""

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
import threading
import time
from typing import Callable

from .acsdb import AcsDatabase
from .chessbase_integrity import (
    ChessBaseIntegritySnapshot,
    capture_integrity_snapshot,
    verify_integrity_snapshot,
)
from .game_identity import identity_for_game
from .gametree import PgnGame, parse_games, serialize_games
from .library_import_service import (
    LibraryImportCancelledError,
    LibraryImportControlError,
    LibraryImportProgress,
    LibraryImportResult,
    LibraryImportService,
)
from .report_paths import report_safe_name

SCIDB_COMMIT = "7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415"
SCID_COMMIT = "5837653efa3975c64cff232006d9f981b36ac56b"
SCIDB_CBH2SI4_BLOB = "1830d059b987e3b9d4b97803d92f33936a69ace1"
SCID_SCIDPGN_BLOB = "84273490e8ee6b47bc78ca26a274ab559845e7b5"

MAX_PROCESS_STDOUT = 64 * 1024 * 1024
MAX_PROCESS_STDERR = 1 * 1024 * 1024
MAX_PRIVATE_SI4_BYTES = 512 * 1024 * 1024
MAX_CANONICAL_GAMES = 100_000
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CbfCbiExternalCode(str, Enum):
    UNSUPPORTED_SOURCE = "unsupported_source"
    BACKEND_INVALID = "backend_invalid"
    BACKEND_TIMEOUT = "backend_timeout"
    BACKEND_OUTPUT_LIMIT = "backend_output_limit"
    BACKEND_FAILED = "backend_failed"
    TEMP_OUTPUT_INVALID = "temp_output_invalid"
    RESOURCE_LIMIT = "resource_limit"
    PGN_INVALID = "pgn_invalid"
    ROUNDTRIP_MISMATCH = "roundtrip_mismatch"
    SOURCE_CHANGED = "source_changed"


class CbfCbiExternalError(RuntimeError):
    def __init__(self, message: str, *, code: CbfCbiExternalCode) -> None:
        super().__init__(message)
        self.code = CbfCbiExternalCode(code)


@dataclass(frozen=True, slots=True)
class ExternalCbfCbiReaderConfig:
    """Trust profile for separately installed GPL conversion components.

    SHA-256 pins are mandatory for the converter executable, the Scid Tcl
    interpreter executable, and the exact PGN-export script. No component is
    discovered through PATH and none is bundled by this module.
    """

    cbh2si4_executable: Path
    cbh2si4_sha256: str
    tcscid_executable: Path
    tcscid_sha256: str
    scidpgn_script: Path
    scidpgn_sha256: str
    timeout_seconds: float = 120.0
    max_stdout_bytes: int = MAX_PROCESS_STDOUT
    max_stderr_bytes: int = MAX_PROCESS_STDERR
    max_private_si4_bytes: int = MAX_PRIVATE_SI4_BYTES
    max_games: int = MAX_CANONICAL_GAMES

    def __post_init__(self) -> None:
        for field_name in (
            "cbh2si4_executable",
            "tcscid_executable",
            "scidpgn_script",
        ):
            object.__setattr__(self, field_name, Path(getattr(self, field_name)))
        for value, label in (
            (self.cbh2si4_sha256, "cbh2si4_sha256"),
            (self.tcscid_sha256, "tcscid_sha256"),
            (self.scidpgn_sha256, "scidpgn_sha256"),
        ):
            if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
                raise ValueError(f"{label} must be a lowercase SHA-256 digest")
        if (
            type(self.timeout_seconds) not in (int, float)
            or not 0 < float(self.timeout_seconds) <= 600
        ):
            raise ValueError("timeout_seconds must be within (0, 600]")
        for value, label, maximum in (
            (self.max_stdout_bytes, "max_stdout_bytes", 256 * 1024 * 1024),
            (self.max_stderr_bytes, "max_stderr_bytes", 64 * 1024 * 1024),
            (
                self.max_private_si4_bytes,
                "max_private_si4_bytes",
                8 * 1024 * 1024 * 1024,
            ),
        ):
            if type(value) is not int or value < 1024 or value > maximum:
                raise ValueError(f"{label} is outside the supported bound")
        if (
            type(self.max_games) is not int
            or not 1 <= self.max_games <= MAX_CANONICAL_GAMES
        ):
            raise ValueError("max_games is outside the supported bound")


@dataclass(frozen=True, slots=True)
class CbfCbiReadResult:
    source: ChessBaseIntegritySnapshot
    source_family_sha256: str
    cbh2si4_sha256: str
    tcscid_sha256: str
    scidpgn_sha256: str
    games: tuple[PgnGame, ...]
    canonical_roundtrip_verified: bool

    @property
    def total_games(self) -> int:
        return len(self.games)


class CbfCbiLibraryImportStatus(str, Enum):
    IMPORTED = "imported"
    NO_GAMES = "no_games"


@dataclass(frozen=True, slots=True)
class CbfCbiLibraryImportReport:
    status: CbfCbiLibraryImportStatus
    source_name: str
    source_sha256: str
    decoded_game_count: int
    library_result: LibraryImportResult | None
    cbh2si4_sha256: str
    tcscid_sha256: str
    scidpgn_sha256: str

    @property
    def imported_game_count(self) -> int:
        return 0 if self.library_result is None else self.library_result.game_count


@dataclass(slots=True)
class _CapturedStream:
    data: bytearray
    overflow: threading.Event


def _error(message: str, code: CbfCbiExternalCode) -> CbfCbiExternalError:
    return CbfCbiExternalError(message, code=code)


def _is_reparse_point(st: os.stat_result) -> bool:
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(st, "st_file_attributes", 0) & marker)


def _sha256_regular_file(path: Path, expected: str) -> tuple[Path, str]:
    try:
        before = path.lstat()
    except OSError as exc:
        raise _error(
            "CBF/CBI external backend component is unavailable",
            CbfCbiExternalCode.BACKEND_INVALID,
        ) from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or _is_reparse_point(before)
        or not stat.S_ISREG(before.st_mode)
    ):
        raise _error(
            "CBF/CBI external backend component must be a regular non-indirected file",
            CbfCbiExternalCode.BACKEND_INVALID,
        )
    digest = sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.lstat()
    except OSError as exc:
        raise _error(
            "CBF/CBI external backend component could not be verified",
            CbfCbiExternalCode.BACKEND_INVALID,
        ) from exc
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or stat.S_ISLNK(after.st_mode)
        or _is_reparse_point(after)
    ):
        raise _error(
            "CBF/CBI external backend component changed during verification",
            CbfCbiExternalCode.BACKEND_INVALID,
        )
    actual = digest.hexdigest()
    if actual != expected:
        raise _error(
            "CBF/CBI external backend component identity does not match the configured pin",
            CbfCbiExternalCode.BACKEND_INVALID,
        )
    return Path(os.path.abspath(os.fspath(path))), actual


def _sterile_environment(*components: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in ("SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    search: list[str] = []
    for component in components:
        parent = os.fspath(component.parent)
        if parent not in search:
            search.append(parent)
    env["PATH"] = os.pathsep.join(search)
    env["LC_ALL"] = "C.UTF-8"
    env["LANG"] = "C.UTF-8"
    return env


def _read_capped(stream, limit: int, captured: _CapturedStream) -> None:
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            remaining = limit + 1 - len(captured.data)
            if remaining > 0:
                captured.data.extend(chunk[:remaining])
            if len(captured.data) > limit:
                captured.overflow.set()
                return
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _kill_process(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (OSError, ProcessLookupError):
        try:
            process.kill()
        except OSError:
            pass


def _run_process(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
) -> bytes:
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen(
            argv,
            cwd=os.fspath(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=creationflags,
            start_new_session=(os.name != "nt"),
        )
    except OSError as exc:
        raise _error(
            "CBF/CBI external backend could not be started",
            CbfCbiExternalCode.BACKEND_INVALID,
        ) from exc

    assert process.stdout is not None and process.stderr is not None
    stdout = _CapturedStream(bytearray(), threading.Event())
    stderr = _CapturedStream(bytearray(), threading.Event())
    readers = (
        threading.Thread(
            target=_read_capped,
            args=(process.stdout, max_stdout_bytes, stdout),
            daemon=True,
        ),
        threading.Thread(
            target=_read_capped,
            args=(process.stderr, max_stderr_bytes, stderr),
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()

    deadline = time.monotonic() + float(timeout_seconds)
    timed_out = False
    overflow = False
    while process.poll() is None:
        if stdout.overflow.is_set() or stderr.overflow.is_set():
            overflow = True
            _kill_process(process)
            break
        if time.monotonic() >= deadline:
            timed_out = True
            _kill_process(process)
            break
        time.sleep(0.01)

    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        _kill_process(process)
        process.wait(timeout=2.0)
    for reader in readers:
        reader.join(timeout=2.0)

    if timed_out:
        raise _error(
            "CBF/CBI external backend exceeded its time limit",
            CbfCbiExternalCode.BACKEND_TIMEOUT,
        )
    if overflow or stdout.overflow.is_set() or stderr.overflow.is_set():
        raise _error(
            "CBF/CBI external backend exceeded its output limit",
            CbfCbiExternalCode.BACKEND_OUTPUT_LIMIT,
        )
    if process.returncode != 0:
        raise _error(
            "CBF/CBI external backend failed",
            CbfCbiExternalCode.BACKEND_FAILED,
        )
    return bytes(stdout.data)


def _family_sha256(snapshot: ChessBaseIntegritySnapshot) -> str:
    digest = sha256(b"Accessible-Chess-CBF-family-v1\0")
    for item in sorted(
        snapshot.files,
        key=lambda value: (value.extension, value.role, value.sha256),
    ):
        digest.update(item.extension.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.role.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item.size_bytes).encode("ascii"))
        digest.update(b"\0")
        digest.update(item.sha256.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_si4_family(directory: Path, base: str, max_bytes: int) -> None:
    expected = {f"{base}.si4", f"{base}.sg4", f"{base}.sn4"}
    try:
        entries = tuple(directory.iterdir())
    except OSError as exc:
        raise _error(
            "Private SI4 output could not be inspected",
            CbfCbiExternalCode.TEMP_OUTPUT_INVALID,
        ) from exc
    names = {entry.name for entry in entries}
    if names != expected:
        raise _error(
            "External CBF conversion produced an unexpected private output topology",
            CbfCbiExternalCode.TEMP_OUTPUT_INVALID,
        )
    total = 0
    for entry in entries:
        try:
            st = entry.lstat()
        except OSError as exc:
            raise _error(
                "Private SI4 output could not be inspected",
                CbfCbiExternalCode.TEMP_OUTPUT_INVALID,
            ) from exc
        if (
            stat.S_ISLNK(st.st_mode)
            or _is_reparse_point(st)
            or not stat.S_ISREG(st.st_mode)
        ):
            raise _error(
                "Private SI4 output must contain regular non-indirected files only",
                CbfCbiExternalCode.TEMP_OUTPUT_INVALID,
            )
        total += st.st_size
        if total > max_bytes:
            raise _error(
                "Private SI4 output exceeds the configured resource limit",
                CbfCbiExternalCode.RESOURCE_LIMIT,
            )


def _canonical_games_from_pgn(payload: bytes, max_games: int) -> tuple[PgnGame, ...]:
    try:
        text = payload.decode("utf-8", errors="strict")
        games = tuple(parse_games(text))
    except Exception as exc:
        raise _error(
            "External CBF conversion did not produce valid canonical PGN",
            CbfCbiExternalCode.PGN_INVALID,
        ) from exc
    if len(games) > max_games:
        raise _error(
            "External CBF conversion exceeds the configured game limit",
            CbfCbiExternalCode.RESOURCE_LIMIT,
        )
    try:
        identities = tuple(identity_for_game(game).record_digest for game in games)
        reopened = tuple(parse_games(serialize_games(games)))
        reopened_identities = tuple(
            identity_for_game(game).record_digest for game in reopened
        )
    except Exception as exc:
        raise _error(
            "Canonical CBF PGN export/reopen validation failed",
            CbfCbiExternalCode.PGN_INVALID,
        ) from exc
    if identities != reopened_identities:
        raise _error(
            "Canonical CBF PGN export/reopen changed semantic game identity",
            CbfCbiExternalCode.ROUNDTRIP_MISMATCH,
        )
    return games


def read_cbf_cbi_external(
    path: str | Path,
    config: ExternalCbfCbiReaderConfig,
) -> CbfCbiReadResult:
    """Read one complete legacy CBF/CBI family through pinned external tools.

    The source is fingerprinted before backend execution and re-fingerprinted
    after PGN export. Any mutation discards all output. Temporary SI4 files live
    only in a private temporary directory and are removed on every exit.
    """

    if not isinstance(config, ExternalCbfCbiReaderConfig):
        raise TypeError("config must be an ExternalCbfCbiReaderConfig")
    source = Path(path)
    if source.suffix.lower() != ".cbf":
        raise _error(
            "CBF/CBI external reader requires the .cbf primary source",
            CbfCbiExternalCode.UNSUPPORTED_SOURCE,
        )

    try:
        snapshot = capture_integrity_snapshot(source)
    except Exception as exc:
        raise _error(
            "CBF/CBI source family is incomplete or unavailable",
            CbfCbiExternalCode.UNSUPPORTED_SOURCE,
        ) from exc

    cbh2si4, cbh2si4_hash = _sha256_regular_file(
        config.cbh2si4_executable,
        config.cbh2si4_sha256,
    )
    tcscid, tcscid_hash = _sha256_regular_file(
        config.tcscid_executable,
        config.tcscid_sha256,
    )
    scidpgn, scidpgn_hash = _sha256_regular_file(
        config.scidpgn_script,
        config.scidpgn_sha256,
    )
    env = _sterile_environment(cbh2si4, tcscid, scidpgn)

    with tempfile.TemporaryDirectory(prefix="accessible-chess-cbf-") as raw_temp:
        private = Path(raw_temp)
        destination = private / "decoded.si4"
        _run_process(
            [
                os.fspath(cbh2si4),
                "--all-tags",
                "--unusual-tags",
                os.fspath(snapshot.primary_path),
                os.fspath(destination),
            ],
            cwd=private,
            env=env,
            timeout_seconds=config.timeout_seconds,
            max_stdout_bytes=min(config.max_stdout_bytes, 4 * 1024 * 1024),
            max_stderr_bytes=config.max_stderr_bytes,
        )
        _validate_si4_family(private, "decoded", config.max_private_si4_bytes)
        pgn = _run_process(
            [os.fspath(tcscid), os.fspath(scidpgn), os.fspath(destination)],
            cwd=private,
            env=env,
            timeout_seconds=config.timeout_seconds,
            max_stdout_bytes=config.max_stdout_bytes,
            max_stderr_bytes=config.max_stderr_bytes,
        )
        games = _canonical_games_from_pgn(pgn, config.max_games)
        try:
            verify_integrity_snapshot(snapshot)
        except Exception as exc:
            raise _error(
                "CBF/CBI source family changed during external decoding",
                CbfCbiExternalCode.SOURCE_CHANGED,
            ) from exc

    return CbfCbiReadResult(
        source=snapshot,
        source_family_sha256=_family_sha256(snapshot),
        cbh2si4_sha256=cbh2si4_hash,
        tcscid_sha256=tcscid_hash,
        scidpgn_sha256=scidpgn_hash,
        games=games,
        canonical_roundtrip_verified=True,
    )


CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[LibraryImportProgress], None]


def _poll_cancel(cancel_check: CancelCheck | None) -> None:
    if cancel_check is None:
        return
    if not callable(cancel_check):
        raise TypeError("cancel_check must be callable")
    try:
        cancelled = cancel_check()
    except LibraryImportCancelledError:
        raise
    except Exception as exc:
        raise LibraryImportControlError(
            "CBF/CBI import cancellation check failed"
        ) from exc
    if type(cancelled) is not bool:
        raise LibraryImportControlError("cancel_check must return a boolean")
    if cancelled:
        raise LibraryImportCancelledError("CBF/CBI import cancelled")


class CbfCbiLibraryImportService:
    """Unregistered qualification seam for atomic ACSDB publication."""

    def __init__(self, database: AcsDatabase, config: ExternalCbfCbiReaderConfig) -> None:
        if not isinstance(database, AcsDatabase):
            raise TypeError("database must be an AcsDatabase")
        if not isinstance(config, ExternalCbfCbiReaderConfig):
            raise TypeError("config must be an ExternalCbfCbiReaderConfig")
        self._library = LibraryImportService(database)
        self._config = config

    def import_database(
        self,
        path: str | Path,
        *,
        cancel_check: CancelCheck | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> CbfCbiLibraryImportReport:
        _poll_cancel(cancel_check)
        decoded = read_cbf_cbi_external(path, self._config)
        _poll_cancel(cancel_check)
        if not decoded.games:
            return CbfCbiLibraryImportReport(
                status=CbfCbiLibraryImportStatus.NO_GAMES,
                source_name=report_safe_name(decoded.source.primary_path),
                source_sha256=decoded.source_family_sha256,
                decoded_game_count=0,
                library_result=None,
                cbh2si4_sha256=decoded.cbh2si4_sha256,
                tcscid_sha256=decoded.tcscid_sha256,
                scidpgn_sha256=decoded.scidpgn_sha256,
            )
        imported = self._library.import_games(
            decoded.games,
            source_name=report_safe_name(decoded.source.primary_path),
            source_format="cbf",
            source_sha256=decoded.source_family_sha256,
            source_warning_count=0,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
        return CbfCbiLibraryImportReport(
            status=CbfCbiLibraryImportStatus.IMPORTED,
            source_name=report_safe_name(decoded.source.primary_path),
            source_sha256=decoded.source_family_sha256,
            decoded_game_count=len(decoded.games),
            library_result=imported,
            cbh2si4_sha256=decoded.cbh2si4_sha256,
            tcscid_sha256=decoded.tcscid_sha256,
            scidpgn_sha256=decoded.scidpgn_sha256,
        )
