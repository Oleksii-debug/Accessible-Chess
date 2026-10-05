"""Fail-closed verification for locally supplied Accessible Chess updates.

Adapted from first-party donor:
Oleksii-debug/scripture-archive
qa-current-package-accessibility-0913-sol
runtime_engine/scripture_archive_runtime/application_update.py
blob 4d621a3013df7f50984906fcdb59ffe6b6ae98f7

This module deliberately does not download, execute, unpack, install, or replace
an application package. It verifies a versioned manifest and exact artifact
identity so a separately qualified Windows host may stage replacement later.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping


UPDATE_MANIFEST_SCHEMA = "accessible-chess.application-update.v1"
DEFAULT_PRODUCT_ID = "accessible-chess"
DEFAULT_PLATFORM = "windows-x64"
MAX_UPDATE_BYTES = 4 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_HEAD_RE = re.compile(r"^[0-9a-f]{40}$")
_ARTIFACT_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$")
_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_REQUIRED_KEYS = frozenset(
    {
        "schema",
        "product_id",
        "target_platform",
        "target_version",
        "source_head",
        "artifact_name",
        "artifact_size",
        "artifact_sha256",
    }
)


class ApplicationUpdateError(ValueError):
    """Raised when update metadata or artifact evidence fails closed."""


@dataclass(frozen=True, slots=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> "SemVer":
        if type(value) is not str:
            raise ApplicationUpdateError("version must be exact text")
        match = _SEMVER_RE.fullmatch(value)
        if match is None:
            raise ApplicationUpdateError(f"invalid semantic version: {value!r}")
        return cls(
            major=int(match.group(1)),
            minor=int(match.group(2)),
            patch=int(match.group(3)),
            prerelease=tuple(match.group(4).split(".")) if match.group(4) else (),
        )

    def compare_precedence(self, other: "SemVer") -> int:
        if type(other) is not SemVer:
            raise TypeError("other must be an exact SemVer")
        left_core = (self.major, self.minor, self.patch)
        right_core = (other.major, other.minor, other.patch)
        if left_core != right_core:
            return -1 if left_core < right_core else 1
        if not self.prerelease and not other.prerelease:
            return 0
        if not self.prerelease:
            return 1
        if not other.prerelease:
            return -1
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            left_numeric = left.isdigit()
            right_numeric = right.isdigit()
            if left_numeric and right_numeric:
                return -1 if int(left) < int(right) else 1
            if left_numeric != right_numeric:
                return -1 if left_numeric else 1
            return -1 if left < right else 1
        if len(self.prerelease) == len(other.prerelease):
            return 0
        return -1 if len(self.prerelease) < len(other.prerelease) else 1


@dataclass(frozen=True, slots=True)
class ApplicationUpdateManifest:
    product_id: str
    target_platform: str
    target_version: str
    source_head: str
    artifact_name: str
    artifact_size: int
    artifact_sha256: str
    schema: str = UPDATE_MANIFEST_SCHEMA

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ApplicationUpdateManifest":
        if type(raw) is not dict:
            raise ApplicationUpdateError(
                "update manifest must be an exact passive object"
            )
        if any(type(key) is not str for key in raw):
            raise ApplicationUpdateError("manifest keys must be exact text")
        keys = frozenset(raw.keys())
        if keys != _REQUIRED_KEYS:
            missing = sorted(_REQUIRED_KEYS - keys)
            extra = sorted(keys - _REQUIRED_KEYS)
            raise ApplicationUpdateError(
                f"manifest keys mismatch: missing={missing}, extra={extra}"
            )
        schema = _bounded_token(raw["schema"], "schema", 64)
        if schema != UPDATE_MANIFEST_SCHEMA:
            raise ApplicationUpdateError("unsupported update manifest schema")

        product_id = _bounded_token(raw["product_id"], "product_id", 64)
        target_platform = _bounded_token(raw["target_platform"], "target_platform", 32)
        target_version = _bounded_token(raw["target_version"], "target_version", 128)
        SemVer.parse(target_version)
        source_head = _bounded_token(raw["source_head"], "source_head", 40)
        if _HEAD_RE.fullmatch(source_head) is None:
            raise ApplicationUpdateError(
                "source_head must be a lowercase 40-hex commit SHA"
            )
        artifact_name = _validate_artifact_name(raw["artifact_name"])
        artifact_size = raw["artifact_size"]
        if type(artifact_size) is not int:
            raise ApplicationUpdateError("artifact_size must be an exact integer")
        if artifact_size <= 0 or artifact_size > MAX_UPDATE_BYTES:
            raise ApplicationUpdateError("artifact_size is outside the allowed range")
        artifact_sha256 = _bounded_token(
            raw["artifact_sha256"], "artifact_sha256", 64
        )
        if _HASH_RE.fullmatch(artifact_sha256) is None:
            raise ApplicationUpdateError(
                "artifact_sha256 must be lowercase SHA-256 hex"
            )
        return cls(
            product_id=product_id,
            target_platform=target_platform,
            target_version=target_version,
            source_head=source_head,
            artifact_name=artifact_name,
            artifact_size=artifact_size,
            artifact_sha256=artifact_sha256,
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> "ApplicationUpdateManifest":
        if isinstance(payload, bytes):
            try:
                payload = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ApplicationUpdateError("manifest must be UTF-8") from exc
        if not isinstance(payload, str):
            raise ApplicationUpdateError(
                "manifest payload must be text or UTF-8 bytes"
            )
        try:
            encoded = payload.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ApplicationUpdateError(
                "manifest must be valid UTF-8 text"
            ) from exc
        if len(encoded) > MAX_MANIFEST_BYTES:
            raise ApplicationUpdateError("manifest exceeds size limit")
        try:
            raw = json.loads(
                payload,
                object_pairs_hook=_strict_json_object,
                parse_constant=_reject_nonfinite,
            )
        except ApplicationUpdateError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ApplicationUpdateError("manifest is not valid JSON") from exc
        return cls.from_mapping(raw)


@dataclass(frozen=True, slots=True)
class VerifiedApplicationUpdate:
    product_id: str
    target_platform: str
    current_version: str
    target_version: str
    source_head: str
    artifact_name: str
    artifact_size: int
    artifact_sha256: str


def verify_artifact_bytes(
    manifest: ApplicationUpdateManifest,
    artifact: bytes | bytearray | memoryview,
    *,
    current_version: str,
    expected_product_id: str = DEFAULT_PRODUCT_ID,
    expected_platform: str = DEFAULT_PLATFORM,
    allow_downgrade: bool = False,
) -> VerifiedApplicationUpdate:
    manifest = _validated_manifest(manifest)
    _validate_target(
        manifest,
        current_version,
        expected_product_id,
        expected_platform,
        allow_downgrade,
    )
    if type(artifact) not in (bytes, bytearray, memoryview):
        raise ApplicationUpdateError(
            "artifact must be exact bytes, bytearray, or memoryview"
        )
    try:
        view = memoryview(artifact)
    except (TypeError, ValueError) as exc:
        raise ApplicationUpdateError("artifact must be a readable byte buffer") from exc
    if view.nbytes != manifest.artifact_size:
        raise ApplicationUpdateError("artifact size does not match manifest")
    digest = hashlib.sha256(view).hexdigest()
    if digest != manifest.artifact_sha256:
        raise ApplicationUpdateError("artifact SHA-256 does not match manifest")
    return _verified(manifest, current_version)


def verify_local_update(
    manifest: ApplicationUpdateManifest,
    artifact_path: str | os.PathLike[str],
    *,
    current_version: str,
    expected_product_id: str = DEFAULT_PRODUCT_ID,
    expected_platform: str = DEFAULT_PLATFORM,
    allow_downgrade: bool = False,
) -> VerifiedApplicationUpdate:
    """Verify one local regular file without unpacking or executing it."""

    manifest = _validated_manifest(manifest)
    _validate_target(
        manifest,
        current_version,
        expected_product_id,
        expected_platform,
        allow_downgrade,
    )
    if type(artifact_path) not in (str, type(Path())):
        raise ApplicationUpdateError(
            "artifact_path must be exact text or a concrete Path"
        )
    path = Path(artifact_path)
    if path.name != manifest.artifact_name:
        raise ApplicationUpdateError("local artifact name does not match manifest")
    try:
        before = path.lstat()
    except OSError as exc:
        raise ApplicationUpdateError("local artifact is not readable") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ApplicationUpdateError(
            "local artifact must be a regular non-symlink file"
        )
    if before.st_size != manifest.artifact_size:
        raise ApplicationUpdateError("artifact size does not match manifest")

    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > manifest.artifact_size:
                    raise ApplicationUpdateError(
                        "artifact grew during verification"
                    )
                digest.update(chunk)
        after = path.lstat()
    except ApplicationUpdateError:
        raise
    except OSError as exc:
        raise ApplicationUpdateError(
            "local artifact could not be verified"
        ) from exc

    if stat.S_ISLNK(after.st_mode) or not stat.S_ISREG(after.st_mode):
        raise ApplicationUpdateError("local artifact type changed during verification")
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if before_identity != after_identity or total != manifest.artifact_size:
        raise ApplicationUpdateError("local artifact changed during verification")
    if digest.hexdigest() != manifest.artifact_sha256:
        raise ApplicationUpdateError("artifact SHA-256 does not match manifest")
    return _verified(manifest, current_version)


def _validated_manifest(
    manifest: ApplicationUpdateManifest,
) -> ApplicationUpdateManifest:
    if type(manifest) is not ApplicationUpdateManifest:
        raise ApplicationUpdateError(
            "manifest must be an exact ApplicationUpdateManifest"
        )
    return ApplicationUpdateManifest.from_mapping(
        {
            "schema": manifest.schema,
            "product_id": manifest.product_id,
            "target_platform": manifest.target_platform,
            "target_version": manifest.target_version,
            "source_head": manifest.source_head,
            "artifact_name": manifest.artifact_name,
            "artifact_size": manifest.artifact_size,
            "artifact_sha256": manifest.artifact_sha256,
        }
    )


def _validate_target(
    manifest: ApplicationUpdateManifest,
    current_version: str,
    expected_product_id: str,
    expected_platform: str,
    allow_downgrade: bool,
) -> None:
    if type(allow_downgrade) is not bool:
        raise ApplicationUpdateError("allow_downgrade must be an exact boolean")
    expected_product_id = _bounded_token(
        expected_product_id, "expected_product_id", 64
    )
    expected_platform = _bounded_token(
        expected_platform, "expected_platform", 32
    )
    if manifest.product_id != expected_product_id:
        raise ApplicationUpdateError("update targets a different product")
    if manifest.target_platform != expected_platform:
        raise ApplicationUpdateError("update targets a different platform")
    current = SemVer.parse(current_version)
    target = SemVer.parse(manifest.target_version)
    precedence = target.compare_precedence(current)
    if precedence == 0:
        raise ApplicationUpdateError(
            "target version is not newer than current version"
        )
    if precedence < 0 and not allow_downgrade:
        raise ApplicationUpdateError("downgrade is not allowed")


def _verified(
    manifest: ApplicationUpdateManifest,
    current_version: str,
) -> VerifiedApplicationUpdate:
    return VerifiedApplicationUpdate(
        product_id=manifest.product_id,
        target_platform=manifest.target_platform,
        current_version=current_version,
        target_version=manifest.target_version,
        source_head=manifest.source_head,
        artifact_name=manifest.artifact_name,
        artifact_size=manifest.artifact_size,
        artifact_sha256=manifest.artifact_sha256,
    )


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ApplicationUpdateError(
                f"manifest contains duplicate key: {key}"
            )
        out[key] = value
    return out


def _reject_nonfinite(value: str) -> None:
    raise ApplicationUpdateError(
        f"manifest contains non-finite JSON constant: {value}"
    )


def _bounded_token(value: Any, field: str, maximum: int) -> str:
    if type(value) is not str:
        raise ApplicationUpdateError(f"{field} must be exact text")
    if not value or len(value) > maximum or value != value.strip():
        raise ApplicationUpdateError(
            f"{field} is empty, padded, or too long"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ApplicationUpdateError(
            f"{field} contains control characters"
        )
    return value


def _validate_artifact_name(value: Any) -> str:
    name = _bounded_token(value, "artifact_name", 128)
    if _ARTIFACT_RE.fullmatch(name) is None:
        raise ApplicationUpdateError(
            "artifact_name must be a safe portable file name"
        )
    if name in {".", ".."} or name.endswith((".", " ")):
        raise ApplicationUpdateError(
            "artifact_name has unsafe Windows path semantics"
        )
    stem = name.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        raise ApplicationUpdateError(
            "artifact_name uses a reserved Windows device name"
        )
    return name


__all__ = [
    "ApplicationUpdateError",
    "ApplicationUpdateManifest",
    "DEFAULT_PLATFORM",
    "DEFAULT_PRODUCT_ID",
    "MAX_MANIFEST_BYTES",
    "MAX_UPDATE_BYTES",
    "SemVer",
    "UPDATE_MANIFEST_SCHEMA",
    "VerifiedApplicationUpdate",
    "verify_artifact_bytes",
    "verify_local_update",
]
