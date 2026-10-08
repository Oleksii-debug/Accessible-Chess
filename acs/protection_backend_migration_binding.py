"""R68 trusted backend migration composition using the ONE canonical cutover.

Operator-only backend control, never a browser route or an alternate issuer.
No live migration is possible without external independently authenticated
proof, backup, journal, fenced source, verified target and durable routing CAS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from continuum_runtime.backend_migration import MigrationCutover, MigrationProof
from .server_application_boundary import AuthenticatedPrincipal


@dataclass(frozen=True)
class TrustedMigrationJob:
    """Loaded by trusted server operator storage, not by client/request JSON."""
    proof: MigrationProof
    verified_backup: bytes


class CanonicalMigrationOperatorBoundary:
    """Delegate exactly to R68 MigrationCutover, including UNKNOWN reconciliation.

    A role and permission alone never authenticate a migration; the injected
    operator authorization MUST independently verify the subject, target,
    source, scope and approved change ticket. Never retry an ambiguous write.
    """

    def __init__(
        self, *, cutover: MigrationCutover,
        authorize_operator: Callable[[AuthenticatedPrincipal], bool],
        load_approved_job: Callable[[], TrustedMigrationJob],
    ) -> None:
        if (type(cutover) is not MigrationCutover
                or not callable(authorize_operator)
                or not callable(load_approved_job)):
            raise ValueError("R68_MIGRATION_AUTHORITY_NOT_CONFIGURED")
        self._cutover = cutover
        self._authorize = authorize_operator
        self._job = load_approved_job

    def _authorized(self, actor: AuthenticatedPrincipal) -> bool:
        if (type(actor) is not AuthenticatedPrincipal
                or "migration.operator" not in actor.roles
                or "backend.migrate" not in actor.permissions):
            return False
        try:
            return self._authorize(actor) is True
        except Exception:
            return False

    def _approved_job(self) -> TrustedMigrationJob | None:
        try:
            job = self._job()
            if (type(job) is not TrustedMigrationJob
                    or type(job.proof) is not MigrationProof
                    or type(job.verified_backup) is not bytes
                    or not 0 < len(job.verified_backup) <= 8 * 1024 * 1024):
                return None
            return job
        except Exception:
            return None

    def execute(self, actor: AuthenticatedPrincipal) -> str:
        """No automatic retry on any ambiguous fence/stage/commit result."""
        if not self._authorized(actor):
            return "DENIED"
        job = self._approved_job()
        if job is None:
            return "DENIED"
        try:
            result = self._cutover.execute(
                proof=job.proof, verified_backup=job.verified_backup,
            )
            return "COMMITTED" if type(result) is str and result == "CUTOVER_COMMITTED" else "UNKNOWN_FAIL_CLOSED"
        except Exception:
            return "UNKNOWN_FAIL_CLOSED"

    def reconcile(self, actor: AuthenticatedPrincipal) -> str:
        """Read-only R68 reconciliation: never repeats a side effect."""
        if not self._authorized(actor):
            return "DENIED"
        job = self._approved_job()
        if job is None:
            return "DENIED"
        try:
            result = self._cutover.reconcile(job.proof)
            return "COMMITTED" if type(result) is str and result == "COMMITTED" else "UNKNOWN_FAIL_CLOSED"
        except Exception:
            return "UNKNOWN_FAIL_CLOSED"


__all__ = ["TrustedMigrationJob", "CanonicalMigrationOperatorBoundary"]
