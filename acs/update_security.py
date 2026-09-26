from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol, runtime_checkable
from urllib.parse import urlsplit

from acs.entitlements import ProductVersion


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_MANIFEST_KEYS = frozenset(
    {
        "version",
        "minimum_source_version",
        "payload_sha256",
        "payload_size",
        "download_url",
        "key_id",
        "signature",
    }
)


class UpdateDecisionCode(str, Enum):
    ACCEPT = "accept"
    INVALID_METADATA = "invalid_metadata"
    SIGNATURE_INVALID = "signature_invalid"
    ROLLBACK_BLOCKED = "rollback_blocked"
    SOURCE_TOO_OLD = "source_too_old"
    PAYLOAD_SIZE_MISMATCH = "payload_size_mismatch"
    PAYLOAD_HASH_MISMATCH = "payload_hash_mismatch"


@dataclass(frozen=True)
class UpdateDecision:
    allowed: bool
    code: UpdateDecisionCode
    reason: str


@runtime_checkable
class UpdateSignatureVerifier(Protocol):
    """Trust-store-backed verifier supplied by release infrastructure.

    Implementations own public-key algorithms and trust-anchor rotation. The
    application contract deliberately carries no signing private key and does
    not pretend that a checksum is a signature.
    """

    def verify(self, *, key_id: str, message: bytes, signature: str) -> bool:
        ...


@dataclass(frozen=True)
class UpdateManifest:
    """Strict metadata for one immutable update payload.

    The detached signature authenticates canonical metadata that binds the
    target version, source-version floor, payload digest/size and HTTPS URL.
    Payload bytes are independently checked against the signed digest and size
    before any future installer is permitted to consume them.
    """

    version: ProductVersion
    minimum_source_version: ProductVersion | None
    payload_sha256: str
    payload_size: int
    download_url: str
    key_id: str
    signature: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "UpdateManifest":
        keys = frozenset(value.keys())
        missing = _ALLOWED_MANIFEST_KEYS - keys
        unknown = keys - _ALLOWED_MANIFEST_KEYS
        if missing or unknown:
            parts: list[str] = []
            if missing:
                parts.append("missing=" + ",".join(sorted(missing)))
            if unknown:
                parts.append("unknown=" + ",".join(sorted(str(v) for v in unknown)))
            raise ValueError("invalid update manifest fields: " + " ".join(parts))

        raw_minimum = value["minimum_source_version"]
        minimum_source = (
            None
            if raw_minimum is None
            else ProductVersion.parse(_strict_text("minimum_source_version", raw_minimum))
        )
        payload_size = value["payload_size"]
        if isinstance(payload_size, bool) or not isinstance(payload_size, int):
            raise ValueError("payload_size must be an integer")

        manifest = cls(
            version=ProductVersion.parse(_strict_text("version", value["version"])),
            minimum_source_version=minimum_source,
            payload_sha256=_strict_text("payload_sha256", value["payload_sha256"]),
            payload_size=payload_size,
            download_url=_strict_text("download_url", value["download_url"]),
            key_id=_strict_text("key_id", value["key_id"]),
            signature=_strict_text("signature", value["signature"]),
        )
        manifest.validate()
        return manifest

    def validate(self) -> None:
        if self.payload_size <= 0:
            raise ValueError("payload_size must be positive")
        if not _SHA256_RE.fullmatch(self.payload_sha256):
            raise ValueError("payload_sha256 must be 64 lowercase hexadecimal characters")
        _validate_https_download_url(self.download_url)
        _validate_token("key_id", self.key_id, max_length=128)
        _validate_token("signature", self.signature, max_length=16384)

    def signed_bytes(self) -> bytes:
        """Return the one canonical byte representation covered by signature."""

        self.validate()
        body = {
            "download_url": self.download_url,
            "key_id": self.key_id,
            "minimum_source_version": (
                str(self.minimum_source_version)
                if self.minimum_source_version is not None
                else None
            ),
            "payload_sha256": self.payload_sha256,
            "payload_size": self.payload_size,
            "version": str(self.version),
        }
        return json.dumps(
            body,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")


def verify_update(
    manifest: UpdateManifest,
    *,
    current_version: ProductVersion | str,
    payload: bytes,
    signature_verifier: UpdateSignatureVerifier,
) -> UpdateDecision:
    """Fail closed unless metadata, signature, version and payload all agree.

    This function never downloads, writes, installs or executes the payload.
    Those actions belong to a future adapter that may proceed only after an
    ACCEPT decision and its own platform-specific safety checks.
    """

    try:
        manifest.validate()
        current = (
            current_version
            if isinstance(current_version, ProductVersion)
            else ProductVersion.parse(current_version)
        )
    except (TypeError, ValueError) as exc:
        return UpdateDecision(False, UpdateDecisionCode.INVALID_METADATA, str(exc))

    try:
        signature_ok = bool(
            signature_verifier.verify(
                key_id=manifest.key_id,
                message=manifest.signed_bytes(),
                signature=manifest.signature,
            )
        )
    except Exception:
        return UpdateDecision(
            False,
            UpdateDecisionCode.SIGNATURE_INVALID,
            "signature verifier failed closed",
        )
    if not signature_ok:
        return UpdateDecision(
            False,
            UpdateDecisionCode.SIGNATURE_INVALID,
            "update metadata signature was not accepted",
        )

    if manifest.version <= current:
        return UpdateDecision(
            False,
            UpdateDecisionCode.ROLLBACK_BLOCKED,
            "target version is not newer than installed version",
        )

    minimum = manifest.minimum_source_version
    if minimum is not None and current < minimum:
        return UpdateDecision(
            False,
            UpdateDecisionCode.SOURCE_TOO_OLD,
            "installed version is below this update's supported source floor",
        )

    if len(payload) != manifest.payload_size:
        return UpdateDecision(
            False,
            UpdateDecisionCode.PAYLOAD_SIZE_MISMATCH,
            "payload size does not match signed metadata",
        )

    actual_digest = hashlib.sha256(payload).hexdigest()
    if actual_digest != manifest.payload_sha256:
        return UpdateDecision(
            False,
            UpdateDecisionCode.PAYLOAD_HASH_MISMATCH,
            "payload SHA-256 does not match signed metadata",
        )

    return UpdateDecision(True, UpdateDecisionCode.ACCEPT, "verified update candidate")


def _strict_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    if value != value.strip() or not value:
        raise ValueError(f"{name} must be non-empty canonical text")
    return value


def _validate_token(name: str, value: str, *, max_length: int) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty canonical text")
    if len(value) > max_length:
        raise ValueError(f"{name} is too long")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ValueError(f"{name} contains control characters")


def _validate_https_download_url(value: str) -> None:
    if value != value.strip():
        raise ValueError("download_url must be canonical text")
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https":
        raise ValueError("download_url must use HTTPS")
    if not parsed.hostname:
        raise ValueError("download_url must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("download_url must not contain userinfo")
    if parsed.fragment:
        raise ValueError("download_url must not contain a fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("download_url contains an invalid port") from exc
    if port is not None and not (1 <= port <= 65535):
        raise ValueError("download_url contains an invalid port")
