"""R65 product server paid-operation boundary; the browser never issues authority."""
from __future__ import annotations

import pytest

from acs.server_application_boundary import (
    ApiRequest, AuthenticatedPrincipal, ServerApplicationBoundary,
    ServerBoundaryError, ServerOperation,
)


def _context(guard):
    calls = []
    operation = ServerOperation(
        operation="premium.analysis",
        permission="premium.use",
        mutates=False,
        handler=lambda *_args: calls.append("effect") or {"result": "ok"},
        premium_required=True,
    )
    principal = AuthenticatedPrincipal(
        actor_id="actor-1", workspace_id="workspace-1",
        session_id="session-1",
        roles=frozenset({"member"}),
        permissions=frozenset({"premium.use"}),
    )
    request = ApiRequest(
        schema_version=1, request_id="req-1",
        workspace_id="workspace-1",
        operation="premium.analysis", payload={},
    )
    class _Policy:
        def verify_gate(self, _gate):
            return None
        def authorize(self, _request):
            return None
    # Use the already-constructed server's handle path, isolating its new R65
    # effect guard without creating a second fake production security policy.
    server = object.__new__(ServerApplicationBoundary)
    server._operations = {operation.operation: operation}
    server._product_security_guard = None
    server._premium_guard = guard
    server._job_store = None
    server._security_policy = _Policy()
    server._security_gate = None
    return server, principal, request, calls


@pytest.mark.parametrize("bad", [1, "yes", None, [], {}])
def test_premium_server_flag_must_be_literal_bool(bad):
    with pytest.raises(ServerBoundaryError, match="operation flags"):
        ServerOperation(
            operation="premium.analysis", permission="premium.use",
            mutates=False, premium_required=bad,
            handler=lambda *_: {},
        )


def test_premium_heavy_queue_rejected_until_worker_time_recheck_exists():
    with pytest.raises(ServerBoundaryError, match="execution-time authority"):
        ServerOperation(
            operation="premium.analysis", permission="premium.use",
            mutates=False, heavy=True, premium_required=True,
            handler=lambda *_: {},
        )


@pytest.mark.parametrize("decision", [None, False, 0, 1, "yes", {}, []])
def test_absent_forged_or_truthy_server_premium_decision_blocks_effect(decision):
    server, principal, request, calls = _context(lambda *_: decision)
    with pytest.raises(ServerBoundaryError, match="server premium operation denied"):
        server.handle(principal, request)
    assert calls == []


def test_server_guard_exception_is_redacted_and_never_reaches_handler():
    def fail(*_):
        raise RuntimeError("PRIVATE-BILLING-TOKEN-NEVER-EXPOSE")
    server, principal, request, calls = _context(fail)
    with pytest.raises(ServerBoundaryError) as err:
        server.handle(principal, request)
    assert "PRIVATE-BILLING" not in str(err.value)
    assert err.value.__cause__ is None
    assert calls == []


def test_literal_true_server_guard_allows_one_handler_effect():
    events = []
    server, principal, request, calls = _context(
        lambda principal, request: events.append(
            (principal.actor_id, request.request_id)
        ) or True
    )
    result = server.handle(principal, request)
    assert events == [("actor-1", "req-1")]
    assert calls == ["effect"]
    assert result["schema_version"] == 1


def test_preexisting_free_operation_remains_unchanged():
    server, principal, request, calls = _context(
        lambda *_: (_ for _ in ()).throw(RuntimeError("should not run"))
    )
    original = server._operations["premium.analysis"]
    server._operations = {
        "premium.analysis": ServerOperation(
            operation=original.operation, permission=original.permission,
            mutates=False, handler=original.handler,
        )
    }
    server.handle(principal, request)
    assert calls == ["effect"]
