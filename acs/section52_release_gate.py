"""One fail-closed decision over the Section 52 release evidence chain."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Mapping
from urllib.parse import urlsplit


_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_UPDATE_ACTIONS = frozenset({"release.status", "release.check_update", "release.apply_update"})


class ReleaseAudience(str, Enum):
    TEST_BUILD = "TEST_BUILD"
    PUBLIC_RELEASE = "PUBLIC_RELEASE"


class Section52ReleaseError(ValueError):
    """Evidence is incomplete, inconsistent or unsafe for promotion."""


@dataclass(frozen=True)
class ReleaseGateInput:
    audience: ReleaseAudience
    source_sha: str
    package_sha256: str
    sbom_package_sha256: str
    provenance_package_sha256: str
    preflight_passed: bool
    receipt_verified: bool
    authenticode_valid: bool
    timestamped: bool
    license_manifest_complete: bool
    corpus_kind: str
    credentials_embedded: bool
    support_url: str
    update_actions: frozenset[str]
    clean_windows_launch: bool = False
    owner_nvda_accepted: bool = False


def _https(value: object) -> str:
    if type(value) is not str or value != value.strip() or not value or len(value) > 2048:
        raise Section52ReleaseError("support URL is invalid")
    if "\\" in value or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise Section52ReleaseError("support URL is invalid")
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise Section52ReleaseError("support URL is invalid") from None
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise Section52ReleaseError("support URL is invalid")
    return value


def qualify_release(evidence: ReleaseGateInput) -> dict[str, Any]:
    """Bind package identity to every required release fact.

    A green repository gate is not itself permission to publish: physical clean
    Windows launch and owner NVDA acceptance are reported separately.
    """
    if type(evidence) is not ReleaseGateInput or type(evidence.audience) is not ReleaseAudience:
        raise Section52ReleaseError("release evidence has an invalid type")
    if not _SHA40.fullmatch(evidence.source_sha):
        raise Section52ReleaseError("source SHA is invalid")
    for value in (evidence.package_sha256, evidence.sbom_package_sha256, evidence.provenance_package_sha256):
        if type(value) is not str or not _SHA256.fullmatch(value):
            raise Section52ReleaseError("artifact SHA-256 is invalid")
    if len({evidence.package_sha256, evidence.sbom_package_sha256, evidence.provenance_package_sha256}) != 1:
        raise Section52ReleaseError("package, SBOM and provenance identities differ")
    for field in ("preflight_passed", "receipt_verified", "authenticode_valid", "timestamped", "license_manifest_complete", "credentials_embedded", "clean_windows_launch", "owner_nvda_accepted"):
        if type(getattr(evidence, field)) is not bool:
            raise Section52ReleaseError("release verdicts must be exact booleans")
    required_true = (evidence.preflight_passed, evidence.receipt_verified, evidence.authenticode_valid, evidence.timestamped, evidence.license_manifest_complete)
    if not all(required_true) or evidence.credentials_embedded:
        raise Section52ReleaseError("release evidence chain is incomplete")
    if evidence.corpus_kind != evidence.audience.value:
        raise Section52ReleaseError("release audience and corpus policy differ")
    if type(evidence.update_actions) is not frozenset or evidence.update_actions != REQUIRED_UPDATE_ACTIONS:
        raise Section52ReleaseError("accessible update action surface is incomplete")
    support_url = _https(evidence.support_url)
    promotion = evidence.clean_windows_launch and evidence.owner_nvda_accepted
    return {
        "schema": "accessible-chess.section52-release-gate.v1",
        "source_sha": evidence.source_sha,
        "package_sha256": evidence.package_sha256,
        "audience": evidence.audience.value,
        "repository_gate": "PASS",
        "support_url": support_url,
        "update_actions": sorted(evidence.update_actions),
        "physical_acceptance": "PASS" if promotion else "EXTERNAL_NOT_PERFORMED",
        "publication_authorized": promotion,
    }


__all__ = ["ReleaseAudience", "ReleaseGateInput", "Section52ReleaseError", "qualify_release"]
