"""R67 enterprise LAN seat composition; reuse the one R52/R45/R29 authority.

Trusted SERVER ONLY: no public client licence issuer, no browser-provided
device/account/site/build, no floating entitlement and no blind UNKNOWN retry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Callable

from continuum_runtime.enterprise_seats import EnterpriseSeatServer
from continuum_runtime.license_container import ContainerKind, ContainerRequest
from .server_application_boundary import ApiRequest, AuthenticatedPrincipal

_TICKET = re.compile(r"^[0-9a-f]{48}$")


@dataclass(frozen=True)
class TrustedSeatSession:
    """Verified by server auth middleware; never deserialize from a browser.

    enforcer, keys and context are injected from the existing canonical
    authorization stack. The optional LAN store itself has NO grant authority.
    """
    license_request: ContainerRequest
    enforcer: object
    context: dict[str, object]
    trusted_public_keys: dict[str, bytes]
    minimum_policy_version: int
    now: datetime


class CanonicalEnterpriseSeatBoundary:
    """Expose only checkout/checkin while reusing R67's signed seat ledger.

    The source of signed R52 entitlements, durable independent monotonic
    anchor and trusted seat clock are outside this product-side binding.
    For ambiguous remote effects do NOT blindly retry; use operator
    reconciliation against the canonical store and anchor.
    """

    def __init__(
        self, *, seats: EnterpriseSeatServer,
        trusted_session: Callable[[AuthenticatedPrincipal], TrustedSeatSession],
    ) -> None:
        if type(seats) is not EnterpriseSeatServer or not callable(trusted_session):
            raise ValueError("R67_TRUSTED_SEAT_AUTHORITY_NOT_CONFIGURED")
        self._seats = seats
        self._session = trusted_session

    def _resolve(
        self, principal: AuthenticatedPrincipal, request: ApiRequest,
        operation: str,
    ) -> TrustedSeatSession | None:
        if (type(principal) is not AuthenticatedPrincipal
                or type(request) is not ApiRequest
                or request.workspace_id != principal.workspace_id
                or 'enterprise.seat.use' not in principal.permissions
                or request.operation != operation):
            return None
        try:
            s = self._session(principal)  # no ApiRequest/body can forge identity
            if (type(s) is not TrustedSeatSession
                    or type(s.license_request) is not ContainerRequest
                    or s.license_request.kind is not ContainerKind.ENTERPRISE
                    or type(s.context) is not dict or len(s.context) > 64
                    or any(type(k) is not str for k in s.context)
                    or type(s.trusted_public_keys) is not dict
                    or not 1 <= len(s.trusted_public_keys) <= 32
                    or any(type(k) is not str or type(v) is not bytes
                           for k, v in s.trusted_public_keys.items())
                    or type(s.minimum_policy_version) is not int
                    or s.minimum_policy_version < 1
                    or type(s.now) is not datetime or s.now.tzinfo is None):
                return None
            return s
        except Exception:
            return None

    def checkout(self, principal: AuthenticatedPrincipal, request: ApiRequest) -> str | None:
        """Only an empty browser body is valid; ticket is NOT an entitlement."""
        if type(request) is not ApiRequest or request.payload != {}:
            return None
        s = self._resolve(principal, request, "enterprise.seat.checkout")
        if s is None:
            return None
        try:
            ticket = self._seats.checkout(
                request=s.license_request, enforcer=s.enforcer, context=s.context,
                trusted_public_keys=s.trusted_public_keys,
                minimum_policy_version=s.minimum_policy_version, now=s.now,
            )
            return ticket if type(ticket) is str and _TICKET.fullmatch(ticket) else None
        except Exception:
            return None

    def checkin(self, principal: AuthenticatedPrincipal, request: ApiRequest) -> bool:
        """Tickets may be presented by clients but are verified by R67 owner."""
        if type(request) is not ApiRequest or set(request.payload) != {"ticket"}:
            return False
        ticket = request.payload["ticket"]
        if type(ticket) is not str or _TICKET.fullmatch(ticket) is None:
            return False
        s = self._resolve(principal, request, "enterprise.seat.checkin")
        if s is None:
            return False
        try:
            result = self._seats.checkin(
                ticket=ticket, request=s.license_request, enforcer=s.enforcer,
                context=s.context, trusted_public_keys=s.trusted_public_keys,
                minimum_policy_version=s.minimum_policy_version, now=s.now,
            )
            return result is None
        except Exception:
            return False


__all__ = ["TrustedSeatSession", "CanonicalEnterpriseSeatBoundary"]
