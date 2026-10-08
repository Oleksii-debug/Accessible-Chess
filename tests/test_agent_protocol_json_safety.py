from __future__ import annotations

import math
import unittest

from acs.agent_model_gateway import ModelGateway
from acs.agent_tools import ToolExecutor
from acs.universal_chess_agent import (
    AgentProtocolError,
    AgentRunPolicy,
    AgentStepKind,
    UniversalChessAgentRuntime,
    _strict_step,
)


class _HostileInstruction(str):
    def strip(self, *_args: object, **_kwargs: object) -> str:
        raise AssertionError("hostile instruction hook must not run")


class AgentProtocolJsonSafetyTests(unittest.TestCase):
    def test_duplicate_top_level_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(AgentProtocolError, "duplicate JSON object keys"):
            _strict_step(
                '{"type":"final","type":"tool","text":"ok"}',
                max_chars=32_000,
            )

    def test_duplicate_nested_tool_argument_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(AgentProtocolError, "duplicate JSON object keys"):
            _strict_step(
                '{"type":"tool","tool_id":"board.current","arguments":{"square":"a1","square":"h8"}}',
                max_chars=32_000,
            )

    def test_non_standard_non_finite_json_numbers_are_rejected(self) -> None:
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(AgentProtocolError, "non-finite JSON number"):
                    _strict_step(
                        '{"type":"tool","tool_id":"board.current","arguments":{"value":'
                        + value
                        + "}}",
                        max_chars=32_000,
                    )

    def test_deep_json_is_normalized_to_protocol_error_not_recursion_error(self) -> None:
        raw = (
            '{"type":"tool","tool_id":"board.current","arguments":{"value":'
            + "[" * 1500
            + "0"
            + "]" * 1500
            + "}}"
        )
        with self.assertRaisesRegex(AgentProtocolError, "nesting is too deep"):
            _strict_step(raw, max_chars=32_000)

    def test_json_item_count_is_bounded_before_tool_execution(self) -> None:
        values = ",".join("0" for _ in range(5000))
        raw = (
            '{"type":"tool","tool_id":"board.current","arguments":{"values":['
            + values
            + "]}}"
        )
        with self.assertRaisesRegex(AgentProtocolError, "too many items"):
            _strict_step(raw, max_chars=32_000)

    def test_valid_nested_tool_arguments_remain_accepted(self) -> None:
        kind, tool_id, arguments = _strict_step(
            '{"type":"tool","tool_id":"board.current","arguments":{"outer":{"inner":1}}}',
            max_chars=32_000,
        )
        self.assertIs(kind, AgentStepKind.TOOL)
        self.assertEqual(tool_id, "board.current")
        self.assertEqual(arguments, {"outer": {"inner": 1}})

    def test_policy_rejects_non_finite_or_active_timeout_values(self) -> None:
        class HostileFloat(float):
            def __float__(self) -> float:
                raise AssertionError("hostile float hook must not run")

        for value in (math.nan, math.inf, -math.inf, HostileFloat(1.0)):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    AgentRunPolicy(model_timeout_seconds=value)

    def test_product_instruction_requires_passive_builtin_text_before_strip(self) -> None:
        with self.assertRaises(TypeError):
            UniversalChessAgentRuntime(
                gateway=ModelGateway(),
                tools=ToolExecutor(),
                provider_id="fixture",
                product_instruction=_HostileInstruction("fixture"),
            )


if __name__ == "__main__":
    unittest.main()
