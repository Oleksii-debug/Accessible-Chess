from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from acs.network_security import DEFAULT_SECTION29_POLICY, SecurityGate
from acs.server_application_boundary import (
    API_SCHEMA_VERSION,
    ApiRequest,
    AuthenticatedPrincipal,
    AuthenticatedServerAsgi,
    EntityRef,
    JobState,
    ServerApplicationBoundary,
    ServerBoundaryError,
    ServerOperation,
    SqliteJobStore,
    build_application_operations,
)


class Section30ServerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.policy = DEFAULT_SECTION29_POLICY
        self.principal = AuthenticatedPrincipal(
            actor_id="user-1",
            workspace_id="workspace-1",
            session_id="session-1",
            roles=frozenset({"teacher"}),
            permissions=frozenset({"app.read", "app.write", "jobs.cancel"}),
        )

    def _boundary(self, operations, job_store=None):
        return ServerApplicationBoundary(
            security_policy=self.policy,
            security_gate=self.policy.gate(),
            operations=operations,
            job_store=job_store,
        )

    def test_real_application_snapshot_and_dispatch_are_delegated(self):
        calls = []
        def snapshot():
            return {"route": "board", "revision": 7}
        def dispatch(action_id, payload):
            calls.append((action_id, payload))
            return {"accepted": True, "action": action_id}
        boundary = self._boundary(build_application_operations(snapshot=snapshot, dispatch=dispatch))
        query = ApiRequest(1, "req-query-1", "workspace-1", "server.application.snapshot", {})
        self.assertEqual(boundary.handle(self.principal, query)["result"]["route"], "board")
        command = ApiRequest(
            1, "req-command-1", "workspace-1", "server.application.command",
            {"action_id": "board.new_game", "payload": {}},
            EntityRef("board-1", 7),
        )
        self.assertTrue(boundary.handle(self.principal, command)["result"]["accepted"])
        self.assertEqual(calls, [("board.new_game", {})])

    def test_state_change_fails_closed_without_entity_revision(self):
        boundary = self._boundary(build_application_operations(snapshot=lambda: {}, dispatch=lambda *_: {}))
        request = ApiRequest(
            1, "req-1", "workspace-1", "server.application.command",
            {"action_id": "board.new_game", "payload": {}},
        )
        with self.assertRaises(ServerBoundaryError):
            boundary.handle(self.principal, request)

    def test_cross_workspace_and_missing_permission_are_rejected_server_side(self):
        boundary = self._boundary(build_application_operations(snapshot=lambda: {}, dispatch=lambda *_: {}))
        with self.assertRaises(ServerBoundaryError):
            boundary.handle(
                self.principal,
                ApiRequest(1, "req-cross", "workspace-2", "server.application.snapshot", {}),
            )
        weak = AuthenticatedPrincipal(
            "user-1", "workspace-1", "session-1",
            frozenset({"teacher"}), frozenset({"app.read"}),
        )
        with self.assertRaises(ServerBoundaryError):
            boundary.handle(
                weak,
                ApiRequest(
                    1, "req-write", "workspace-1", "server.application.command",
                    {"action_id": "board.new_game", "payload": {}},
                    EntityRef("board-1", 0),
                ),
            )

    def test_versioned_dtos_reject_malformed_ids_and_unbounded_json(self):
        with self.assertRaises(ServerBoundaryError):
            ApiRequest(2, "req-1", "workspace-1", "server.application.snapshot", {})
        with self.assertRaises(ServerBoundaryError):
            ApiRequest(1, "req 1", "workspace-1", "server.application.snapshot", {})
        with self.assertRaises(ServerBoundaryError):
            ApiRequest(1, "req-1", "workspace-1", "server.application.snapshot", {"bad": float("nan")})

    def test_section29_gate_is_a_hard_composition_prerequisite(self):
        gate = self.policy.gate()
        stale = SecurityGate(gate.schema_version, gate.policy_revision, "0" * 64)
        with self.assertRaises(ServerBoundaryError):
            ServerApplicationBoundary(
                security_policy=self.policy,
                security_gate=stale,
                operations=build_application_operations(snapshot=lambda: {}, dispatch=lambda *_: {}),
            )

    def test_durable_job_cancel_retry_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteJobStore(Path(directory) / "jobs.sqlite3")
            operation = ServerOperation(
                "server.heavy.import", True, "app.write",
                lambda _principal, payload, _entity: {"value": payload["value"]},
                heavy=True,
            )
            boundary = self._boundary((operation,), store)
            request = ApiRequest(
                1, "req-heavy-1", "workspace-1", "server.heavy.import",
                {"value": 3}, EntityRef("library-1", 2),
            )
            accepted = boundary.handle(self.principal, request)
            job_id = accepted["job"]["job_id"]
            self.assertEqual(accepted["job"]["state"], "queued")
            running = store.claim_next()
            self.assertEqual(running.state, JobState.RUNNING)
            store.progress(job_id, 40)
            self.assertEqual(store.recover_after_restart(), 1)
            recovered = store.get(job_id)
            self.assertEqual(recovered.state, JobState.QUEUED)
            self.assertEqual(recovered.error_code, "restart_recovery")
            running = store.claim_next()
            self.assertEqual(running.attempts, 2)
            failed = store.fail(job_id, error_code="provider_retry", retryable=True)
            self.assertEqual(failed.state, JobState.QUEUED)
            running = store.claim_next()
            self.assertEqual(running.attempts, 3)
            done = store.complete(job_id, {"ok": True})
            self.assertEqual(done.state, JobState.SUCCEEDED)
            self.assertEqual(done.progress, 100)
            second = ApiRequest(
                1, "req-heavy-2", "workspace-1", "server.heavy.import",
                {"value": 4}, EntityRef("library-1", 3),
            )
            second_job = boundary.handle(self.principal, second)["job"]["job_id"]
            cancelled = boundary.cancel_job(self.principal, job_id=second_job)
            self.assertEqual(cancelled["job"]["state"], "cancelled")

    def test_job_request_id_is_idempotent_and_conflicts_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteJobStore(Path(directory) / "jobs.sqlite3")
            request = ApiRequest(
                1, "req-heavy", "workspace-1", "server.heavy.import",
                {"value": 3}, EntityRef("library-1", 2),
            )
            first = store.enqueue(request)
            second = store.enqueue(request)
            self.assertEqual(first.job_id, second.job_id)
            changed = ApiRequest(
                1, "req-heavy", "workspace-1", "server.heavy.import",
                {"value": 4}, EntityRef("library-1", 2),
            )
            with self.assertRaises(ServerBoundaryError):
                store.enqueue(changed)

    def test_asgi_requires_trusted_principal_and_never_accepts_http_identity(self):
        boundary = self._boundary(build_application_operations(snapshot=lambda: {"ok": True}, dispatch=lambda *_: {}))
        app = AuthenticatedServerAsgi(boundary)

        async def invoke(state):
            events = [{"type": "http.request", "body": json.dumps({
                "schema_version": 1,
                "request_id": "req-http",
                "workspace_id": "workspace-1",
                "operation": "server.application.snapshot",
                "payload": {},
                "entity": None,
            }).encode(), "more_body": False}]
            sent = []
            async def receive():
                return events.pop(0)
            async def send(event):
                sent.append(event)
            await app(
                {"type": "http", "method": "POST", "path": "/v1/query", "state": state},
                receive, send,
            )
            return sent

        self.assertEqual(asyncio.run(invoke({}))[0]["status"], 400)
        self.assertEqual(asyncio.run(invoke({"accessible_chess_principal": self.principal}))[0]["status"], 200)

    def test_server_module_contains_no_chess_or_gametree_authority(self):
        source = (Path(__file__).resolve().parents[1] / "acs" / "server_application_boundary.py").read_text(encoding="utf-8")
        for token in (
            "from .chesscore", "import chesscore", "from .gametree",
            "from .notation", "parse_fen", "legal_moves(",
        ):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
