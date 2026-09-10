from __future__ import annotations

"""Evidence-gated extraction of ChessBase ``.cbv`` archives.

CBV is an archive/container rather than a game database decoder.  Accessible
Chess keeps the GPL extractor as an optional external executable, validates
the complete archive entry list before extraction, writes only into a fresh
temporary directory, and then hands the extracted classic ``.cbh`` family to
the existing semantic decoder.
"""

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import subprocess
import threading
import time

from .import_contract import SourceFingerprint, fingerprint, verify_source_unchanged


MAX_ARCHIVE_ENTRIES = 4096
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024
MAX_EXTRACTED_BYTES = 16 * 1024 * 1024 * 1024
MAX_LIST_STDOUT = 4 * 1024 * 1024
MAX_BACKEND_STDERR = 1 * 1024 * 1024
MAX_ENTRY_NAME_CHARS = 1024


class CbvExtractCode(str, Enum):
    UNSUPPORTED_SOURCE = "unsupported_source"
    SOURCE_INVALID = "source_invalid"
    SOURCE_CHANGED = "source_changed"
    BACKEND_INVALID = "backend_invalid"
    BACKEND_TIMEOUT = "backend_timeout"
    BACKEND_OUTPUT_LIMIT = "backend_output_limit"
    BACKEND_FAILED = "backend_failed"
    INVALID_ENTRY = "invalid_entry"
    RESOURCE_LIMIT = "resource_limit"
    OUTPUT_INVALID = "output_invalid"


class CbvExtractError(RuntimeError):
    def __init__(self, message: str, *, code: CbvExtractCode) -> None:
        super().__init__(message)
        self.code = CbvExtractCode(code)


@dataclass(frozen=True, slots=True)
class ExternalCbvExtractorConfig:
    executable: Path
    expected_backend_sha256: str
    timeout_seconds: float = 120.0
    max_stdout_bytes: int = MAX_LIST_STDOUT
    max_stderr_bytes: int = MAX_BACKEND_STDERR
    max_entries: int = MAX_ARCHIVE_ENTRIES
    max_source_bytes: int = MAX_ARCHIVE_BYTES
    max_extracted_bytes: int = MAX_EXTRACTED_BYTES

    def __post_init__(self) -> None:
        object.__setattr__(self, "executable", Path(self.executable))
        digest = self.expected_backend_sha256
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("expected_backend_sha256 must be a lowercase SHA-256")
        if type(self.timeout_seconds) not in (int, float) or not 0 < float(self.timeout_seconds) <= 600:
            raise ValueError("timeout_seconds must be within (0, 600]")
        for value, label, minimum, maximum in (
            (self.max_stdout_bytes, "max_stdout_bytes", 1024, 64 * 1024 * 1024),
            (self.max_stderr_bytes, "max_stderr_bytes", 1024, 64 * 1024 * 1024),
            (self.max_entries, "max_entries", 1, 100_000),
            (self.max_source_bytes, "max_source_bytes", 1, 64 * 1024 * 1024 * 1024),
            (self.max_extracted_bytes, "max_extracted_bytes", 1, 256 * 1024 * 1024 * 1024),
        ):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{label} is outside the supported bound")


@dataclass(frozen=True, slots=True)
class CbvExtraction:
    source: SourceFingerprint
    primary_path: Path
    entry_count: int
    extracted_bytes: int
    backend_name: str
    backend_sha256: str


@dataclass(slots=True)
class _CapturedStream:
    buffer: bytearray
    overflow: threading.Event


def _error(message: str, code: CbvExtractCode) -> CbvExtractError:
    return CbvExtractError(message, code=code)


def _is_reparse_point(st: os.stat_result) -> bool:
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(st, "st_file_attributes", 0) & marker)


def _validate_real_directory(path: Path, *, must_be_empty: bool) -> Path:
    try:
        st = path.lstat()
    except OSError as exc:
        raise _error("CBV extraction directory is unavailable", CbvExtractCode.OUTPUT_INVALID) from exc
    if stat.S_ISLNK(st.st_mode) or _is_reparse_point(st) or not stat.S_ISDIR(st.st_mode):
        raise _error(
            "CBV extraction directory must be a real non-indirected directory",
            CbvExtractCode.OUTPUT_INVALID,
        )
    absolute = Path(os.path.abspath(os.fspath(path)))
    if must_be_empty:
        try:
            if next(absolute.iterdir(), None) is not None:
                raise _error(
                    "CBV extraction directory must be empty",
                    CbvExtractCode.OUTPUT_INVALID,
                )
        except OSError as exc:
            raise _error(
                "CBV extraction directory could not be inspected",
                CbvExtractCode.OUTPUT_INVALID,
            ) from exc
    return absolute


def _read_capped(stream, limit: int, captured: _CapturedStream) -> None:
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            remaining = limit + 1 - len(captured.buffer)
            if remaining > 0:
                captured.buffer.extend(chunk[:remaining])
            if len(captured.buffer) > limit:
                captured.overflow.set()
                return
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _sterile_environment(executable: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in ("SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    env["PATH"] = os.fspath(executable.parent)
    env["LC_ALL"] = "C.UTF-8"
    env["LANG"] = "C.UTF-8"
    return env


def _scan_output(directory: Path) -> tuple[set[str], int]:
    files: set[str] = set()
    total = 0
    try:
        for current, directory_names, file_names in os.walk(directory, followlinks=False):
            current_path = Path(current)
            for name in directory_names:
                child = current_path / name
                st = child.lstat()
                if stat.S_ISLNK(st.st_mode) or _is_reparse_point(st) or not stat.S_ISDIR(st.st_mode):
                    raise _error(
                        "CBV extractor produced an unsafe directory entry",
                        CbvExtractCode.OUTPUT_INVALID,
                    )
            for name in file_names:
                child = current_path / name
                st = child.lstat()
                if stat.S_ISLNK(st.st_mode) or _is_reparse_point(st) or not stat.S_ISREG(st.st_mode):
                    raise _error(
                        "CBV extractor produced an unsafe file entry",
                        CbvExtractCode.OUTPUT_INVALID,
                    )
                relative = child.relative_to(directory).as_posix()
                files.add(relative)
                total += st.st_size
    except CbvExtractError:
        raise
    except OSError as exc:
        raise _error(
            "CBV extraction output could not be inspected",
            CbvExtractCode.OUTPUT_INVALID,
        ) from exc
    return files, total


def _run_uncbv(
    executable: Path,
    arguments: list[str],
    config: ExternalCbvExtractorConfig,
    *,
    cwd: Path,
    monitor_directory: Path | None = None,
) -> bytes:
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen(
            [os.fspath(executable), *arguments],
            cwd=os.fspath(cwd),
            env=_sterile_environment(executable),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=creationflags,
            start_new_session=(os.name != "nt"),
        )
    except OSError as exc:
        raise _error(
            "CBV extractor backend could not be started",
            CbvExtractCode.BACKEND_INVALID,
        ) from exc

    assert process.stdout is not None and process.stderr is not None
    stdout = _CapturedStream(bytearray(), threading.Event())
    stderr = _CapturedStream(bytearray(), threading.Event())
    threads = (
        threading.Thread(
            target=_read_capped,
            args=(process.stdout, config.max_stdout_bytes, stdout),
            daemon=True,
        ),
        threading.Thread(
            target=_read_capped,
            args=(process.stderr, config.max_stderr_bytes, stderr),
            daemon=True,
        ),
    )
    for thread in threads:
        thread.start()

    deadline = time.monotonic() + float(config.timeout_seconds)
    timed_out = False
    overflow = False
    monitor_error: CbvExtractError | None = None
    while process.poll() is None:
        if stdout.overflow.is_set() or stderr.overflow.is_set():
            overflow = True
            process.kill()
            break
        if monitor_directory is not None:
            try:
                _, size = _scan_output(monitor_directory)
                if size > config.max_extracted_bytes:
                    monitor_error = _error(
                        "CBV extracted content exceeds the configured limit",
                        CbvExtractCode.RESOURCE_LIMIT,
                    )
                    process.kill()
                    break
            except CbvExtractError as exc:
                monitor_error = exc
                process.kill()
                break
        if time.monotonic() >= deadline:
            timed_out = True
            process.kill()
            break
        time.sleep(0.02)

    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)
    for thread in threads:
        thread.join(timeout=2.0)

    if monitor_error is not None:
        raise monitor_error
    if timed_out:
        raise _error(
            "CBV extractor backend exceeded its time limit",
            CbvExtractCode.BACKEND_TIMEOUT,
        )
    if overflow or stdout.overflow.is_set() or stderr.overflow.is_set():
        raise _error(
            "CBV extractor backend exceeded its output limit",
            CbvExtractCode.BACKEND_OUTPUT_LIMIT,
        )
    if process.returncode != 0:
        raise _error(
            f"CBV extractor backend failed with exit code {process.returncode}",
            CbvExtractCode.BACKEND_FAILED,
        )
    return bytes(stdout.buffer)


def _normalize_entry_name(value: str) -> str:
    if not value or len(value) > MAX_ENTRY_NAME_CHARS or "\x00" in value:
        raise _error("CBV archive contains an invalid entry name", CbvExtractCode.INVALID_ENTRY)
    normalized = value.replace("\\", "/")
    windows = PureWindowsPath(value)
    path = PurePosixPath(normalized)
    parts = path.parts
    if (
        normalized.startswith("/")
        or windows.is_absolute()
        or bool(windows.drive)
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
        or any(len(part) > 255 for part in parts)
    ):
        raise _error("CBV archive contains an unsafe entry path", CbvExtractCode.INVALID_ENTRY)
    return PurePosixPath(*parts).as_posix()


def _parse_entry_list(data: bytes, *, max_entries: int) -> tuple[str, ...]:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise _error(
            "CBV extractor returned a non-UTF-8 entry list",
            CbvExtractCode.INVALID_ENTRY,
        ) from exc
    raw_names = [line.rstrip("\r") for line in text.splitlines() if line.rstrip("\r")]
    if not raw_names or len(raw_names) > max_entries:
        raise _error(
            "CBV archive entry count is outside the configured bound",
            CbvExtractCode.RESOURCE_LIMIT,
        )
    names = tuple(_normalize_entry_name(name) for name in raw_names)
    folded = [name.casefold() for name in names]
    if len(set(folded)) != len(folded):
        raise _error(
            "CBV archive contains duplicate or case-colliding entries",
            CbvExtractCode.INVALID_ENTRY,
        )
    return names


def extract_cbv_external(
    path: str | Path,
    output_directory: str | Path,
    config: ExternalCbvExtractorConfig,
) -> CbvExtraction:
    """Extract one immutable CBV archive into a fresh trusted-host directory."""

    if not isinstance(config, ExternalCbvExtractorConfig):
        raise TypeError("config must be an ExternalCbvExtractorConfig")
    source_path = Path(path)
    if source_path.suffix.lower() != ".cbv":
        raise _error(
            "CBV extractor supports .cbv archives only",
            CbvExtractCode.UNSUPPORTED_SOURCE,
        )
    try:
        source = fingerprint(source_path)
        backend = fingerprint(config.executable)
    except (OSError, ValueError) as exc:
        raise _error(
            "CBV source or extractor backend failed read-only validation",
            CbvExtractCode.SOURCE_INVALID,
        ) from exc
    if source.size > config.max_source_bytes:
        raise _error(
            "CBV archive exceeds the configured source size limit",
            CbvExtractCode.RESOURCE_LIMIT,
        )
    if backend.sha256 != config.expected_backend_sha256:
        raise _error(
            "CBV extractor backend identity does not match the configured SHA-256",
            CbvExtractCode.BACKEND_INVALID,
        )

    output = _validate_real_directory(Path(output_directory), must_be_empty=True)
    executable = Path(backend.path)
    source_absolute = Path(source.path)
    listed = _run_uncbv(
        executable,
        ["list", os.fspath(source_absolute)],
        config,
        cwd=output,
    )
    entries = _parse_entry_list(listed, max_entries=config.max_entries)
    if not verify_source_unchanged(source, source_absolute):
        raise _error(
            "CBV source changed while its entry list was inspected",
            CbvExtractCode.SOURCE_CHANGED,
        )

    _run_uncbv(
        executable,
        [
            "extract",
            os.fspath(source_absolute),
            f"--output={os.fspath(output)}",
            "--no-confirm",
        ],
        config,
        cwd=output,
        monitor_directory=output,
    )
    if not verify_source_unchanged(source, source_absolute):
        raise _error(
            "CBV source changed while it was extracted",
            CbvExtractCode.SOURCE_CHANGED,
        )
    if not verify_source_unchanged(backend, executable):
        raise _error(
            "CBV extractor backend changed while it was running",
            CbvExtractCode.BACKEND_INVALID,
        )

    observed, extracted_bytes = _scan_output(output)
    if extracted_bytes > config.max_extracted_bytes:
        raise _error(
            "CBV extracted content exceeds the configured limit",
            CbvExtractCode.RESOURCE_LIMIT,
        )
    expected = set(entries)
    if observed != expected:
        raise _error(
            "CBV extractor output does not match the validated archive entry list",
            CbvExtractCode.OUTPUT_INVALID,
        )
    primary_names = [name for name in entries if PurePosixPath(name).suffix.lower() == ".cbh"]
    if len(primary_names) != 1:
        raise _error(
            "CBV archive must contain exactly one classic .cbh primary source",
            CbvExtractCode.OUTPUT_INVALID,
        )
    primary = output.joinpath(*PurePosixPath(primary_names[0]).parts)
    return CbvExtraction(
        source=source,
        primary_path=primary,
        entry_count=len(entries),
        extracted_bytes=extracted_bytes,
        backend_name="uncbv",
        backend_sha256=backend.sha256,
    )
