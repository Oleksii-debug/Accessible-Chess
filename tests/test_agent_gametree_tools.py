from __future__ import annotations

import asyncio
import unittest

from acs.agent_gametree_tools import register_gametree_tools
from acs.agent_model_contracts import (
    ModelRequest,
    ModelResponse,
    ModelUsage,
    ProviderCapabilities,
    ProviderKind,
)
from acs.agent_model_gateway import ModelGateway
from acs.agent_tools import (
    ToolAuthorization,
    ToolCall,
    ToolExecutor,
    ToolRisk,
    tool_arguments_fingerprint,
)
from acs.chess_agent_tools import ChessAgentToolRegistry
from acs.pgn_workspace import PgnWorkspace
from acs.universal_chess_agent import UniversalChessAgentRuntime


PGN = """[Event "Tree One"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 (1... c5 2. Nf3) (1... e6 2. d4) 2. Nf3 Nc6 *

[Event "Tree Two"]
[White "Gamma"]
[Black "Delta"]
[Result "1-0"]

1. d4 d5 1-0
"""


class _ScriptedProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id="gametree-fixture",
            kind=ProviderKind.LOCAL,
            supports_private_data=True,
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected model call")
        return ModelResponse(
            request_id=request.request_id,
            text=self.responses.pop(0),
            provider_id="gametree-fixture",
            provider_kind=ProviderKind.LOCAL,
            model=request.model or "fixture-model",
            usage=ModelUsage(
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
            ),
        )


class AgentGameTreeToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = PgnWorkspace.from_text(PGN)
        self.executor = ToolExecutor()
        register_gametree_tools(self.executor, lambda: self.workspace)

    def execute(self, tool_id: str, arguments=None):
        return asyncio.run(
            self.executor.execute(
                ToolCall(
                    call_id=f"call-{tool_id}",
                    tool_id=tool_id,
                    arguments=arguments or {},
                )
            )
        )

    def test_status_is_bounded_canonical_workspace_state(self) -> None:
        result = self.execute("gametree.current")
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output["gameCount"], 2)
        self.assertEqual(result.output["selectedGameIndex"], 0)
        self.assertEqual(result.output["game"]["event"], "Tree One")
        self.assertEqual(result.output["cursor"]["linePath"], [])
        self.assertEqual(result.output["cursor"]["nextMoveIndex"], 0)
        self.assertEqual(result.output["currentMove"]["san"], "e4")
        self.assertIsNone(result.output["previousMove"])
        self.assertTrue(result.output["atLineStart"])
        self.assertFalse(result.output["atLineEnd"])
        self.assertFalse(result.output["dirty"])

    def test_navigation_reuses_workspace_branch_return_semantics(self) -> None:
        original_digest = self.workspace.content_digest
        self.assertTrue(self.execute("gametree.next_move").ok)
        parent = self.execute("gametree.next_move")
        self.assertTrue(parent.ok, parent.error)
        self.assertEqual(parent.output["previousMove"]["san"], "e5")
        self.assertEqual(parent.output["availableVariations"], 2)

        entered = self.execute(
            "gametree.enter_variation", {"variation_index": 0}
        )
        self.assertTrue(entered.ok, entered.error)
        self.assertEqual(
            entered.output["cursor"]["linePath"],
            [{"parentMoveIndex": 1, "variationIndex": 0}],
        )
        self.assertEqual(entered.output["currentMove"]["san"], "c5")
        self.assertEqual(entered.output["siblingVariationCount"], 2)

        sibling = self.execute(
            "gametree.sibling_variation", {"direction": "next"}
        )
        self.assertTrue(sibling.ok, sibling.error)
        self.assertEqual(
            sibling.output["cursor"]["linePath"],
            [{"parentMoveIndex": 1, "variationIndex": 1}],
        )
        self.assertEqual(sibling.output["currentMove"]["san"], "e6")

        left = self.execute("gametree.leave_variation")
        self.assertTrue(left.ok, left.error)
        self.assertEqual(left.output["cursor"]["linePath"], [])
        self.assertEqual(left.output["cursor"]["nextMoveIndex"], 2)
        self.assertEqual(left.output["currentMove"]["san"], "Nf3")

        self.assertEqual(self.workspace.content_digest, original_digest)
        self.assertFalse(self.workspace.dirty)
        self.assertEqual(self.workspace.content_revision, 0)

    def test_failed_navigation_is_atomic(self) -> None:
        before = self.workspace.view()
        digest = self.workspace.content_digest
        for tool_id, arguments in (
            ("gametree.previous_move", {}),
            ("gametree.enter_variation", {"variation_index": True}),
            ("gametree.enter_variation", {"variation_index": 0}),
        ):
            with self.subTest(tool_id=tool_id, arguments=arguments):
                result = self.execute(tool_id, arguments)
                self.assertFalse(result.ok)
                self.assertEqual(result.error, "tool failed")
                self.assertEqual(self.workspace.view(), before)
        self.assertEqual(self.workspace.content_digest, digest)
        self.assertFalse(self.workspace.dirty)


    def test_promote_current_variation_uses_canonical_workspace_edit(self) -> None:
        self.assertTrue(self.execute("gametree.next_move").ok)
        self.assertTrue(self.execute("gametree.next_move").ok)
        entered = self.execute(
            "gametree.enter_variation", {"variation_index": 0}
        )
        self.assertTrue(entered.ok, entered.error)

        result = self.execute("gametree.promote_current_variation")
        self.assertTrue(result.ok, result.error)
        self.assertTrue(result.output["dirty"])
        self.assertEqual(result.output["contentRevision"], 1)
        self.assertFalse(result.output["insideVariation"])
        self.assertEqual(result.output["currentMove"]["san"], "c5")
        root = self.workspace.current_game().line
        self.assertEqual([move.san for move in root.moves], ["e4", "c5", "Nf3"])

    def test_reorder_current_variation_tracks_same_semantic_branch(self) -> None:
        self.assertTrue(self.execute("gametree.next_move").ok)
        self.assertTrue(self.execute("gametree.next_move").ok)
        self.assertTrue(
            self.execute(
                "gametree.enter_variation", {"variation_index": 0}
            ).ok
        )

        result = self.execute(
            "gametree.reorder_current_variation", {"new_index": 1}
        )
        self.assertTrue(result.ok, result.error)
        self.assertTrue(result.output["dirty"])
        self.assertEqual(result.output["contentRevision"], 1)
        self.assertTrue(result.output["insideVariation"])
        self.assertEqual(result.output["activeVariationIndex"], 1)
        self.assertEqual(result.output["currentMove"]["san"], "c5")
        owner = self.workspace.current_game().line.moves[1]
        self.assertEqual(
            [variation.moves[0].san for variation in owner.variations],
            ["e6", "c5"],
        )

    def test_delete_current_variation_requires_high_impact_authority(self) -> None:
        self.workspace.next_move()
        self.workspace.next_move()
        self.workspace.enter_variation(0)
        before = self.workspace.to_text()
        revision = self.workspace.content_revision

        denied = self.execute("gametree.delete_current_variation")
        self.assertFalse(denied.ok)
        self.assertEqual(
            denied.error,
            "approval and durable effect guard required",
        )
        self.assertEqual(self.workspace.to_text(), before)
        self.assertEqual(self.workspace.content_revision, revision)

        guard = _EffectGuard()

        async def approval(spec, call):
            return ToolAuthorization(
                tool_id=spec.tool_id,
                task_id=call.task_id,
                risk=spec.risk,
                arguments_fingerprint=tool_arguments_fingerprint(call.arguments),
                effect_fingerprint="delete-current-variation",
                approval_fingerprint="approved-by-host",
            )

        executor = ToolExecutor(
            approval_policy=approval,
            effect_guard=guard,
        )
        register_gametree_tools(executor, lambda: self.workspace)
        result = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="delete-approved",
                    tool_id="gametree.delete_current_variation",
                    arguments={},
                    task_id="agent-task-delete",
                )
            )
        )
        self.assertTrue(result.ok, result.error)
        self.assertTrue(guard.completed)
        self.assertFalse(guard.uncertain)
        self.assertEqual(self.workspace.content_revision, revision + 1)
        self.assertTrue(self.workspace.dirty)
        self.assertFalse(result.output["insideVariation"])
        self.assertEqual(result.output["cursor"]["nextMoveIndex"], 2)
        self.assertEqual(len(self.workspace.current_game().line.moves[1].variations), 1)

    def test_structural_edit_failures_are_atomic_and_cursor_derived(self) -> None:
        root_before = self.workspace.to_text()
        root_view = self.workspace.view()
        result = self.execute("gametree.promote_current_variation")
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool failed")
        self.assertEqual(self.workspace.to_text(), root_before)
        self.assertEqual(self.workspace.view(), root_view)

        self.workspace.next_move()
        self.workspace.next_move()
        self.workspace.enter_variation(0)
        before = self.workspace.to_text()
        view = self.workspace.view()
        for arguments in (
            {"new_index": 99},
            {"new_index": True},
            {"new_index": 1, "extra": "x"},
        ):
            with self.subTest(arguments=arguments):
                result = self.execute(
                    "gametree.reorder_current_variation",
                    arguments,
                )
                self.assertFalse(result.ok)
                self.assertEqual(result.error, "tool failed")
                self.assertEqual(self.workspace.to_text(), before)
                self.assertEqual(self.workspace.view(), view)

    def test_multi_game_navigation_resets_cursor_without_editing_pgn(self) -> None:
        digest = self.workspace.content_digest
        self.assertTrue(self.execute("gametree.next_move").ok)

        selected = self.execute("gametree.select_game", {"index": 1})
        self.assertTrue(selected.ok, selected.error)
        self.assertEqual(selected.output["selectedGameIndex"], 1)
        self.assertEqual(selected.output["game"]["event"], "Tree Two")
        self.assertEqual(selected.output["cursor"]["nextMoveIndex"], 0)
        self.assertEqual(selected.output["currentMove"]["san"], "d4")

        failed = self.execute("gametree.next_game")
        self.assertFalse(failed.ok)
        self.assertEqual(self.workspace.selected_game_index, 1)

        back = self.execute("gametree.previous_game")
        self.assertTrue(back.ok, back.error)
        self.assertEqual(back.output["selectedGameIndex"], 0)
        self.assertEqual(self.workspace.content_digest, digest)
        self.assertFalse(self.workspace.dirty)


    def test_unknown_arguments_fail_closed_before_navigation(self) -> None:
        before = self.workspace.view()
        for tool_id, arguments in (
            ("gametree.current", {"unexpected": 1}),
            ("gametree.next_move", {"unexpected": 1}),
            ("gametree.enter_variation", {"variation_index": 0, "extra": True}),
            ("gametree.select_game", {"index": 1, "extra": "x"}),
        ):
            with self.subTest(tool_id=tool_id):
                result = self.execute(tool_id, arguments)
                self.assertFalse(result.ok)
                self.assertEqual(result.error, "tool failed")
                self.assertEqual(self.workspace.view(), before)

    def test_navigation_risk_is_explicit(self) -> None:
        specs = {spec.tool_id: spec for spec in self.executor.specs()}
        self.assertEqual(specs["gametree.current"].risk, ToolRisk.READ_ONLY)
        for tool_id in (
            "gametree.next_move",
            "gametree.previous_move",
            "gametree.enter_variation",
            "gametree.leave_variation",
            "gametree.sibling_variation",
            "gametree.select_game",
            "gametree.next_game",
            "gametree.previous_game",
            "gametree.promote_current_variation",
            "gametree.reorder_current_variation",
        ):
            self.assertEqual(specs[tool_id].risk, ToolRisk.LOCAL_WRITE)
        self.assertEqual(
            specs["gametree.delete_current_variation"].risk,
            ToolRisk.HIGH_IMPACT,
        )

    def test_main_registry_composes_same_gametree_adapter(self) -> None:
        executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=executor,
            board_provider=lambda: None,
            board_commands_provider=lambda: None,
            workspace_provider=lambda: self.workspace,
        ).register_all()
        ids = {spec.tool_id for spec in executor.specs()}
        self.assertTrue(
            {
                "gametree.current",
                "gametree.next_move",
                "gametree.previous_move",
                "gametree.enter_variation",
                "gametree.leave_variation",
                "gametree.sibling_variation",
                "gametree.select_game",
                "gametree.next_game",
                "gametree.previous_game",
                "gametree.promote_current_variation",
                "gametree.reorder_current_variation",
                "gametree.delete_current_variation",
            }.issubset(ids)
        )


    def test_universal_agent_executes_gametree_navigation_tool_loop(self) -> None:
        executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=executor,
            board_provider=lambda: None,
            board_commands_provider=lambda: None,
            workspace_provider=lambda: self.workspace,
        ).register_all()

        provider = _ScriptedProvider(
            [
                '{"type":"tool","tool_id":"gametree.next_move","arguments":{}}',
                '{"type":"tool","tool_id":"gametree.current","arguments":{}}',
                '{"type":"final","text":"The next move is e5."}',
            ]
        )
        gateway = ModelGateway()
        gateway.register(provider)
        runtime = UniversalChessAgentRuntime(
            gateway=gateway,
            tools=executor,
            provider_id="gametree-fixture",
            model="fixture-model",
            product_instruction="Use canonical Accessible Chess tools.",
        )

        result = asyncio.run(
            runtime.run(
                run_id="gametree-runtime",
                user_text="Move one step and tell me the next move.",
            )
        )

        self.assertEqual(result.text, "The next move is e5.")
        self.assertEqual(result.tool_calls, 2)
        self.assertEqual(result.model_calls, 3)
        self.assertEqual(self.workspace.cursor.next_move_index, 1)
        self.assertEqual(len(provider.requests), 3)
        tool_feedback = provider.requests[2].messages[-1]
        self.assertEqual(tool_feedback.role, "tool")
        self.assertIn('"tool_id":"gametree.current"', tool_feedback.content)
        self.assertIn('"san":"e5"', tool_feedback.content)

    def test_workspace_provider_must_return_exact_workspace(self) -> None:
        executor = ToolExecutor()
        register_gametree_tools(executor, lambda: object())
        result = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="wrong-workspace",
                    tool_id="gametree.current",
                    arguments={},
                )
            )
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool failed")


class _EffectGuard:
    def __init__(self) -> None:
        self.completed = False
        self.uncertain = False
        self.output = None

    def reserve(self, *, spec, call):
        return (spec.tool_id, call.call_id)

    def completed_output(self, _reservation):
        return False, None

    def complete(self, _reservation, output):
        self.completed = True
        self.output = output

    def mark_uncertain(self, _reservation):
        self.uncertain = True


if __name__ == "__main__":
    unittest.main()
