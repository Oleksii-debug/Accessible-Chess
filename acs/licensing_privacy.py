from __future__ import annotations

"""Privacy boundary for licensing versus optional product telemetry.

Licensing is allowed to use only the metadata required by issue #11: account,
installation, session, application version and entitlement state. Chess data,
books, documents and arbitrary diagnostic payloads never enter this contract.
Optional analytics/diagnostics are a separate consent domain and are disabled by
default.
"""

from dataclasses import dataclass
from enum import Enum
import re
from typing import Mapping

from .entitlements import EntitlementState


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:@+-]{1,256}$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,127}$")
_ANALYTICS_FIELDS = frozenset({"event", "app_version", "platform", "locale"})


class LicensingPrivacyError(ValueError):
    """Raised when data would cross the licensing privacy boundary."""


class OptionalTelemetryConsent(str, Enum):
    DISABLED = "disabled"
    ENABLED = "enabled"


def _bounded_identifier(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise LicensingPrivacyError(f"{label} must be plain text")
    clean = value.strip()
    if not _IDENTIFIER_RE.fullmatch(clean):
        raise LicensingPrivacyError(f"{label} is invalid")
    return clean


def _version(value: object) -> str:
    if type(value) is not str:
        raise LicensingPrivacyError("app_version must be plain text")
    clean = value.strip()
    if not _VERSION_RE.fullmatch(clean):
        raise LicensingPrivacyError("app_version is invalid")
    return clean


def _entitlement_state(value: object) -> EntitlementState:
    if isinstance(value, EntitlementState):
        return value
    if type(value) is not str:
        raise LicensingPrivacyError("entitlement_state must be canonical entitlement state")
    try:
        return EntitlementState(value.strip().casefold())
    except ValueError as exc:
        raise LicensingPrivacyError("entitlement_state is unsupported") from exc


@dataclass(frozen=True, slots=True)
class LicensingMetadata:
    """Exact metadata that a licensing/policy request may expose."""

    account_id: str
    installation_id: str
    session_id: str
    app_version: str
    entitlement_state: EntitlementState | str

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_id", _bounded_identifier(self.account_id, label="account_id"))
        object.__setattr__(
            self,
            "installation_id",
            _bounded_identifier(self.installation_id, label="installation_id"),
        )
        object.__setattr__(self, "session_id", _bounded_identifier(self.session_id, label="session_id"))
        object.__setattr__(self, "app_version", _version(self.app_version))
        object.__setattr__(self, "entitlement_state", _entitlement_state(self.entitlement_state))

    def as_request_payload(self) -> dict[str, str]:
        """Return the complete and intentionally closed licensing payload."""

        return {
            "account_id": self.account_id,
            "installation_id": self.installation_id,
            "session_id": self.session_id,
            "app_version": self.app_version,
            "entitlement_state": self.entitlement_state.value,
        }


def build_licensing_payload(metadata: LicensingMetadata) -> dict[str, str]:
    if not isinstance(metadata, LicensingMetadata):
        raise LicensingPrivacyError("licensing payload requires LicensingMetadata")
    return metadata.as_request_payload()


def build_optional_telemetry_payload(
    values: Mapping[str, object],
    *,
    consent: OptionalTelemetryConsent = OptionalTelemetryConsent.DISABLED,
) -> dict[str, str] | None:
    """Build optional analytics only after explicit consent and strict allowlisting.

    Unknown fields fail closed instead of being silently forwarded. The analytics
    allowlist deliberately contains no account/session/installation identifiers
    and no chess/document content fields.
    """

    if not isinstance(consent, OptionalTelemetryConsent):
        raise LicensingPrivacyError("telemetry consent must be explicit")
    if consent is OptionalTelemetryConsent.DISABLED:
        return None
    if not isinstance(values, Mapping):
        raise LicensingPrivacyError("telemetry values must be a mapping")
    if any(type(key) is not str for key in values):
        raise LicensingPrivacyError("telemetry field names must be plain text")
    unknown = set(values) - _ANALYTICS_FIELDS
    if unknown:
        raise LicensingPrivacyError("telemetry contains non-allowlisted fields")
    payload: dict[str, str] = {}
    for key in sorted(values):
        value = values[key]
        if type(value) is not str:
            raise LicensingPrivacyError("telemetry fields must be plain text")
        clean = value.strip()
        if not clean or len(clean) > 256 or any(char in clean for char in "\r\n\x00"):
            raise LicensingPrivacyError("telemetry field value is invalid")
        payload[key] = clean
    return payload


def licensing_payload_keys() -> frozenset[str]:
    """Expose the closed boundary for architecture/release assertions."""

    return frozenset(
        {"account_id", "installation_id", "session_id", "app_version", "entitlement_state"}
    )
