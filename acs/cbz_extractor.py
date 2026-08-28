from __future__ import annotations

"""Bounded encrypted-CBZ execution without a format-support overclaim.

This module is deliberately narrower than semantic ChessBase import. It feeds
one password to the separately configured/pinned ``uncbv`` executable through
stdin (never argv/environment), decrypts into a private staging tree, delegates
the resulting CBV to the already-qualified CBV extractor, and publishes the
extracted files only after the whole staged operation succeeds.

A successful call proves backend mechanics and atomic file-service behavior. It
does not by itself prove ChessBase semantic compatibility or promote CBZ above
BLOCKED without independent real-corpus acceptance evidence.
"""

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import threading
import time

from .cbv_extractor import (
    CbvExtractError,
    ExternalCbvExtractorConfig,
    _is_reparse_point,
    _sterile_environment,
    _validate_real_directory,
    extract_cbv_external,
)
from .import_contract import SourceFingerprint, fingerprint, verify_source_unchanged


MAX_PASSWORD_BYTES = 1024


class CbzExtractCode(str, Enum):
    UNSUPPORTED_SOURCE = "unsupported_source"
    PASSWORD_INVALID = "password_invalid"
    SOURCE_INVALID = "source_invalid"
    SOURCE_CHANGED = "source_changed"
    BACKEND_INVALID = "backend_invalid"
    BACKEND_TIMEOUT = "backend_timeout"
    BACKEND_OUTPUT_LIMIT = "backend_output_limit"
    BACKEND_FAILED = "backend_failed"
    CANCELLED = "cancelled"
    DECRYPTED_ARCHIVE_INVALID = "decrypted_archive_invalid"
    CBV_STAGE_FAILED = "cbv_stage_failed"
    RESOURCE_LIMIT = "resource_limit"
    OUTPUT_INVALID = "output_invalid"
    TEMP_CLEANUP_FAILED = "temp_cleanup_failed"


class CbzExtractError(RuntimeError):
    def __init__(self, message: str, *, code: CbzExtractCode) -> None:
        super().__init__(message)
        self.code = CbzExtractCode(code)


@dataclass(frozen=True, slots=True)
class CbzExtraction:
    source: SourceFingerprint
    primary_path: Path
    entry_count: int
    extracted_bytes: int
    backend_name: str
    backend_sha256: str
    decrypted_cbv_sha256: str


@dataclass(slots=True)
class _CapturedStream:
    buffer: bytearray
    overflow: threading.Event


def _error(message: str, code: CbzExtractCode) -> CbzExtractError:
    return CbzExtractError(message, code=code)


def _password_payload(password: str) -> bytearray:
    if type(password) is not str or not password:
        raise _error("CBZ password is missing or invalid", CbzExtractCode.PASSWORD_INVALID)
    if any(character in password for character in ("\x00", "\r", "\n")):
        raise _error(
            "CBZ password contains an unsupported control character",
            CbzExtractCode.PASSWORD_INVALID,
        )
    try:
        encoded = password.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise _error(
            "CBZ password could not be encoded",
            CbzExtractCode.PASSWORD_INVALID,
        ) from exc
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise _error(
            "CBZ password exceeds the configured bound",
            CbzExtractCode.PASSWORD_INVALID,
        )
    payload = bytearray(encoded)
    payload.append(0x0A)
    return payload


def _wipe(buffer: bytearray) -> None:
    for index in range(len(buffer)):
        buffer[index] = 0
    buffer.clear()


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


def _kill_and_wait(process: subprocess.Popen[bytes]) -> None:
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=2.0)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
        except OSError:
            pass


def _monitor_decrypted_file(path: Path, *, max_bytes: int) -> CbzExtractError | None:
    if not path.exists():
        return None
    try:
        metadata = path.lstat()
    except OSError:
        return _error(
            "CBZ decrypted staging output is unavailable",
            CbzExtractCode.DECRYPTED_ARCHIVE_INVALID,
        )
    if (
        stat.S_ISLNK(metadata.st_mode)
        or _is_reparse_point(metadata)
        or not stat.S_ISREG(metadata.st_mode)
    ):
        return _error(
            "CBZ backend produced an unsafe decrypted staging object",
            CbzExtractCode.DECRYPTED_ARCHIVE_INVALID,
        )
    if metadata.st_size > max_bytes:
        return _error(
            "CBZ decrypted archive exceeds the configured resource bound",
            CbzExtractCode.RESOURCE_LIMIT,
        )
    return None


def _run_uncbv_decrypt(
    executable: Path,
    source: Path,
    destination: Path,
    config: ExternalCbvExtractorConfig,
    password: str,
    *,
    cwd: Path,
    cancel_event: threading.Event | None = None,
) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise _error("CBZ decrypt was cancelled", CbzExtractCode.CANCELLED)

    payload = _password_payload(password)
    arguments = [
        "decrypt",
        os.fspath(source),
        f"--output={os.fspath(destination)}",
        "--no-confirm",
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    try:
        process = subprocess.Popen(
            [os.fspath(executable), *arguments],
            cwd=os.fspath(cwd),
            env=_sterile_environment(executable),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=creationflags,
            start_new_session=(os.name != "nt"),
        )
    except OSError as exc:
        _wipe(payload)
        raise _error(
            "CBZ backend could not be started",
            CbzExtractCode.BACKEND_INVALID,
        ) from exc

    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    stdout = _CapturedStream(bytearray(), threading.Event())
    stderr = _CapturedStream(bytearray(), threading.Event())
    readers = (
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
    for reader in readers:
        reader.start()

    secret_write_failed = False
    try:
        process.stdin.write(payload)
        process.stdin.flush()
    except (BrokenPipeError, OSError):
        secret_write_failed = True
    finally:
        _wipe(payload)
        try:
            process.stdin.close()
        except OSError:
            pass

    deadline = time.monotonic() + float(config.timeout_seconds)
    timed_out = False
    cancelled = False
    overflow = False
    monitor_error: CbzExtractError | None = None
    while process.poll() is None:
        if stdout.overflow.is_set() or stderr.overflow.is_set():
            overflow = True
            _kill_and_wait(process)
            break
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            _kill_and_wait(process)
            break
        monitor_error = _monitor_decrypted_file(
            destination,
            max_bytes=config.max_extracted_bytes,
        )
        if monitor_error is not None:
            _kill_and_wait(process)
            break
        if time.monotonic() >= deadline:
            timed_out = True
            _kill_and_wait(process)
            break
        time.sleep(0.02)

    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        _kill_and_wait(process)
    for reader in readers:
        reader.join(timeout=2.0)

    if monitor_error is not None:
        raise monitor_error
    if cancelled:
        raise _error("CBZ decrypt was cancelled", CbzExtractCode.CANCELLED)
    if timed_out:
        raise _error(
            "CBZ backend exceeded its time limit",
            CbzExtractCode.BACKEND_TIMEOUT,
        )
    if overflow or stdout.overflow.is_set() or stderr.overflow.is_set():
        raise _error(
            "CBZ backend exceeded its diagnostic output limit",
            CbzExtractCode.BACKEND_OUTPUT_LIMIT,
        )
    if secret_write_failed or process.returncode != 0:
        raise _error(
            "CBZ backend failed while decrypting the archive",
            CbzExtractCode.BACKEND_FAILED,
        )


def _validate_decrypted_cbv(path: Path, *, max_bytes: int) -> SourceFingerprint:
    error = _monitor_decrypted_file(path, max_bytes=max_bytes)
    if error is not None:
        raise error
    try:
        metadata = path.lstat()
        if metadata.st_size <= 0:
            raise _error(
                "CBZ backend produced an empty decrypted archive",
                CbzExtractCode.DECRYPTED_ARCHIVE_INVALID,
            )
        with path.open("rb") as handle:
            magic = handle.read(2)
    except CbzExtractError:
        raise
    except OSError as exc:
        raise _error(
            "CBZ decrypted archive could not be validated",
            CbzExtractCode.DECRYPTED_ARCHIVE_INVALID,
        ) from exc
    if magic != b"\x08\x00":
        raise _error(
            "CBZ password or decrypted archive is invalid",
            CbzExtractCode.DECRYPTED_ARCHIVE_INVALID,
        )
    try:
        return fingerprint(path)
    except (OSError, ValueError) as exc:
        raise _error(
            "CBZ decrypted archive failed immutable fingerprinting",
            CbzExtractCode.DECRYPTED_ARCHIVE_INVALID,
        ) from exc


def _make_private_workspace(parent: Path) -> Path:
    try:
        workspace = Path(
            tempfile.mkdtemp(
                prefix=".accessible-chess-cbz-",
                dir=os.fspath(parent),
            )
        )
        if os.name != "nt":
            workspace.chmod(0o700)
        return workspace
    except OSError as exc:
        raise _error(
            "CBZ private staging workspace could not be created",
            CbzExtractCode.OUTPUT_INVALID,
        ) from exc


def _cleanup_private_workspace(path: Path) -> None:
    try:
        if path.exists():
            shutil.rmtree(path)
    except OSError as exc:
        raise _error(
            "CBZ temporary decrypted material could not be removed",
            CbzExtractCode.TEMP_CLEANUP_FAILED,
        ) from exc


def _publish_staged_directory(staged: Path, output: Path) -> None:
    try:
        _validate_real_directory(output, must_be_empty=True)
    except CbvExtractError as exc:
        raise _error(
            "CBZ final output changed before publish",
            CbzExtractCode.OUTPUT_INVALID,
        ) from exc
    try:
        output.rmdir()
        os.replace(staged, output)
    except OSError as exc:
        try:
            if not output.exists():
                output.mkdir()
        except OSError:
            pass
        raise _error(
            "CBZ extracted output could not be published atomically",
            CbzExtractCode.OUTPUT_INVALID,
        ) from exc


def extract_cbz_external(
    path: str | Path,
    output_directory: str | Path,
    config: ExternalCbvExtractorConfig,
    password: str,
    *,
    cancel_event: threading.Event | None = None,
) -> CbzExtraction:
    """Decrypt one immutable CBZ, stage CBV extraction, then publish atomically.

    ``password`` is sent only through the child process stdin. It is never put
    in argv, the environment, a report, or an exception. The caller still owns
    the lifetime of its Python string; this function cannot guarantee wiping an
    immutable caller object from interpreter memory.
    """

    if not isinstance(config, ExternalCbvExtractorConfig):
        raise TypeError("config must be an ExternalCbvExtractorConfig")
    source_path = Path(path)
    if source_path.suffix.lower() != ".cbz":
        raise _error(
            "Encrypted extractor supports .cbz only",
            CbzExtractCode.UNSUPPORTED_SOURCE,
        )
    password_check = _password_payload(password)
    _wipe(password_check)

    if cancel_event is not None and cancel_event.is_set():
        raise _error("CBZ extraction was cancelled", CbzExtractCode.CANCELLED)

    try:
        source = fingerprint(source_path)
        backend = fingerprint(config.executable)
    except (OSError, ValueError) as exc:
        raise _error(
            "CBZ source or backend failed read-only validation",
            CbzExtractCode.SOURCE_INVALID,
        ) from exc
    if source.size > config.max_source_bytes:
        raise _error(
            "CBZ archive exceeds the configured source size limit",
            CbzExtractCode.RESOURCE_LIMIT,
        )
    if backend.sha256 != config.expected_backend_sha256:
        raise _error(
            "CBZ backend identity does not match the configured SHA-256",
            CbzExtractCode.BACKEND_INVALID,
        )

    output = _validate_real_directory(Path(output_directory), must_be_empty=True)
    executable = Path(backend.path)
    source_absolute = Path(source.path)
    workspace = _make_private_workspace(output.parent)
    staged = workspace / "extracted"
    decrypted = workspace / "payload.cbv"
    try:
        try:
            staged.mkdir()
        except OSError as exc:
            raise _error(
                "CBZ private extraction stage could not be created",
                CbzExtractCode.OUTPUT_INVALID,
            ) from exc
        _run_uncbv_decrypt(
            executable,
            source_absolute,
            decrypted,
            config,
            password,
            cwd=workspace,
            cancel_event=cancel_event,
        )
        if not verify_source_unchanged(source, source_absolute):
            raise _error(
                "CBZ source changed while it was decrypted",
                CbzExtractCode.SOURCE_CHANGED,
            )
        if not verify_source_unchanged(backend, executable):
            raise _error(
                "CBZ backend changed while decrypting",
                CbzExtractCode.BACKEND_INVALID,
            )

        decrypted_fingerprint = _validate_decrypted_cbv(
            decrypted,
            max_bytes=config.max_extracted_bytes,
        )
        if cancel_event is not None and cancel_event.is_set():
            raise _error("CBZ extraction was cancelled", CbzExtractCode.CANCELLED)

        try:
            cbv_result = extract_cbv_external(decrypted, staged, config)
        except CbvExtractError as exc:
            raise _error(
                "Decrypted CBV failed bounded extraction",
                CbzExtractCode.CBV_STAGE_FAILED,
            ) from exc

        if cancel_event is not None and cancel_event.is_set():
            raise _error(
                "CBZ extraction was cancelled before publish",
                CbzExtractCode.CANCELLED,
            )
        if not verify_source_unchanged(source, source_absolute):
            raise _error(
                "CBZ source changed before publish",
                CbzExtractCode.SOURCE_CHANGED,
            )
        if not verify_source_unchanged(backend, executable):
            raise _error(
                "CBZ backend changed before publish",
                CbzExtractCode.BACKEND_INVALID,
            )

        primary_relative = cbv_result.primary_path.relative_to(staged)
        _publish_staged_directory(staged, output)
        return CbzExtraction(
            source=source,
            primary_path=output / primary_relative,
            entry_count=cbv_result.entry_count,
            extracted_bytes=cbv_result.extracted_bytes,
            backend_name=cbv_result.backend_name,
            backend_sha256=cbv_result.backend_sha256,
            decrypted_cbv_sha256=decrypted_fingerprint.sha256,
        )
    finally:
        # After a successful directory rename, only the decrypted CBV remains
        # in the private workspace. On every failure, staged output is removed.
        _cleanup_private_workspace(workspace)
