"""R68 operator-only product binding; no production migration is performed."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from continuum_runtime.backend_migration import MigrationCutover, MigrationProof
from acs.server_application_boundary import AuthenticatedPrincipal
from acs.protection_backend_migration_binding import (
    CanonicalMigrationOperatorBoundary, TrustedMigrationJob,
)


def actor(roles=frozenset({"migration.operator"}), permissions=frozenset({"backend.migrate"})):
    return AuthenticatedPrincipal(
        "actor.one", "workspace.one", "session.one", roles, permissions,
    )


def job():
    snapshot = b"canonical-snapshot"
    backup = b"trusted-backup"
    return TrustedMigrationJob(
        MigrationProof(
            migration_id="migration.one", source_id="source.one",
            target_id="target.one", scope_id="scope.one", revision=1,
            snapshot_sha256=sha256(snapshot).hexdigest(),
            backup_sha256=sha256(backup).hexdigest(),
        ),
        backup,
    )


def boundary(*, approve=lambda _actor, _proof: True, load=job, execute="CUTOVER_COMMITTED",
             reconcile="COMMITTED", fail_exec=False, fail_reconcile=False):
    calls = []
    source = object.__new__(MigrationCutover)
    def exec_stub(**kw):
        calls.append(("execute", kw))
        if fail_exec:
            raise RuntimeError("UNKNOWN-CAS-WITH-PRIVATE-SECRET")
        return execute
    def reconcile_stub(proof):
        calls.append(("reconcile", proof))
        if fail_reconcile:
            raise RuntimeError("PRIVATE-MIGRATION-ERROR")
        return reconcile
    source.execute = exec_stub
    source.reconcile = reconcile_stub
    return CanonicalMigrationOperatorBoundary(
        cutover=source, authorize_operator=approve, load_approved_job=load,
    ), calls


def test_r68_server_operator_executes_only_canonical_migration_cutover():
    bridge, calls = boundary()
    assert bridge.execute(actor()) == "COMMITTED"
    assert [event[0] for event in calls] == ["execute"]
    assert type(calls[0][1]["proof"]) is MigrationProof
    assert calls[0][1]["verified_backup"] == b"trusted-backup"


def test_r68_reconcile_is_read_only_and_never_calls_execute():
    bridge, calls = boundary(reconcile="UNKNOWN_FAIL_CLOSED")
    assert bridge.reconcile(actor()) == "UNKNOWN_FAIL_CLOSED"
    assert [event[0] for event in calls] == ["reconcile"]


@pytest.mark.parametrize("user", [
    actor(roles=frozenset()),
    actor(permissions=frozenset()),
    actor(roles=frozenset({"member"})),
    None, True, {},
])
def test_r68_roles_and_permissions_deny_without_side_effect(user):
    bridge, calls = boundary()
    assert bridge.execute(user) == "DENIED"
    assert bridge.reconcile(user) == "DENIED"
    assert calls == []


def test_r68_requires_separately_authenticated_operator_authorization():
    for verify in (lambda _actor, _proof: False, lambda _actor, _proof: 1,
                   lambda _actor, _proof: (_ for _ in ()).throw(RuntimeError("AUTH_SECRET"))):
        bridge, calls = boundary(approve=verify)
        assert bridge.execute(actor()) == "DENIED"
        assert bridge.reconcile(actor()) == "DENIED"
        assert calls == []


@pytest.mark.parametrize("bad_job", [None, False, {}, object(),
                                     replace(job(), verified_backup=b""),
                                     replace(job(), verified_backup="fake"),
                                     replace(job(), verified_backup=b"x" * (8*1024*1024+1))])
def test_r68_untrusted_job_source_cannot_start_migration(bad_job):
    bridge, calls = boundary(load=lambda: bad_job)
    assert bridge.execute(actor()) == "DENIED"
    assert calls == []


def test_r68_independent_approval_is_bound_to_exact_proof_not_role_only():
    reviewed = job().proof
    calls_to_approver = []
    def authorize(actor, proof):
        calls_to_approver.append((actor.actor_id, proof))
        return proof == reviewed
    bridge, effects = boundary(approve=authorize)
    assert bridge.execute(actor()) == "COMMITTED"
    assert calls_to_approver == [("actor.one", reviewed)]
    assert [x[0] for x in effects] == ["execute"]
    forged = replace(job(), proof=replace(reviewed, target_id="attacker.target"))
    blocked, blocked_effects = boundary(approve=authorize, load=lambda: forged)
    assert blocked.execute(actor()) == "DENIED"
    assert blocked.reconcile(actor()) == "DENIED"
    assert blocked_effects == []


def test_r68_not_authorized_operator_does_not_mutate_durable_backend():
    approvals = []
    def verify(_actor, _proof):
        approvals.append(True)
        return False
    bridge, calls = boundary(approve=verify)
    assert bridge.execute(actor()) == "DENIED"
    assert approvals == [True]
    assert calls == []



def test_r68_uncertain_commit_not_retried_or_promoted():
    bridge, calls = boundary(fail_exec=True)
    assert bridge.execute(actor()) == "UNKNOWN_FAIL_CLOSED"
    assert len(calls) == 1
    # Only explicit operator-requested read-only reconciliation follows.
    assert bridge.reconcile(actor()) == "COMMITTED"
    assert [x[0] for x in calls] == ["execute", "reconcile"]


@pytest.mark.parametrize("result", [None, 1, True, "ACK", "ROUTED", "UNKNOWN"])
def test_r68_forged_commit_result_fails_closed(result):
    bridge, calls = boundary(execute=result)
    assert bridge.execute(actor()) == "UNKNOWN_FAIL_CLOSED"
    assert len(calls) == 1


def test_r68_readback_error_does_not_promote_success():
    bridge, calls = boundary(fail_reconcile=True)
    assert bridge.reconcile(actor()) == "UNKNOWN_FAIL_CLOSED"
    assert len(calls) == 1


def test_r68_migration_authority_cannot_be_missing():
    with pytest.raises(ValueError, match="R68_MIGRATION_AUTHORITY_NOT_CONFIGURED"):
        CanonicalMigrationOperatorBoundary(
            cutover=None, authorize_operator=lambda _: True, load_approved_job=job,
        )
