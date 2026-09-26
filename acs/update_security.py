from __future__ import annotations

"""Provider-neutral, fail-closed verification for future update payloads.

This module deliberately does not download, execute, or install anything. It
turns an update package into a ``VerifiedUpdate`` capability only after signed
metadata, version policy, expiry, source URL, size and SHA-256 binding have all
passed. Cryptographic key storage/rotation is supplied by a replaceable
asymmetric ``SignatureVerifier``; no signing secret belongs in the client.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import BinaryIO, Iterator, Protocol
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
    """Authenticated metadata plus the only safe package-consumption authority.

    The pathname is informational. Code that consumes update bytes must use
    :func:`open_verified_update`, which revalidates the signed identity against
    an already-open read-only handle immediately before consumption.
    """

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


def _require_utc_instant(value: datetime | None) -> datetime:
    instant = datetime.now(timezone.utc) if value is None else value
    if instant.tzinfo is None or instant.utcoffset() != timezone.utc.utcoffset(instant):
        raise ValueError("now must be timezone-aware UTC")
    return instant


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


def _regular_file(path: Path) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise UpdateSecurityError("update package is unavailable") from exc
    reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISREG(info.st_mode):
        raise UpdateSecurityError("update package must be a regular non-reparse file")
    return info


def _regular_open_file(info: os.stat_result) -> None:
    reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if reparse or not stat.S_ISREG(info.st_mode):
        raise UpdateSecurityError("opened update package is not a regular non-reparse file")


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(getattr(info, "st_dev", 0)),
        int(getattr(info, "st_ino", 0)),
        int(info.st_size),
        int(getattr(info, "st_mtime_ns", 0)),
    )


@contextmanager
def _verified_package_handle(
    path: Path,
    *,
    expected_size: int,
    expected_digest: str,
) -> Iterator[BinaryIO]:
    """Open, authenticate, rewind, and retain one immutable read handle."""
    before = _regular_file(path)
    if before.st_size != expected_size:
        raise UpdateSecurityError("update package size mismatch")

    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            _regular_open_file(opened)
            if _file_identity(opened) != _file_identity(before):
                raise UpdateSecurityError("update package changed before verified open")

            digest = hashlib.sha256()
            total = 0
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > expected_size:
                    raise UpdateSecurityError("update package size mismatch")
                digest.update(block)
            opened_after = os.fstat(handle.fileno())
            _regular_open_file(opened_after)
            after = _regular_file(path)
            if (
                _file_identity(opened_after) != _file_identity(opened)
                or _file_identity(after) != _file_identity(opened)
            ):
                raise UpdateSecurityError("update package changed during verification")
            if total != expected_size:
                raise UpdateSecurityError("update package size mismatch")
            if digest.hexdigest() != expected_digest:
                raise UpdateSecurityError("update package digest mismatch")

            handle.seek(0)
            yield handle
    except UpdateSecurityError:
        raise
    except OSError as exc:
        raise UpdateSecurityError("update package could not be read") from exc


@contextmanager
def open_verified_update(
    verified: VerifiedUpdate,
    *,
    now: datetime | None = None,
) -> Iterator[BinaryIO]:
    """Yield only the exact signed bytes still valid at consumption time.

    Future update installers must consume this retained read-only handle (or bytes
    derived from it), not reopen ``verified.package_path`` after verification.
    """
    if not isinstance(verified, VerifiedUpdate):
        raise TypeError("verified must be a VerifiedUpdate capability")
    instant = _require_utc_instant(now)
    if instant < verified.published_at:
        raise UpdateSecurityError("verified update is not yet valid")
    if instant > verified.expires_at:
        raise UpdateSecurityError("verified update is expired")
    with _verified_package_handle(
        verified.package_path,
        expected_size=verified.package_size,
        expected_digest=verified.package_sha256,
    ) as handle:
        yield handle


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
    install the candidate package on any exception from this function. A caller
    that later consumes package bytes must use :func:`open_verified_update` so
    pathname replacement after this function returns cannot bypass verification.
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
    instant = _require_utc_instant(now)
    if expires <= published or instant > expires:
        raise UpdateSecurityError("update metadata is expired")
    if published > instant:
        raise UpdateSecurityError("update metadata is not yet valid")

    package = Path(package_path)
    with _verified_package_handle(
        package,
        expected_size=package_size,
        expected_digest=digest,
    ):
        pass

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


__all__ = [
    "SignatureVerifier",
    "UpdateSecurityError",
    "VerifiedUpdate",
    "open_verified_update",
    "verify_update_package",
]
