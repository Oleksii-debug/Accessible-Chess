from __future__ import annotations

"""Public R28-R37 bridge to the private advanced protection runtime.

The public product exposes only product boundary identifiers and verified update
bytes. Capability classification, trusted local state, key hierarchy/rotation,
minimum-build policy and secure-update authority remain private-runtime concerns.
"""

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import BinaryIO
from urllib.parse import urlsplit

from .protection_boundary import (
    ADVANCED_SECURITY_RUNTIME_API_VERSION,
    ProtectionBoundaryError,
    ProtectionRuntimeClient,
)
from .release_update_center import StagedUpdate
from .protection_product_boundaries import boundaries_for_action, boundaries_for_surface

_BOUNDARY = re.compile(r"^[a-z0-9][a-z0-9._-]{2,95}$")
_REASON = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_ACTIONS = frozenset({
    "none",
    "login",
    "recover",
    "repair",
    "review_privacy",
    "open-secure-updater",
    "apply-trust-migration",
})
_LIVE = frozenset({"none", "polite", "assertive"})
_TRUST_STATES = frozenset({"trusted", "migration_required", "compromised", "unavailable"})
_MAX_METADATA = 1024 * 1024
_MAX_SIGNATURE = 16 * 1024 * 1024
_MAX_MESSAGE = 2 * 1024 * 1024


class ProtectionAdvancedError(ProtectionBoundaryError):
    pass


@dataclass(frozen=True)
class ProductBoundaryDecision:
    boundary_id: str
    authorized: bool
    reason: str
    live_region: str
    action: str


@dataclass(frozen=True)
class TrustStatus:
    state: str
    reason: str
    sequence: int
    live_region: str
    action: str


def _runtime_v4(client: ProtectionRuntimeClient):
    try:
        return client.runtime_extension(minimum_api_version=ADVANCED_SECURITY_RUNTIME_API_VERSION)
    except ProtectionBoundaryError as exc:
        raise ProtectionAdvancedError(str(exc)) from exc


def _action(value: object) -> str:
    if value not in _ACTIONS:
        raise ProtectionAdvancedError("private advanced action is invalid")
    return str(value)


def _live(value: object) -> str:
    if value not in _LIVE:
        raise ProtectionAdvancedError("private advanced live region is invalid")
    return str(value)


def _reason(value: object) -> str:
    if not isinstance(value, str) or _REASON.fullmatch(value) is None:
        raise ProtectionAdvancedError("private advanced reason is invalid")
    return value


class ProtectionCapabilityGate:
    """Independent authorization calls for distinct product service boundaries."""

    def __init__(self, client: ProtectionRuntimeClient) -> None:
        if not isinstance(client, ProtectionRuntimeClient):
            raise TypeError("client must be a ProtectionRuntimeClient")
        self.client = client

    def authorize(self, boundary_id: str) -> ProductBoundaryDecision:
        if not isinstance(boundary_id, str) or _BOUNDARY.fullmatch(boundary_id) is None:
            raise ProtectionAdvancedError("product boundary id is invalid")
        runtime = _runtime_v4(self.client)
        operation = getattr(runtime, "authorize_product_boundary", None)
        if not callable(operation):
            raise ProtectionAdvancedError("private product-boundary authorization is unavailable")
        try:
            value = operation(
                package_root=self.client.application_dir,
                state_root=self.client.state_root,
                boundary_id=boundary_id,
            )
        except Exception as exc:
            raise ProtectionAdvancedError("private product-boundary authorization failed") from exc
        if not isinstance(value, dict) or set(value) != {
            "api_version", "boundary_id", "authorized", "reason", "live_region", "action"
        }:
            raise ProtectionAdvancedError("private product-boundary schema is invalid")
        if value.get("api_version") != ADVANCED_SECURITY_RUNTIME_API_VERSION:
            raise ProtectionAdvancedError("private product-boundary API version is unsupported")
        if value.get("boundary_id") != boundary_id:
            raise ProtectionAdvancedError("private product-boundary identity mismatch")
        authorized = value.get("authorized")
        if not isinstance(authorized, bool):
            raise ProtectionAdvancedError("private product-boundary authorization is invalid")
        reason = _reason(value.get("reason"))
        live_region = _live(value.get("live_region"))
        action = _action(value.get("action"))
        if authorized:
            if reason != "none" or action != "none":
                raise ProtectionAdvancedError("authorized product-boundary result is inconsistent")
        else:
            if reason == "none" or live_region != "assertive":
                raise ProtectionAdvancedError("denied product-boundary result is inconsistent")
        return ProductBoundaryDecision(boundary_id, authorized, reason, live_region, action)

    def require(self, boundary_id: str) -> None:
        decision = self.authorize(boundary_id)
        if not decision.authorized:
            raise ProtectionAdvancedError(
                f"protected product boundary denied: {decision.reason}"
            )

    def require_many(self, boundary_ids: tuple[str, ...]) -> None:
        if type(boundary_ids) is not tuple or not boundary_ids:
            raise ProtectionAdvancedError("product boundary set is invalid")
        for boundary_id in boundary_ids:
            self.require(boundary_id)

    def require_surface(self, surface: str) -> None:
        self.require_many(boundaries_for_surface(surface))

    def require_action(self, action_id: str) -> None:
        boundary_ids = boundaries_for_action(action_id)
        for boundary_id in boundary_ids:
            self.require(boundary_id)


class ProtectionTrustBoundary:
    """Read/synchronize R31-R33 public trust state without exposing key material."""

    def __init__(self, client: ProtectionRuntimeClient) -> None:
        if not isinstance(client, ProtectionRuntimeClient):
            raise TypeError("client must be a ProtectionRuntimeClient")
        self.client = client

    def status(self) -> TrustStatus:
        runtime = _runtime_v4(self.client)
        operation = getattr(runtime, "read_trust_status", None)
        if not callable(operation):
            raise ProtectionAdvancedError("private trust-status operation is unavailable")
        try:
            value = operation(
                package_root=self.client.application_dir,
                state_root=self.client.state_root,
            )
        except Exception as exc:
            raise ProtectionAdvancedError("private trust-status operation failed") from exc
        required = {"api_version", "state", "reason", "sequence", "live_region", "action"}
        if not isinstance(value, dict) or set(value) != required:
            raise ProtectionAdvancedError("private trust-status schema is invalid")
        if value.get("api_version") != ADVANCED_SECURITY_RUNTIME_API_VERSION:
            raise ProtectionAdvancedError("private trust-status API version is unsupported")
        state = value.get("state")
        if state not in _TRUST_STATES:
            raise ProtectionAdvancedError("private trust state is invalid")
        sequence = value.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise ProtectionAdvancedError("private trust sequence is invalid")
        reason = _reason(value.get("reason"))
        live_region = _live(value.get("live_region"))
        action = _action(value.get("action"))
        if state == "trusted":
            if reason != "none" or action != "none":
                raise ProtectionAdvancedError("trusted state is inconsistent")
        else:
            if reason == "none" or live_region != "assertive":
                raise ProtectionAdvancedError("blocked trust state is inconsistent")
        return TrustStatus(state, reason, sequence, live_region, action)

    def synchronize(self) -> TrustStatus:
        runtime = _runtime_v4(self.client)
        operation = getattr(runtime, "synchronize_trust_state", None)
        if not callable(operation):
            raise ProtectionAdvancedError("private trust synchronization is unavailable")
        try:
            operation(
                package_root=self.client.application_dir,
                state_root=self.client.state_root,
            )
        except Exception as exc:
            raise ProtectionAdvancedError("private trust synchronization failed") from exc
        return self.status()


class ProtectionUpdateChannel:
    def __init__(self, client: ProtectionRuntimeClient) -> None:
        self.client = client

    def stage(self, *, current_version: str) -> StagedUpdate | None:
        runtime = _runtime_v4(self.client)
        operation = getattr(runtime, "stage_secure_update", None)
        if not callable(operation):
            raise ProtectionAdvancedError("private secure-update channel is unavailable")
        try:
            value = operation(
                package_root=self.client.application_dir,
                state_root=self.client.state_root,
                current_version=current_version,
            )
        except Exception as exc:
            raise ProtectionAdvancedError("private secure-update staging failed") from exc
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != {
            "api_version", "metadata_utf8", "package_path", "source_url"
        }:
            raise ProtectionAdvancedError("private secure-update staging schema is invalid")
        if value.get("api_version") != ADVANCED_SECURITY_RUNTIME_API_VERSION:
            raise ProtectionAdvancedError("private secure-update API version is unsupported")
        metadata = value.get("metadata_utf8")
        if not isinstance(metadata, str):
            raise ProtectionAdvancedError("private secure-update metadata is invalid")
        encoded = metadata.encode("utf-8", errors="strict")
        if not encoded or len(encoded) > _MAX_METADATA:
            raise ProtectionAdvancedError("private secure-update metadata is invalid")
        package = self._staged_path(value.get("package_path"))
        source_url = self._source_url(value.get("source_url"))
        return StagedUpdate(metadata=encoded, package_path=package, source_url=source_url)

    def _staged_path(self, value: object) -> Path:
        if not isinstance(value, str) or not value:
            raise ProtectionAdvancedError("private secure-update package path is invalid")
        root = (self.client.state_root / "security-updates").resolve()
        path = Path(value).expanduser().resolve()
        try:
            path.relative_to(root)
        except ValueError:
            raise ProtectionAdvancedError("private secure-update package escaped staging root") from None
        try:
            info = path.lstat()
        except OSError as exc:
            raise ProtectionAdvancedError("private secure-update package is unavailable") from exc
        if path.is_symlink() or not stat.S_ISREG(info.st_mode):
            raise ProtectionAdvancedError("private secure-update package is unsafe")
        return path

    @staticmethod
    def _source_url(value: object) -> str:
        if not isinstance(value, str) or len(value) > 4096:
            raise ProtectionAdvancedError("private secure-update source URL is invalid")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ProtectionAdvancedError("private secure-update source URL is unsafe")
        return value


class ProtectionUpdateSignatureVerifier:
    def __init__(self, client: ProtectionRuntimeClient) -> None:
        self.client = client

    def verify(self, *, key_id: str, message: bytes, signature: bytes) -> bool:
        if not isinstance(key_id, str) or not key_id or len(key_id) > 128:
            return False
        if not isinstance(message, bytes) or not message or len(message) > _MAX_MESSAGE:
            return False
        if not isinstance(signature, bytes) or not signature or len(signature) > _MAX_SIGNATURE:
            return False
        runtime = _runtime_v4(self.client)
        operation = getattr(runtime, "verify_update_signature", None)
        if not callable(operation):
            return False
        try:
            value = operation(
                package_root=self.client.application_dir,
                state_root=self.client.state_root,
                key_id=key_id,
                message=message,
                signature=signature,
            )
        except Exception:
            return False
        return value is True


class ProtectionTrustedTimeSource:
    def __init__(self, client: ProtectionRuntimeClient) -> None:
        self.client = client

    def utc_now(self) -> datetime:
        runtime = _runtime_v4(self.client)
        operation = getattr(runtime, "trusted_update_time", None)
        if not callable(operation):
            raise ProtectionAdvancedError("private trusted update time is unavailable")
        try:
            value = operation(
                package_root=self.client.application_dir,
                state_root=self.client.state_root,
            )
        except Exception as exc:
            raise ProtectionAdvancedError("private trusted update time failed") from exc
        if not isinstance(value, str) or not value.endswith("Z"):
            raise ProtectionAdvancedError("private trusted update time is invalid")
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError as exc:
            raise ProtectionAdvancedError("private trusted update time is invalid") from exc
        if parsed.tzinfo != timezone.utc or parsed.microsecond:
            raise ProtectionAdvancedError("private trusted update time is invalid")
        return parsed


class ProtectionUpdateInstaller:
    """Pass already verified bytes to the private R34-R37 installer for revalidation."""

    def __init__(self, client: ProtectionRuntimeClient) -> None:
        self.client = client

    def install(self, *, version: str, stream: BinaryIO) -> bool:
        if not isinstance(version, str) or not version:
            return False
        read = getattr(stream, "read", None)
        if not callable(read):
            return False
        runtime = _runtime_v4(self.client)
        operation = getattr(runtime, "install_verified_update_handoff", None)
        if not callable(operation):
            return False
        root = self.client.state_root / "security-updates" / "handoff"
        root.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="verified-", suffix=".package", dir=root)
        path = Path(name)
        try:
            total = 0
            with os.fdopen(fd, "wb", closefd=True) as output:
                while True:
                    block = read(1024 * 1024)
                    if not block:
                        break
                    if not isinstance(block, (bytes, bytearray)):
                        return False
                    total += len(block)
                    if total > 16 * 1024 * 1024 * 1024:
                        return False
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            try:
                result = operation(
                    package_root=self.client.application_dir,
                    state_root=self.client.state_root,
                    version=version,
                    verified_handoff_path=path,
                )
            except Exception:
                return False
            return result is True
        finally:
            with suppress(OSError):
                path.unlink()


__all__ = [
    "ProductBoundaryDecision",
    "ProtectionAdvancedError",
    "ProtectionCapabilityGate",
    "ProtectionTrustBoundary",
    "ProtectionTrustedTimeSource",
    "ProtectionUpdateChannel",
    "ProtectionUpdateInstaller",
    "ProtectionUpdateSignatureVerifier",
    "TrustStatus",
]
