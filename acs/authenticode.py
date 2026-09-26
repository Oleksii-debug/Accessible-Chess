from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, Mapping


class AuthenticodeStatus(str, Enum):
    """Bounded, provider-neutral Authenticode verification result."""

    VALID = "valid"
    UNSIGNED = "unsigned"
    UNTRUSTED = "untrusted"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class AuthenticodeEvidence:
    """Non-secret evidence suitable for release policy decisions and logs.

    The verifier deliberately excludes the raw PowerShell StatusMessage because
    it may contain machine-specific paths or provider text. Certificate subjects
    and thumbprints are public signing metadata and are bounded before exposure.
    """

    status: AuthenticodeStatus
    trusted: bool
    signer_subject: str | None = None
    signer_thumbprint: str | None = None
    timestamp_subject: str | None = None

    @property
    def acceptable_for_release(self) -> bool:
        return self.status is AuthenticodeStatus.VALID and self.trusted


Runner = Callable[..., subprocess.CompletedProcess[str]]


class WindowsAuthenticodeVerifier:
    """Fail-closed Windows Authenticode verifier.

    Verification uses Windows' own Get-AuthenticodeSignature trust evaluation.
    This class never signs binaries, loads private keys, or changes certificate
    stores. On non-Windows hosts it returns UNAVAILABLE rather than pretending a
    signature is valid.
    """

    def __init__(self, *, runner: Runner = subprocess.run) -> None:
        self._runner = runner

    def verify(self, path: str | os.PathLike[str]) -> AuthenticodeEvidence:
        target = Path(path)
        if not target.is_file():
            return AuthenticodeEvidence(AuthenticodeStatus.ERROR, False)

        if sys.platform != "win32":
            return AuthenticodeEvidence(AuthenticodeStatus.UNAVAILABLE, False)

        script = r"""
$ErrorActionPreference = 'Stop'
$sig = Get-AuthenticodeSignature -LiteralPath $env:ACS_AUTHENTICODE_TARGET
$result = [ordered]@{
  Status = [string]$sig.Status
  SignerSubject = if ($null -ne $sig.SignerCertificate) { [string]$sig.SignerCertificate.Subject } else { $null }
  SignerThumbprint = if ($null -ne $sig.SignerCertificate) { [string]$sig.SignerCertificate.Thumbprint } else { $null }
  TimestampSubject = if ($null -ne $sig.TimeStamperCertificate) { [string]$sig.TimeStamperCertificate.Subject } else { $null }
}
$result | ConvertTo-Json -Compress
""".strip()

        env = dict(os.environ)
        env["ACS_AUTHENTICODE_TARGET"] = str(target.resolve())

        try:
            completed = self._runner(
                [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "-",
                ],
                input=script,
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
                env=env,
            )
        except (OSError, subprocess.SubprocessError):
            return AuthenticodeEvidence(AuthenticodeStatus.ERROR, False)

        if completed.returncode != 0:
            return AuthenticodeEvidence(AuthenticodeStatus.ERROR, False)

        try:
            payload = json.loads(completed.stdout)
        except (json.JSONDecodeError, TypeError):
            return AuthenticodeEvidence(AuthenticodeStatus.ERROR, False)

        if not isinstance(payload, Mapping):
            return AuthenticodeEvidence(AuthenticodeStatus.ERROR, False)

        status = _classify_status(payload.get("Status"))
        return AuthenticodeEvidence(
            status=status,
            trusted=status is AuthenticodeStatus.VALID,
            signer_subject=_bounded_text(payload.get("SignerSubject"), 512),
            signer_thumbprint=_normalize_thumbprint(payload.get("SignerThumbprint")),
            timestamp_subject=_bounded_text(payload.get("TimestampSubject"), 512),
        )


def require_trusted_authenticode(
    path: str | os.PathLike[str],
    *,
    verifier: WindowsAuthenticodeVerifier | None = None,
) -> AuthenticodeEvidence:
    """Verify a release binary and raise without leaking target/provider details.

    Callers that gate publication can use this helper to make the policy
    explicit. The exception intentionally contains only the bounded status.
    """

    evidence = (verifier or WindowsAuthenticodeVerifier()).verify(path)
    if not evidence.acceptable_for_release:
        raise ValueError(f"unacceptable Authenticode signature: {evidence.status.value}")
    return evidence


def _classify_status(value: object) -> AuthenticodeStatus:
    text = str(value or "").strip().casefold()
    if text == "valid":
        return AuthenticodeStatus.VALID
    if text == "notsigned":
        return AuthenticodeStatus.UNSIGNED
    if text == "nottrusted":
        return AuthenticodeStatus.UNTRUSTED
    if text in {"hashmismatch", "notsupported"}:
        return AuthenticodeStatus.INVALID
    if text in {"unknownerror", ""}:
        return AuthenticodeStatus.ERROR
    return AuthenticodeStatus.ERROR


def _bounded_text(value: object, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\x00", "").strip()
    if not text:
        return None
    return text[:limit]


def _normalize_thumbprint(value: object) -> str | None:
    if value is None:
        return None
    text = "".join(ch for ch in str(value) if ch.isalnum()).upper()
    if not text:
        return None
    if len(text) > 128:
        text = text[:128]
    return text
