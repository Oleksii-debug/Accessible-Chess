from __future__ import annotations

"""Narrow public-client R42/R44-R50 boundary; implementation remains private.

The client cannot mint, refresh, or independently validate an entitlement,
device attestation, TPM proof, or protected-resource key. It asks the private
runtime to verify each independent release check before product composition.
A local success receipt is NEVER a server-side premium authorization.
"""

import re

from .protection_boundary import (
    HARDENED_SECURITY_RUNTIME_API_VERSION,
    ProtectionBoundaryError,
    ProtectionRuntimeClient,
)

# Deliberately no check can be inferred from another check's success.
# R41 is a private design inventory; R43 belongs to the build/release gate.
REQUIRED_HARDENED_CHECKS = (
    "native-runtime-integrity",  # R42
    "protected-resource-integrity",  # R44
    "hardened-license-binding",  # R45
    "device-key-binding",  # R46
    "hardware-assurance-policy",  # R47 (explicit fallback policy is private)
    "proof-of-possession",  # R48
    "device-health-policy",  # R49 (optional only when policy allows)
    "clone-resistance-policy",  # R50
)
_REASON = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class ProtectionHardenedError(ProtectionBoundaryError):
    """A higher-assurance private verification check was denied or unavailable."""


class HardenedReleaseBoundary:
    def __init__(self, client: ProtectionRuntimeClient) -> None:
        if not isinstance(client, ProtectionRuntimeClient):
            raise TypeError("client must be ProtectionRuntimeClient")
        self.client = client

    def require_all(self, *, build_id: str) -> None:
        if (type(build_id) is not str or not build_id
                or len(build_id) > 256 or any(c.isspace() for c in build_id)):
            raise ProtectionHardenedError("hardened release build is invalid")
        try:
            runtime = self.client.runtime_extension(
                minimum_api_version=HARDENED_SECURITY_RUNTIME_API_VERSION
            )
            verify = getattr(runtime, "verify_hardened_release_check", None)
        except Exception:
            raise ProtectionHardenedError("private hardened runtime unavailable") from None
        if not callable(verify):
            raise ProtectionHardenedError("private hardened verifier unavailable")
        for check_id in REQUIRED_HARDENED_CHECKS:
            try:
                receipt = verify(
                    package_root=self.client.application_dir,
                    state_root=self.client.state_root,
                    check_id=check_id,
                    build_id=build_id,
                )
            except Exception:
                # Do not propagate provider data, endpoint names, secrets or tracebacks.
                raise ProtectionHardenedError("private hardened verification failed") from None
            if type(receipt) is not dict or set(receipt) != {
                "api_version", "check_id", "build_id", "authorized", "reason"
            }:
                raise ProtectionHardenedError("private hardened receipt schema invalid")
            if (type(receipt["api_version"]) is not int
                    or receipt["api_version"] != HARDENED_SECURITY_RUNTIME_API_VERSION
                    or type(receipt["check_id"]) is not str
                    or receipt["check_id"] != check_id
                    or type(receipt["build_id"]) is not str
                    or receipt["build_id"] != build_id
                    or type(receipt["authorized"]) is not bool
                    or type(receipt["reason"]) is not str
                    or _REASON.fullmatch(receipt["reason"]) is None):
                raise ProtectionHardenedError("private hardened receipt invalid")
            if receipt["authorized"] is not True:
                raise ProtectionHardenedError("hardened check denied: " + receipt["reason"])
            if receipt["reason"] != "none":
                raise ProtectionHardenedError("authorized hardened receipt inconsistent")


__all__ = [
    "HardenedReleaseBoundary",
    "ProtectionHardenedError",
    "REQUIRED_HARDENED_CHECKS",
]
