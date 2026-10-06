from __future__ import annotations

import asyncio
import math
import unittest

from acs.agent_tools import (
    ToolAuthorization,
    ToolCall,
    ToolExecutor,
    ToolRisk,
    ToolSpec,
    _MAX_TOOL_RESULT_SERIALIZED_BYTES,
    _MAX_TOOL_RESULT_SAFE_INTEGER,
    _MAX_TOOL_RESULT_TEXT_BYTES,
    tool_arguments_fingerprint,
)


class AgentToolResultAuthorityTests(unittest.TestCase):
    def execute_read_output(self, output: object):
        executor = ToolExecutor()

        async def handler(_arguments):
            return output

        executor.register(ToolSpec("fixture.read", "Read fixture."), handler)
        return asyncio.run(
            executor.execute(
                ToolCall(call_id="call-read", tool_id="fixture.read", arguments={})
            )
        )

    def test_nested_handler_output_is_detached_before_publication(self) -> None:
        source = {
            "nested": {"moves": [{"san": "e4"}]},
            "labels": ["one", "two"],
        }
        result = self.execute_read_output(source)
        self.assertTrue(result.ok)

        source["nested"]["moves"][0]["san"] = "d4"
        source["nested"]["moves"].append({"san": "Nf3"})
        source["labels"].append("three")

        self.assertEqual(result.output["nested"]["moves"], [{"san": "e4"}])
        self.assertEqual(result.output["labels"], ["one", "two"])

    def test_active_custom_or_non_finite_output_fails_closed(self) -> None:
        class ActiveText(str):
            pass

        for output in (
            {"value": object()},
            {"value": ActiveText("active")},
            {"value": math.nan},
            {"value": math.inf},
            {1: "non-text-key"},
        ):
            with self.subTest(output=output):
                result = self.execute_read_output(output)
                self.assertFalse(result.ok)
                self.assertEqual(result.error, "tool result not safe")
                self.assertIsNone(result.output)

    def test_tool_output_structure_is_bounded(self) -> None:
        deep: object = 0
        for _ in range(34):
            deep = [deep]
        result = self.execute_read_output({"value": deep})
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool result not safe")

        result = self.execute_read_output({"values": [0] * 4097})
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool result not safe")

    def test_tool_output_text_budget_is_aggregate_and_bounded(self) -> None:
        too_large = "x" * (_MAX_TOOL_RESULT_TEXT_BYTES + 1)
        result = self.execute_read_output({"value": too_large})
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool result not safe")

        half = _MAX_TOOL_RESULT_TEXT_BYTES // 2
        result = self.execute_read_output(
            {"first": "a" * half, "second": "b" * half}
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool result not safe")

    def test_tool_output_integer_range_is_json_interoperable(self) -> None:
        for value in (-_MAX_TOOL_RESULT_SAFE_INTEGER, _MAX_TOOL_RESULT_SAFE_INTEGER):
            with self.subTest(value=value):
                result = self.execute_read_output({"value": value})
                self.assertTrue(result.ok)
                self.assertEqual(result.output, {"value": value})

        for value in (
            -_MAX_TOOL_RESULT_SAFE_INTEGER - 1,
            _MAX_TOOL_RESULT_SAFE_INTEGER + 1,
        ):
            with self.subTest(value=value):
                result = self.execute_read_output({"value": value})
                self.assertFalse(result.ok)
                self.assertEqual(result.error, "tool result not safe")
                self.assertIsNone(result.output)

    def test_real_serialized_payload_is_bounded_after_json_escaping(self) -> None:
        escaped_length = _MAX_TOOL_RESULT_SERIALIZED_BYTES // 4
        self.assertLess(escaped_length + len("value"), _MAX_TOOL_RESULT_TEXT_BYTES)
        result = self.execute_read_output({"value": "\x00" * escaped_length})
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool result not safe")
        self.assertIsNone(result.output)

        plain_length = min(
            _MAX_TOOL_RESULT_TEXT_BYTES // 2,
            _MAX_TOOL_RESULT_SERIALIZED_BYTES // 2,
        )
        result = self.execute_read_output({"value": "x" * plain_length})
        self.assertTrue(result.ok)
        self.assertEqual(len(result.output["value"]), plain_length)

    def test_tool_output_text_and_keys_are_nfc_canonical(self) -> None:
        result = self.execute_read_output(
            {"cafe\u0301": "re\u0301sume\u0301"}
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.output, {"café": "résumé"})

    def test_tool_output_rejects_duplicate_normalized_keys(self) -> None:
        result = self.execute_read_output(
            {"é": "first", "e\u0301": "second"}
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool result not safe")
        self.assertIsNone(result.output)

    def test_tool_output_rejects_unsafe_unicode_text(self) -> None:
        result = self.execute_read_output({"value": "\ud800"})
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool result not safe")

    def test_external_effect_with_unsafe_fresh_output_is_marked_uncertain(self) -> None:
        guard = _EffectGuard()

        async def approval(spec, call):
            return ToolAuthorization(
                tool_id=spec.tool_id,
                task_id=call.task_id,
                risk=spec.risk,
                arguments_fingerprint=tool_arguments_fingerprint(call.arguments),
                effect_fingerprint="effect",
                approval_fingerprint="approval",
            )

        async def handler(_arguments):
            return {"value": object()}

        executor = ToolExecutor(approval_policy=approval, effect_guard=guard)
        executor.register(
            ToolSpec(
                "fixture.external",
                "External fixture.",
                risk=ToolRisk.EXTERNAL_SIDE_EFFECT,
            ),
            handler,
        )
        result = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="call-external",
                    tool_id="fixture.external",
                    arguments={},
                    task_id="task-1",
                )
            )
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool result not safe")
        self.assertTrue(guard.uncertain)
        self.assertFalse(guard.completed)

    def test_completed_external_effect_output_is_revalidated_without_replay(self) -> None:
        guard = _EffectGuard(completed_output={"value": object()})

        async def approval(spec, call):
            return ToolAuthorization(
                tool_id=spec.tool_id,
                task_id=call.task_id,
                risk=spec.risk,
                arguments_fingerprint=tool_arguments_fingerprint(call.arguments),
                effect_fingerprint="effect",
                approval_fingerprint="approval",
            )

        calls = []

        async def handler(_arguments):
            calls.append(True)
            return {"should": "not execute"}

        executor = ToolExecutor(approval_policy=approval, effect_guard=guard)
        executor.register(
            ToolSpec(
                "fixture.external",
                "External fixture.",
                risk=ToolRisk.EXTERNAL_SIDE_EFFECT,
            ),
            handler,
        )
        result = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="call-replay",
                    tool_id="fixture.external",
                    arguments={},
                    task_id="task-2",
                )
            )
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool result not safe")
        self.assertEqual(calls, [])
        self.assertFalse(guard.uncertain)


class _EffectGuard:
    def __init__(self, completed_output: object | None = None) -> None:
        self._completed_output = completed_output
        self.completed = False
        self.uncertain = False

    def reserve(self, *, spec, call):
        return (spec.tool_id, call.call_id)

    def completed_output(self, _reservation):
        if self._completed_output is None:
            return False, None
        return True, self._completed_output

    def complete(self, _reservation, _output):
        self.completed = True

    def mark_uncertain(self, _reservation):
        self.uncertain = True


if __name__ == "__main__":
    unittest.main()
