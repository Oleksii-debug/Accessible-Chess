"""R52 narrow product boundary for private verified license-container selection.

This bridge NEVER selects machine/cloud/hardware/enterprise from a browser or
user-owned setting. It delegates to the existing private license-container R52
and canonical R08/R45/R29 authorities, passing only the verified build context.
A transport receipt is not authorization. No silent medium fallback is allowed.
"""
from __future__ import annotations

import re
from .protection_boundary import (
    HARDENED_SECURITY_RUNTIME_API_VERSION,
    ProtectionBoundaryError, ProtectionRuntimeClient,
)

_REASON = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class ProductLicenseContainerDenied(ProtectionBoundaryError):
    pass


def require_private_license_container(client: ProtectionRuntimeClient, *, build_id: str) -> None:
    if type(client) is not ProtectionRuntimeClient:
        raise TypeError("client must be ProtectionRuntimeClient")
    if (type(build_id) is not str or not build_id or len(build_id) > 256
            or any(c.isspace() for c in build_id)):
        raise ProductLicenseContainerDenied("license container build identity is invalid")
    try:
        runtime = client.runtime_extension(
            minimum_api_version=HARDENED_SECURITY_RUNTIME_API_VERSION
        )
        verify = getattr(runtime, "verify_license_container", None)
    except Exception:
        raise ProductLicenseContainerDenied("private license container unavailable") from None
    if not callable(verify):
        raise ProductLicenseContainerDenied("private license container unavailable")
    try:
        decision = verify(
            package_root=client.application_dir,
            state_root=client.state_root,
            build_id=build_id,
        )
    except Exception:
        raise ProductLicenseContainerDenied("private license container verification failed") from None
    if (type(decision) is not dict
        or set(decision) != {"api_version", "build_id", "authorized", "reason"}
        or type(decision["api_version"]) is not int
        or decision["api_version"] != HARDENED_SECURITY_RUNTIME_API_VERSION
        or type(decision["build_id"]) is not str
        or decision["build_id"] != build_id
        or type(decision["authorized"]) is not bool
        or type(decision["reason"]) is not str
        or _REASON.fullmatch(decision["reason"]) is None):
        raise ProductLicenseContainerDenied("private license container receipt invalid")
    if decision["authorized"] is not True:
        raise ProductLicenseContainerDenied("private license container denied")
    if decision["reason"] != "none":
        raise ProductLicenseContainerDenied("private license container allowance inconsistent")
