"""R62 trusted server-only incident boundary over canonical R61/R22 authorities.

This is an integration contract, not a deployed incident console or public API.
A production caller must supply independently authenticated operator authorization,
an ACID durable case journal, and the canonical continuum LeakResponseService
wired to the real R22 revocation authority. No client-controlled role or release
flag is accepted; ambiguous effects MUST be reconciled, never blindly retried.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Callable

from continuum_runtime.leak_response import (
    LeakResponseDenied, LeakResponseService,
)
from continuum_runtime.revocation import RevocationKind

_CASE = re.compile(r"[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_BUILD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_MAX_ARTIFACT = 16 * 1024 * 1024


class IncidentBoundaryDenied(ValueError):
    """Only a fixed reason is exposed, never operator tokens or attribution data."""


class TrustedIncidentBoundary:
    """Delegates effect authority to R62/R22 and idempotency to the durable journal.

    Journal.reserve(case_id, request_digest) MUST atomically persist UNKNOWN
    before the revocation effect. It returns literal 'NEW' only for the first
    attempt; duplicate, conflicted, uncertain and recovered cases deny.
    Journal.complete(case_id, request_digest, revocation_id) MUST atomically
    persist verified effect readback and return literal True.
    An unavailable/in-memory journal is not suitable for production.
    """

    def __init__(
        self, *, service: LeakResponseService,
        authorize_operator: Callable[[str, RevocationKind], bool],
        durable_journal: object,
    ) -> None:
        if (type(service) is not LeakResponseService
                or not callable(authorize_operator)
                or not callable(getattr(durable_journal, "reserve", None))
                or not callable(getattr(durable_journal, "complete", None))):
            raise IncidentBoundaryDenied("R62_TRUSTED_BACKEND_NOT_CONFIGURED")
        self._service = service
        self._authorize = authorize_operator
        self._journal = durable_journal

    def apply(
        self, *, operator_session: str, case_id: str, evidence_sha256: str,
        envelope: object, protected_artifact: bytes, expected_build_id: str,
        kind: RevocationKind, now: datetime,
    ) -> dict[str, object]:
        if (type(operator_session) is not str or not operator_session
                or len(operator_session) > 512
                or type(case_id) is not str or _CASE.fullmatch(case_id) is None
                or type(evidence_sha256) is not str
                or _SHA256.fullmatch(evidence_sha256) is None
                or type(expected_build_id) is not str
                or _BUILD.fullmatch(expected_build_id) is None
                or type(kind) is not RevocationKind
                or kind not in (RevocationKind.CREDENTIAL,
                                RevocationKind.DEVICE, RevocationKind.BUILD)
                or type(protected_artifact) is not bytes
                or not 1 <= len(protected_artifact) <= _MAX_ARTIFACT
                or not isinstance(now, datetime) or now.tzinfo is None):
            raise IncidentBoundaryDenied("R62_REQUEST_INVALID")
        try:
            if self._authorize(operator_session, kind) is not True:
                raise IncidentBoundaryDenied("R62_OPERATOR_DENIED")
        except IncidentBoundaryDenied:
            raise
        except Exception:
            raise IncidentBoundaryDenied("R62_OPERATOR_DENIED") from None

        try:
            # Bind exact proof bytes, kind, build and case to the one journal
            # reservation. The journal stores only this digest and opaque case.
            evidence_packet = json.dumps(
                {"case": case_id, "evidence": evidence_sha256,
                 "envelope": envelope, "artifact_sha256":
                 hashlib.sha256(protected_artifact).hexdigest(),
                 "build": expected_build_id, "kind": kind.value},
                sort_keys=True, separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")
            if len(evidence_packet) > 16384:
                raise ValueError("oversized incident")
            digest = hashlib.sha256(evidence_packet).hexdigest()
        except (TypeError, ValueError, OverflowError):
            raise IncidentBoundaryDenied("R62_PROOF_ENVELOPE_INVALID") from None

        try:
            admitted = self._journal.reserve(
                case_id=case_id, request_digest=digest)
        except Exception:
            # A reserve may already be durable. Never attempt the effect.
            raise IncidentBoundaryDenied("R62_RESERVATION_UNKNOWN") from None
        if type(admitted) is not str or admitted != "NEW":
            raise IncidentBoundaryDenied("R62_CASE_NOT_NEW")

        try:
            decision = self._service.respond(
                case_id=case_id, evidence_sha256=evidence_sha256,
                envelope=envelope, protected_artifact=protected_artifact,
                expected_build_id=expected_build_id, kind=kind, now=now)
        except LeakResponseDenied:
            # The journal deliberately stays UNKNOWN until a separate trusted
            # reconciliation process establishes what actually happened.
            raise IncidentBoundaryDenied("R62_CANONICAL_RESPONSE_DENIED") from None
        except Exception:
            raise IncidentBoundaryDenied("R62_EFFECT_UNKNOWN") from None

        try:
            committed = self._journal.complete(
                case_id=case_id, request_digest=digest,
                revocation_id=decision.revocation_id)
        except Exception:
            raise IncidentBoundaryDenied("R62_JOURNAL_UNKNOWN") from None
        if committed is not True:
            raise IncidentBoundaryDenied("R62_JOURNAL_UNKNOWN")

        return {
            "schema_version": 1,
            "status": "R62_TARGET_REVOCATION_RECORDED",
            "action_kind": decision.action_kind,
            "action_fingerprint": decision.action_fingerprint,
            "release_approved": False,
        }
