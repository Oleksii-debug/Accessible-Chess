from __future__ import annotations

"""Provider-neutral, fail-closed verification for future update payloads.

This module deliberately does not download, execute, or install anything. It
turns an update package into a ``VerifiedUpdate`` capability only after signed
metadata, version policy, expiry, source URL, size and SHA-256 binding have all
passed. Cryptographic key storage/rotation is supplied by a replaceable
asymmetric ``SignatureVerifier``; no signing secret belongs in the client.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import hashlib
import json
from pathlib import Path
import re
import stat
from typing import Protocol
from urllib.parse import urlsplit


_METADATA_LIMIT = 64 * 1024
_DEFAULT_PACKAGE_LIMIT = 4 * 1024 * 1024 * 1024
_PRODUCT = "accessible-chess"
_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_SIGNED_KEYS = frozenset(
    {
        "schema_version",
        "product",
        "version",
        "minimum_current_version",
        "published_at",
        "expires_at",
        "download_url",
        "package_sha256",
        "package_size",
        "key_id",
    }
)
_ENVELOPE_KEYS = frozenset({"signed", "signature"})


class UpdateSecurityError(RuntimeError):
    pass


class SignatureVerifier(Protocol):
    """Verify a detached signature using client-embedded public trust only."""

    def verify(self, *, key_id: str, message: bytes, signature: bytes) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class VerifiedUpdate:
    package_path: Path
    version: str
    download_url: str
    package_sha256: str
    package_size: int
    key_id: str
    published_at: datetime
    expires_at: datetime


class _DuplicateKey(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKey(key)
        value[key] = item
    return value


def _version(value: object, label: str) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise UpdateSecurityError(f"{label} is invalid")
    match = _VERSION_RE.fullmatch(value)
    if match is None:
        raise UpdateSecurityError(f"{label} is invalid")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _utc_time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise UpdateSecurityError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise UpdateSecurityError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise UpdateSecurityError(f"{label} is invalid")
    return parsed


def _download_url(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise UpdateSecurityError("download URL is invalid")
    if "\\" in value or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise UpdateSecurityError("download URL is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise UpdateSecurityError("download URL is invalid") from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise UpdateSecurityError("download URL must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise UpdateSecurityError("download URL must not contain userinfo")
    if parsed.fragment:
        raise UpdateSecurityError("download URL must not contain a fragment")
    if port is not None and not (1 <= port <= 65535):
        raise UpdateSecurityError("download URL has an invalid port")
    return value


def _canonical_signed(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _regular_file(path: Path) -> stat.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise UpdateSecurityError("update package is unavailable") from exc
    reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISREG(info.st_mode):
        raise UpdateSecurityError("update package must be a regular non-reparse file")
    return info


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise UpdateSecurityError("update package could not be read") from exc
    return digest.hexdigest()


def verify_update_package(
    metadata: bytes,
    package_path: str | Path,
    *,
    current_version: str,
    verifier: SignatureVerifier,
    now: datetime | None = None,
    max_package_bytes: int = _DEFAULT_PACKAGE_LIMIT,
) -> VerifiedUpdate:
    """Return a capability only for an authentic, applicable package.

    Callers must treat failure as non-applicable and must never execute or
    install the candidate package on any exception from this function.
    """
    if not isinstance(metadata, bytes) or not metadata or len(metadata) > _METADATA_LIMIT:
        raise UpdateSecurityError("update metadata is invalid")
    if not callable(getattr(verifier, "verify", None)):
        raise TypeError("verifier must implement SignatureVerifier")
    if type(max_package_bytes) is not int or max_package_bytes < 1:
        raise ValueError("max_package_bytes must be a positive integer")
    current = _version(current_version, "current version")

    try:
        envelope = json.loads(metadata.decode("utf-8"), object_pairs_hook=_unique_object)
    except (_DuplicateKey, UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateSecurityError("update metadata is invalid") from exc
    if not isinstance(envelope, dict) or set(envelope) != _ENVELOPE_KEYS:
        raise UpdateSecurityError("update metadata envelope is invalid")
    signed = envelope.get("signed")
    signature_text = envelope.get("signature")
    if not isinstance(signed, dict) or set(signed) != _SIGNED_KEYS:
        raise UpdateSecurityError("signed update metadata is invalid")
    if not isinstance(signature_text, str) or not signature_text:
        raise UpdateSecurityError("update signature is missing")

    schema = signed.get("schema_version")
    if type(schema) is not int or schema != _SCHEMA_VERSION:
        raise UpdateSecurityError("update metadata schema is unsupported")
    if signed.get("product") != _PRODUCT:
        raise UpdateSecurityError("update product identity is invalid")
    key_id = signed.get("key_id")
    if not isinstance(key_id, str) or _KEY_ID_RE.fullmatch(key_id) is None:
        raise UpdateSecurityError("update signing key id is invalid")
    download_url = _download_url(signed.get("download_url"))
    digest = signed.get("package_sha256")
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        raise UpdateSecurityError("update package digest is invalid")
    package_size = signed.get("package_size")
    if type(package_size) is not int or not (1 <= package_size <= max_package_bytes):
        raise UpdateSecurityError("update package size is invalid")

    try:
        signature = base64.b64decode(signature_text, validate=True)
    except (ValueError, TypeError) as exc:
        raise UpdateSecurityError("update signature encoding is invalid") from exc
    if not signature or len(signature) > 16 * 1024:
        raise UpdateSecurityError("update signature encoding is invalid")
    try:
        authentic = verifier.verify(
            key_id=key_id,
            message=_canonical_signed(signed),
            signature=signature,
        )
    except Exception as exc:
        raise UpdateSecurityError("update signature verification failed") from exc
    if authentic is not True:
        raise UpdateSecurityError("update signature verification failed")

    target = _version(signed.get("version"), "target version")
    minimum = _version(signed.get("minimum_current_version"), "minimum current version")
    if target <= current:
        raise UpdateSecurityError("update would not advance the installed version")
    if current < minimum:
        raise UpdateSecurityError("installed version is too old for this update path")

    published = _utc_time(signed.get("published_at"), "published time")
    expires = _utc_time(signed.get("expires_at"), "expiry time")
    instant = datetime.now(timezone.utc) if now is None else now
    if instant.tzinfo is None or instant.utcoffset() != timezone.utc.utcoffset(instant):
        raise ValueError("now must be timezone-aware UTC")
    if expires <= published or instant > expires:
        raise UpdateSecurityError("update metadata is expired")
    if published > instant:
        raise UpdateSecurityError("update metadata is not yet valid")

    package = Path(package_path)
    info_before = _regular_file(package)
    if info_before.st_size != package_size:
        raise UpdateSecurityError("update package size mismatch")
    actual_digest = _sha256(package)
    info_after = _regular_file(package)
    before_identity = (
        info_before.st_dev,
        info_before.st_ino,
        info_before.st_size,
        getattr(info_before, "st_mtime_ns", 0),
    )
    after_identity = (
        info_after.st_dev,
        info_after.st_ino,
        info_after.st_size,
        getattr(info_after, "st_mtime_ns", 0),
    )
    if after_identity != before_identity:
        raise UpdateSecurityError("update package changed during verification")
    if actual_digest != digest:
        raise UpdateSecurityError("update package digest mismatch")

    return VerifiedUpdate(
        package_path=package,
        version=str(signed["version"]),
        download_url=download_url,
        package_sha256=digest,
        package_size=package_size,
        key_id=key_id,
        published_at=published,
        expires_at=expires,
    )
