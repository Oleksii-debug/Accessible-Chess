from __future__ import annotations

import asyncio
from dataclasses import replace
import unittest

from acs.agent_tools import ToolCall, ToolExecutor
from acs.chesscore import Board
from acs.interaction_contracts import PresentationState
from acs.media_application import MediaApplicationService
from acs.media_core import (
    MediaChessLink,
    MediaChessSession,
    MediaCursor,
    MediaLinkStatus,
    MediaPositionTimeline,
    MediaSource,
    MediaSourceKind,
)
from acs.remote_session import RemoteSessionState
from acs.section36_integration import (
    AccountWorkspaceSnapshot,
    AgentAccountWorkspaceTools,
    AgentTactileTools,
    CrossSurfaceTactileBridge,
    Section36AgentIntegration,
    TeacherAssistantWorkflow,
)
from acs.tactile_graphics import TactileGraphicsController, TactileSimulator
from acs.tactile_sync import TactileSyncController
from acs.teaching_session import TeachingSessionPhase, TeachingSessionState


def _teaching_state(*, revision: int = 0, fen: str = Board.START) -> TeachingSessionState:
    return TeachingSessionState(
        session_id="lesson-session",
        plan_digest="0" * 64,
        phase=TeachingSessionPhase.ACTIVE,
        step_index=0,
        position_fen=fen,
        presentation=PresentationState(),
        remaining_seconds=None,
        revision=revision,
    )


def _tactile() -> tuple[TactileSyncController, TactileSimulator]:
    simulator = TactileSimulator()
    return TactileSyncController(TactileGraphicsController(simulator)), simulator


def _execute(executor: ToolExecutor, tool_id: str, arguments=None):
    return asyncio.run(
        executor.execute(
            ToolCall(
                call_id=f"call-{tool_id}",
                tool_id=tool_id,
                arguments={} if arguments is None else arguments,
            )
        )
    )


class Section36AccountWorkspaceTests(unittest.TestCase):
    def test_authorized_account_and_workspace_reads_are_non_secret(self):
        snapshot = AccountWorkspaceSnapshot(
            signed_in=True,
            account_id="acct-1",
            organization_id="org-1",
            workspace_id="workspace-1",
            workspace_revision=7,
            permissions=frozenset({"account.read", "workspace.read"}),
        )
        tools = AgentAccountWorkspaceTools(
            lambda: snapshot,
            lambda permission, current: permission in current.permissions,
        )
        executor = ToolExecutor()
        tools.register(executor)

        account = _execute(executor, "account.status")
        workspace = _execute(executor, "workspace.status")
        self.assertTrue(account.ok, account.error)
        self.assertTrue(workspace.ok, workspace.error)
        self.assertEqual(
            account.output,
            {
                "signedIn": True,
                "accountId": "acct-1",
                "organizationId": "org-1",
            },
        )
        self.assertEqual(
            workspace.output,
            {
                "workspaceId": "workspace-1",
                "workspaceRevision": 7,
                "organizationId": "org-1",
            },
        )
        rendered = repr((account.output, workspace.output)).casefold()
        for forbidden in ("token", "secret", "password", "cookie"):
            self.assertNotIn(forbidden, rendered)

    def test_account_workspace_reads_fail_closed_without_permission(self):
        snapshot = AccountWorkspaceSnapshot(
            signed_in=True,
            account_id="acct-1",
            organization_id=None,
            workspace_id="workspace-1",
            workspace_revision=0,
            permissions=frozenset({"account.read"}),
        )
        executor = ToolExecutor()
        AgentAccountWorkspaceTools(
            lambda: snapshot,
            lambda permission, current: True,
        ).register(executor)

        result = _execute(executor, "workspace.status")
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool failed")


class Section36TeacherAssistantTests(unittest.TestCase):
    def test_teacher_assistant_uses_revision_fence_and_typed_dispatch(self):
        holder = {"state": _teaching_state(revision=4)}
        calls = []

        def dispatch(action_id, payload):
            calls.append((action_id, dict(payload)))
            holder["state"] = replace(holder["state"], revision=5)

        workflow = TeacherAssistantWorkflow(
            lambda: holder["state"],
            dispatch,
            permitted_actions=frozenset({"teacher.show_square"}),
        )
        executor = ToolExecutor()
        workflow.register(executor)

        status = _execute(executor, "classroom.teacher_assistant.status")
        self.assertTrue(status.ok, status.error)
        self.assertEqual(status.output["revision"], 4)

        result = _execute(
            executor,
            "classroom.teacher_assistant.apply",
            {
                "action_id": "teacher.show_square",
                "payload": {"square": "e4"},
                "expected_revision": 4,
            },
        )
        self.assertTrue(result.ok, result.error)
        self.assertEqual(calls, [("teacher.show_square", {"square": "e4"})])
        self.assertEqual(result.output["revision"], 5)
        self.assertEqual(holder["state"].position_fen, Board.START)

    def test_teacher_assistant_rejects_unapproved_or_stale_action(self):
        holder = {"state": _teaching_state(revision=2)}
        workflow = TeacherAssistantWorkflow(
            lambda: holder["state"],
            lambda _action, _payload: None,
            permitted_actions=frozenset({"teacher.show_square"}),
        )
        executor = ToolExecutor()
        workflow.register(executor)

        forbidden = _execute(
            executor,
            "classroom.teacher_assistant.apply",
            {
                "action_id": "teacher.make_move",
                "payload": {},
                "expected_revision": 2,
            },
        )
        stale = _execute(
            executor,
            "classroom.teacher_assistant.apply",
            {
                "action_id": "teacher.show_square",
                "payload": {"square": "e4"},
                "expected_revision": 1,
            },
        )
        self.assertFalse(forbidden.ok)
        self.assertFalse(stale.ok)


class Section36TactileCrossSurfaceTests(unittest.TestCase):
    def test_media_to_tactile_reads_confirmed_ref_without_mutating_media(self):
        source = MediaSource(
            source_id="media-1",
            title="Fixture",
            kind=MediaSourceKind.LOCAL_FILE,
            duration_ms=1000,
        )
        timeline = MediaPositionTimeline(
            "media-1",
            (
                MediaChessLink(
                    source_id="media-1",
                    timestamp_ms=0,
                    chess_ref="canonical-position-1",
                    status=MediaLinkStatus.CONFIRMED,
                    confidence=1.0,
                ),
            ),
        )
        application = MediaApplicationService(
            source=source,
            timeline=timeline,
            session=MediaChessSession(MediaCursor("media-1", 0)),
            restore_chess_ref=lambda _ref: None,
        )
        before = application.snapshot()
        tactile, simulator = _tactile()
        bridge = CrossSurfaceTactileBridge(
            tactile,
            media_provider=lambda: application,
            media_ref_to_fen=lambda ref: (
                Board.START
                if ref == "canonical-position-1"
                else (_ for _ in ()).throw(AssertionError("unexpected ref"))
            ),
        )

        result = bridge.sync_media()

        self.assertEqual(result["source"], "media")
        self.assertEqual(result["canonicalFen"], Board.START)
        self.assertEqual(simulator.current_scene.position_fen, Board.START)
        self.assertEqual(application.snapshot(), before)

    def test_classroom_and_remote_use_source_state_without_second_authority(self):
        classroom = _teaching_state(revision=8)
        remote = RemoteSessionState(
            session_id="remote-1",
            last_sequence=3,
            position_fen=Board.START,
        )
        tactile, simulator = _tactile()
        bridge = CrossSurfaceTactileBridge(
            tactile,
            classroom_state_provider=lambda: classroom,
            remote_state_provider=lambda: remote,
        )

        classroom_result = bridge.sync_classroom()
        remote_result = bridge.sync_remote()

        self.assertEqual(classroom_result["sourceRevision"], 8)
        self.assertEqual(remote_result["sourceRevision"], 3)
        self.assertEqual(classroom.position_fen, Board.START)
        self.assertEqual(remote.position_fen, Board.START)
        self.assertEqual(simulator.current_scene.position_fen, Board.START)

    def test_agent_tactile_tools_expose_only_owner_backed_refreshes(self):
        classroom = _teaching_state(revision=1)
        remote = RemoteSessionState(session_id="remote-1")
        tactile, _simulator = _tactile()
        bridge = CrossSurfaceTactileBridge(
            tactile,
            classroom_state_provider=lambda: classroom,
            remote_state_provider=lambda: remote,
        )
        executor = ToolExecutor()
        AgentTactileTools(bridge).register(executor)

        ids = {spec.tool_id for spec in executor.specs()}
        self.assertEqual(
            ids,
            {
                "tactile.status",
                "tactile.refresh_media",
                "tactile.refresh_classroom",
                "tactile.refresh_remote",
            },
        )
        self.assertNotIn("tactile.set_fen", ids)
        result = _execute(executor, "tactile.refresh_classroom")
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output["canonicalFen"], Board.START)
        unavailable = _execute(executor, "tactile.refresh_media")
        self.assertFalse(unavailable.ok)


class Section36CompositionTests(unittest.TestCase):
    def test_single_registration_point_keeps_typed_tools_unique(self):
        account = AccountWorkspaceSnapshot(
            signed_in=True,
            account_id="acct",
            organization_id=None,
            workspace_id="workspace",
            workspace_revision=1,
            permissions=frozenset({"account.read", "workspace.read"}),
        )
        holder = {"state": _teaching_state()}
        teacher = TeacherAssistantWorkflow(
            lambda: holder["state"],
            lambda _action, _payload: None,
            permitted_actions=frozenset({"teacher.show_square"}),
        )
        tactile_sync, _simulator = _tactile()
        tactile = AgentTactileTools(
            CrossSurfaceTactileBridge(
                tactile_sync,
                classroom_state_provider=lambda: holder["state"],
                remote_state_provider=lambda: RemoteSessionState("remote"),
            )
        )
        integration = Section36AgentIntegration(
            account_workspace=AgentAccountWorkspaceTools(
                lambda: account,
                lambda permission, current: permission in current.permissions,
            ),
            teacher_assistant=teacher,
            tactile=tactile,
        )
        executor = ToolExecutor()

        specs = integration.register(executor)
        ids = [spec.tool_id for spec in specs]

        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            set(ids),
            {
                "account.status",
                "workspace.status",
                "classroom.teacher_assistant.status",
                "classroom.teacher_assistant.apply",
                "tactile.status",
                "tactile.refresh_media",
                "tactile.refresh_classroom",
                "tactile.refresh_remote",
            },
        )


if __name__ == "__main__":
    unittest.main()
