from __future__ import annotations

"""Privacy/consent boundary for the R24 security-telemetry contract."""

import re

from .protection_boundary import (
    ADVANCED_SECURITY_RUNTIME_API_VERSION,
    ENTITLEMENT_RUNTIME_API_VERSION,
    ProtectionBoundaryError,
    ProtectionRuntimeClient,
)

_NOTICE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_MAX_SUMMARY = 2000


class ProtectionPrivacyError(ProtectionBoundaryError):
    pass


def _validate_notice(value: object) -> dict[str, object]:
    required = {
        "api_version",
        "notice_version",
        "summary",
        "consent_required",
        "consent_granted",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ProtectionPrivacyError("private security notice schema is invalid")
    if value.get("api_version") != ENTITLEMENT_RUNTIME_API_VERSION:
        raise ProtectionPrivacyError("private security notice API version is unsupported")
    version = value.get("notice_version")
    summary = value.get("summary")
    required_consent = value.get("consent_required")
    granted = value.get("consent_granted")
    if not isinstance(version, str) or not _NOTICE_VERSION.fullmatch(version):
        raise ProtectionPrivacyError("private security notice version is invalid")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > _MAX_SUMMARY:
        raise ProtectionPrivacyError("private security notice summary is invalid")
    if not isinstance(required_consent, bool) or not isinstance(granted, bool):
        raise ProtectionPrivacyError("private security consent state is invalid")
    return {
        "notice_version": version,
        "summary": summary,
        "consent_required": required_consent,
        "consent_granted": granted,
    }


class ProtectionPrivacyClient:
    """Expose only notice/consent state; telemetry payloads never cross this boundary."""

    def __init__(self, client: ProtectionRuntimeClient) -> None:
        if not isinstance(client, ProtectionRuntimeClient):
            raise TypeError("client must be a ProtectionRuntimeClient")
        self.client = client

    def _require_privacy_foundation(self) -> None:
        if self.client.runtime_api_version() < ADVANCED_SECURITY_RUNTIME_API_VERSION:
            return
        from .protection_advanced_boundary import ProtectionCapabilityGate
        ProtectionCapabilityGate(self.client).require("BND.AC-S29-PRIVACY-FOUNDATION")

    def notice(self) -> dict[str, object]:
        self._require_privacy_foundation()
        try:
            runtime = self.client.runtime_extension(
                minimum_api_version=ENTITLEMENT_RUNTIME_API_VERSION
            )
        except ProtectionBoundaryError as exc:
            raise ProtectionPrivacyError(str(exc)) from exc
        operation = getattr(runtime, "security_notice", None)
        if not callable(operation):
            raise ProtectionPrivacyError("private security notice operation is unavailable")
        try:
            value = operation(
                package_root=self.client.application_dir,
                state_root=self.client.state_root,
            )
        except Exception as exc:
            raise ProtectionPrivacyError("private security notice could not be read") from exc
        return _validate_notice(value)

    def set_consent(self, *, granted: bool, notice_version: str) -> dict[str, object]:
        self._require_privacy_foundation()
        if not isinstance(granted, bool):
            raise TypeError("granted must be bool")
        if not isinstance(notice_version, str) or not _NOTICE_VERSION.fullmatch(notice_version):
            raise ProtectionPrivacyError("security notice version is invalid")
        try:
            runtime = self.client.runtime_extension(
                minimum_api_version=ENTITLEMENT_RUNTIME_API_VERSION
            )
        except ProtectionBoundaryError as exc:
            raise ProtectionPrivacyError(str(exc)) from exc
        operation = getattr(runtime, "set_security_consent", None)
        if not callable(operation):
            raise ProtectionPrivacyError("private security consent operation is unavailable")
        try:
            value = operation(
                package_root=self.client.application_dir,
                state_root=self.client.state_root,
                notice_version=notice_version,
                granted=granted,
            )
        except Exception as exc:
            raise ProtectionPrivacyError("private security consent update failed") from exc
        return _validate_notice(value)


__all__ = ["ProtectionPrivacyClient", "ProtectionPrivacyError"]
