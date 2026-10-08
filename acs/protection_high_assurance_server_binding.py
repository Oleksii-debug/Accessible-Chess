"""R66: optional high-assurance admission before the ONE canonical R65 guard.

Server-only composition. No client-supplied hardware, license, provider, session,
device or evidence values are trusted. No issuer or release authority is added.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Callable

from continuum_runtime.high_assurance import AssuranceEvidence, OptionalHighAssurance
from .server_application_boundary import ApiRequest, AuthenticatedPrincipal
from .protection_paid_server_binding import CanonicalPaidOperationCallback

_OP = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class TrustedAssuranceContext:
    """Only trusted server middleware may resolve these fields, never JSON."""
    candidate_id: str
    build_sha256: str
    evidence: AssuranceEvidence
    now: datetime
    baseline_authorized: bool


class CanonicalHighAssurancePaidCallback:
    """Opt-in for a specific R66-required sensitive R65 server operation.

    R66's independent verifier is additive; a positive R66 decision is not a
    payment/entitlement decision. R65 reserves the actual effect afterwards.
    Class-C safety routes must use their original independent authority.
    """

    def __init__(
        self, *, operation_id: str, assurance: OptionalHighAssurance,
        trusted_context: Callable[[AuthenticatedPrincipal, ApiRequest], TrustedAssuranceContext],
        paid_callback: CanonicalPaidOperationCallback,
    ) -> None:
        if (type(operation_id) is not str or _OP.fullmatch(operation_id) is None
                or type(assurance) is not OptionalHighAssurance
                or not callable(trusted_context)
                or type(paid_callback) is not CanonicalPaidOperationCallback):
            raise ValueError("R66_TRUSTED_AUTHORITY_NOT_CONFIGURED")
        self._operation = operation_id
        self._assurance = assurance
        self._context = trusted_context
        self._paid = paid_callback

    def __call__(self, principal: AuthenticatedPrincipal, request: ApiRequest) -> bool:
        if (type(principal) is not AuthenticatedPrincipal
                or type(request) is not ApiRequest
                or request.operation != self._operation):
            return False
        try:
            ctx = self._context(principal, request)
            if (type(ctx) is not TrustedAssuranceContext
                    or type(ctx.candidate_id) is not str
                    or _ID.fullmatch(ctx.candidate_id) is None
                    or type(ctx.build_sha256) is not str
                    or _SHA.fullmatch(ctx.build_sha256) is None
                    or type(ctx.evidence) is not AssuranceEvidence
                    or type(ctx.now) is not datetime or ctx.now.tzinfo is None
                    or type(ctx.baseline_authorized) is not bool):
                return False
            self._assurance.require_for_sensitive_action(
                evidence=ctx.evidence, now=ctx.now,
                candidate_id=ctx.candidate_id, build_sha256=ctx.build_sha256,
                baseline_authorized=ctx.baseline_authorized,
            )
            # Only the existing R65 ledger may give NEW. Never retry UNKNOWN.
            return self._paid(principal, request) is True
        except Exception:
            # Never leak private provider/attestation/device/account details.
            return False


__all__ = ["TrustedAssuranceContext", "CanonicalHighAssurancePaidCallback"]
