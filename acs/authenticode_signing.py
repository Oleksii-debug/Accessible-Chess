from __future__ import annotations

"""Fail-closed Windows Authenticode signing operation contract.

This module deliberately owns only invocation of an externally provisioned
Windows signing identity. It never imports, stores, exports, or provisions
certificate key material and it does not decide whether a resulting signature
is trusted for release. Release trust remains a separate verification step.
"""

from dataclasses import dataclass
from enum import Enum
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Callable
from urllib.parse import urlsplit


_MAX_TARGET_BYTES = 2 * 1024 * 1024 * 1024
_PE_OFFSET_LIMIT = 16 * 1024 * 1024
_SHA1_THUMBPRINT_RE = re.compile(r"^[0-9A-F]{40}$")


class SigningStatus(str, Enum):
    SIGNED = "signed"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"
    ERROR = "error"


@dataclass(frozen=True)
class SigningRequest:
    """Public, non-secret signing configuration.

    ``certificate_thumbprint`` identifies a certificate already available to
    Windows' certificate store. The module does not accept PFX paths, passwords,
    private-key bytes, or provider credentials.
    """

    certificate_thumbprint: str
    timestamp_url: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "certificate_thumbprint",
            _certificate_thumbprint(self.certificate_thumbprint),
        )
        object.__setattr__(self, "timestamp_url", _timestamp_url(self.timestamp_url))


@dataclass(frozen=True)
class SigningResult:
    status: SigningStatus
    bytes_changed: bool = False
    before_sha256: str | None = None
    after_sha256: str | None = None

    @property
    def operation_succeeded(self) -> bool:
        """True only for a completed mutation; this is not a trust verdict."""
        return self.status is SigningStatus.SIGNED and self.bytes_changed


Runner = Callable[..., subprocess.CompletedProcess[str]]


class WindowsSignToolSigner:
    """Invoke Microsoft's SignTool without exposing signing material to Python.

    The SignTool binary path is explicit and must itself be a direct regular
    file. The target must be a direct PE file. No shell is used. Success means
    SignTool returned zero and the target bytes changed; callers must still run
    the canonical Authenticode verifier before publication.
    """

    def __init__(self, *, runner: Runner = subprocess.run) -> None:
        self._runner = runner

    def sign(
        self,
        target: str | os.PathLike[str],
        *,
        signtool: str | os.PathLike[str],
        request: SigningRequest,
    ) -> SigningResult:
        if type(request) is not SigningRequest:
            return SigningResult(SigningStatus.REJECTED)

        target_path = Path(target)
        tool_path = Path(signtool)
        if not _direct_regular_file(target_path, max_bytes=_MAX_TARGET_BYTES):
            return SigningResult(SigningStatus.REJECTED)
        if not _direct_regular_file(tool_path, max_bytes=256 * 1024 * 1024):
            return SigningResult(SigningStatus.REJECTED)
        if not tool_path.is_absolute():
            return SigningResult(SigningStatus.REJECTED)
        if not _looks_like_portable_executable(target_path):
            return SigningResult(SigningStatus.REJECTED)
        if sys.platform != "win32":
            return SigningResult(SigningStatus.UNAVAILABLE)

        before_sha256 = _sha256(target_path)
        command = [
            str(tool_path),
            "sign",
            "/fd",
            "SHA256",
            "/td",
            "SHA256",
            "/tr",
            request.timestamp_url,
            "/sha1",
            request.certificate_thumbprint,
            str(target_path.resolve()),
        ]

        try:
            completed = self._runner(
                command,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            return SigningResult(
                SigningStatus.ERROR,
                before_sha256=before_sha256,
            )

        if completed.returncode != 0:
            return SigningResult(
                SigningStatus.ERROR,
                before_sha256=before_sha256,
            )
        if not _direct_regular_file(target_path, max_bytes=_MAX_TARGET_BYTES):
            return SigningResult(
                SigningStatus.ERROR,
                before_sha256=before_sha256,
            )
        if not _looks_like_portable_executable(target_path):
            return SigningResult(
                SigningStatus.ERROR,
                before_sha256=before_sha256,
            )

        after_sha256 = _sha256(target_path)
        changed = before_sha256 != after_sha256
        if not changed:
            return SigningResult(
                SigningStatus.ERROR,
                bytes_changed=False,
                before_sha256=before_sha256,
                after_sha256=after_sha256,
            )
        return SigningResult(
            SigningStatus.SIGNED,
            bytes_changed=True,
            before_sha256=before_sha256,
            after_sha256=after_sha256,
        )


def _certificate_thumbprint(value: object) -> str:
    if type(value) is not str:
        raise ValueError("certificate thumbprint must be text")
    text = "".join(ch for ch in value if not ch.isspace()).upper()
    if not _SHA1_THUMBPRINT_RE.fullmatch(text):
        raise ValueError("certificate thumbprint must be exactly 40 hexadecimal characters")
    return text


def _timestamp_url(value: object) -> str:
    if type(value) is not str:
        raise ValueError("timestamp URL must be text")
    if not value or value != value.strip():
        raise ValueError("timestamp URL must be canonical nonblank text")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ValueError("timestamp URL contains control characters")
    if "\\" in value:
        raise ValueError("timestamp URL contains an ambiguous backslash")
    parts = urlsplit(value)
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise ValueError("timestamp URL must use HTTPS")
    if parts.username is not None or parts.password is not None:
        raise ValueError("timestamp URL must not contain user information")
    if parts.fragment:
        raise ValueError("timestamp URL must not contain a fragment")
    if parts.port is not None and not 1 <= parts.port <= 65535:
        raise ValueError("timestamp URL port is invalid")
    return value


def _direct_regular_file(path: Path, *, max_bytes: int) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        return False
    if bool(getattr(info, "st_file_attributes", 0) & reparse_flag):
        return False
    if info.st_size <= 0 or info.st_size > max_bytes:
        return False
    return True


def _looks_like_portable_executable(path: Path) -> bool:
    try:
        size = path.stat().st_size
        if size < 0x40:
            return False
        with path.open("rb") as stream:
            if stream.read(2) != b"MZ":
                return False
            stream.seek(0x3C)
            raw = stream.read(4)
            if len(raw) != 4:
                return False
            pe_offset = int.from_bytes(raw, "little", signed=False)
            if pe_offset < 0x40 or pe_offset > _PE_OFFSET_LIMIT:
                return False
            if pe_offset + 4 > size:
                return False
            stream.seek(pe_offset)
            return stream.read(4) == b"PE\x00\x00"
    except OSError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "SigningRequest",
    "SigningResult",
    "SigningStatus",
    "WindowsSignToolSigner",
]
