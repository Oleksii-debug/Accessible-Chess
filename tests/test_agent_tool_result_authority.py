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
    _MAX_TOOL_ARGUMENT_DEPTH,
    _MAX_TOOL_ARGUMENT_ITEMS,
    _MAX_TOOL_ARGUMENT_SERIALIZED_BYTES,
    _MAX_TOOL_ARGUMENT_SAFE_INTEGER,
    _MAX_TOOL_ARGUMENT_TEXT_BYTES,
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

    def test_tool_arguments_are_bounded_and_passively_canonicalized(self) -> None:
        deep: object = 0
        for _ in range(_MAX_TOOL_ARGUMENT_DEPTH + 1):
            deep = [deep]
        with self.assertRaisesRegex(ValueError, "maximum tool argument depth"):
            ToolCall(
                call_id="deep",
                tool_id="fixture.read",
                arguments={"value": deep},
            )

        with self.assertRaisesRegex(ValueError, "too many aggregate items"):
            ToolCall(
                call_id="wide",
                tool_id="fixture.read",
                arguments={"values": [0] * (_MAX_TOOL_ARGUMENT_ITEMS + 1)},
            )

        canonical = ToolCall(
            call_id="unicode",
            tool_id="fixture.read",
            arguments={"cafe\u0301": "re\u0301sume\u0301"},
        )
        self.assertEqual(dict(canonical.arguments), {"café": "résumé"})

    def test_tool_arguments_have_aggregate_text_budget_and_unicode_guard(self) -> None:
        with self.assertRaisesRegex(ValueError, "too much text"):
            ToolCall(
                call_id="huge-text",
                tool_id="fixture.read",
                arguments={"value": "x" * (_MAX_TOOL_ARGUMENT_TEXT_BYTES + 1)},
            )

        half = _MAX_TOOL_ARGUMENT_TEXT_BYTES // 2
        with self.assertRaisesRegex(ValueError, "too much text"):
            ToolCall(
                call_id="aggregate-text",
                tool_id="fixture.read",
                arguments={"first": "a" * half, "second": "b" * half},
            )

        with self.assertRaisesRegex(ValueError, "invalid Unicode"):
            ToolCall(
                call_id="surrogate",
                tool_id="fixture.read",
                arguments={"value": "\ud800"},
            )

    def test_tool_argument_integer_range_is_json_interoperable(self) -> None:
        for value in (-_MAX_TOOL_ARGUMENT_SAFE_INTEGER, _MAX_TOOL_ARGUMENT_SAFE_INTEGER):
            with self.subTest(value=value):
                call = ToolCall(
                    call_id="safe-int",
                    tool_id="fixture.read",
                    arguments={"value": value},
                )
                self.assertEqual(call.arguments["value"], value)

        for value in (
            -_MAX_TOOL_ARGUMENT_SAFE_INTEGER - 1,
            _MAX_TOOL_ARGUMENT_SAFE_INTEGER + 1,
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "JSON safe range"):
                    ToolCall(
                        call_id="unsafe-int",
                        tool_id="fixture.read",
                        arguments={"value": value},
                    )

    def test_tool_argument_real_serialized_payload_is_bounded(self) -> None:
        escaped_length = _MAX_TOOL_ARGUMENT_SERIALIZED_BYTES // 4
        self.assertLess(
            escaped_length + len("value"),
            _MAX_TOOL_ARGUMENT_TEXT_BYTES,
        )
        with self.assertRaisesRegex(ValueError, "serialized form is too large"):
            ToolCall(
                call_id="escaped-wire",
                tool_id="fixture.read",
                arguments={"value": "\x00" * escaped_length},
            )

        plain_length = min(
            _MAX_TOOL_ARGUMENT_TEXT_BYTES // 2,
            _MAX_TOOL_ARGUMENT_SERIALIZED_BYTES // 2,
        )
        call = ToolCall(
            call_id="plain-wire",
            tool_id="fixture.read",
            arguments={"value": "x" * plain_length},
        )
        self.assertEqual(len(call.arguments["value"]), plain_length)

    def test_tool_call_detaches_nested_arguments_before_fingerprinting(self) -> None:
        original = {"query": {"moves": ["e4"], "label": "cafe\u0301"}}
        call = ToolCall(
            call_id="detached",
            tool_id="fixture.read",
            arguments=original,
        )
        fingerprint = tool_arguments_fingerprint(call.arguments)

        original["query"]["moves"][0] = "d4"
        original["query"]["moves"].append("Nf3")
        original["query"]["label"] = "changed"

        nested = call.arguments["query"]
        self.assertEqual(
            dict(nested),
            {"moves": ("e4",), "label": "café"},
        )
        self.assertEqual(tool_arguments_fingerprint(call.arguments), fingerprint)

        with self.assertRaises(TypeError):
            nested["label"] = "mutated"
        with self.assertRaises(TypeError):
            nested["moves"][0] = "d4"
        self.assertEqual(tool_arguments_fingerprint(call.arguments), fingerprint)

    def test_tool_arguments_reject_active_mapping_and_list_subclasses(self) -> None:
        class ActiveMapping(dict):
            def items(self):
                raise AssertionError("active mapping was iterated")

        class ActiveList(list):
            def __iter__(self):
                raise AssertionError("active list was iterated")

        with self.assertRaisesRegex(TypeError, "passive built-in mapping"):
            ToolCall(
                call_id="active-mapping",
                tool_id="fixture.read",
                arguments=ActiveMapping(),
            )
        with self.assertRaisesRegex(TypeError, "unsupported active value type"):
            ToolCall(
                call_id="active-list",
                tool_id="fixture.read",
                arguments={"items": ActiveList([1, 2, 3])},
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
