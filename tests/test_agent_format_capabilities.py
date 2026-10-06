from __future__ import annotations

import asyncio
import unittest

from acs.agent_tools import ToolCall, ToolExecutor, ToolRisk
from acs.chess_agent_tools import ChessAgentToolRegistry
from acs.chessbase_adapter import (
    component_extensions,
    primary_extensions,
    recognized_extensions,
)
from acs.chessbase_decoder import PROTOCOL_ID
from acs.chesscore import Board


class AgentFormatCapabilitiesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=self.executor,
            board_provider=Board,
            board_commands_provider=lambda: None,
        ).register_all()

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

    def test_capabilities_delegate_to_canonical_chessbase_authority(self) -> None:
        result = self.execute("formats.capabilities")
        self.assertTrue(result.ok, result.error)
        chessbase = result.output["chessBase"]
        self.assertEqual(
            chessbase["recognizedExtensions"],
            list(recognized_extensions()),
        )
        self.assertEqual(
            chessbase["primaryExtensions"],
            list(primary_extensions()),
        )
        self.assertEqual(
            chessbase["componentExtensions"],
            list(component_extensions()),
        )
        self.assertEqual(chessbase["decoderProtocol"], PROTOCOL_ID)
        self.assertEqual(chessbase["decoderBackend"], "external_not_bundled")
        self.assertTrue(chessbase["sourceReadOnly"])
        self.assertTrue(chessbase["neutralOutputRequired"])

    def test_extension_classification_is_read_only_and_does_not_probe_paths(self) -> None:
        cbh = self.execute(
            "formats.chessbase_extension", {"extension": "CBH"}
        )
        self.assertTrue(cbh.ok, cbh.error)
        self.assertEqual(cbh.output["extension"], ".cbh")
        self.assertTrue(cbh.output["recognized"])
        self.assertTrue(cbh.output["primarySource"])
        self.assertFalse(cbh.output["componentOnly"])
        self.assertFalse(cbh.output["builtInSafeToImport"])

        cbg = self.execute(
            "formats.chessbase_extension", {"extension": ".CBG"}
        )
        self.assertTrue(cbg.ok, cbg.error)
        self.assertTrue(cbg.output["recognized"])
        self.assertFalse(cbg.output["primarySource"])
        self.assertTrue(cbg.output["componentOnly"])

        unknown = self.execute(
            "formats.chessbase_extension", {"extension": ".zip"}
        )
        self.assertTrue(unknown.ok, unknown.error)
        self.assertFalse(unknown.output["recognized"])
        self.assertFalse(unknown.output["primarySource"])
        self.assertFalse(unknown.output["componentOnly"])

    def test_format_tools_are_explicit_read_only_specs_without_path_inputs(self) -> None:
        specs = {
            spec.tool_id: spec
            for spec in self.executor.specs()
            if spec.tool_id.startswith("formats.")
        }
        self.assertEqual(
            set(specs),
            {"formats.capabilities", "formats.chessbase_extension"},
        )
        for spec in specs.values():
            self.assertIs(spec.risk, ToolRisk.READ_ONLY)
            self.assertNotIn("path", spec.input_schema)
            self.assertNotIn("file", spec.input_schema)

    def test_extension_grammar_accepts_canonical_ascii_family_names(self) -> None:
        for value, expected in (
            ("2CBH", ".2cbh"),
            (".CBONE", ".cbone"),
            ("cbv", ".cbv"),
        ):
            with self.subTest(value=value):
                result = self.execute(
                    "formats.chessbase_extension", {"extension": value}
                )
                self.assertTrue(result.ok, result.error)
                self.assertEqual(result.output["extension"], expected)
                self.assertTrue(result.output["recognized"])

    def test_invalid_extension_arguments_fail_closed(self) -> None:
        for value in (
            None,
            7,
            "",
            "cb h",
            "x" * 17,
            "../cbh",
            ".cbh/..",
            r"c:\base\cbh",
            ".cb-h",
            ".é",
            ".cbh\x00",
            "..",
        ):
            with self.subTest(value=value):
                result = self.execute(
                    "formats.chessbase_extension", {"extension": value}
                )
                self.assertFalse(result.ok)
                self.assertIsNone(result.output)
                self.assertTrue(result.error)

    def test_format_tools_reject_extra_or_unexpected_arguments(self) -> None:
        capabilities = self.execute(
            "formats.capabilities", {"path": "must-not-be-read.cbh"}
        )
        extension = self.execute(
            "formats.chessbase_extension",
            {"extension": ".cbh", "path": "must-not-be-read.cbh"},
        )

        self.assertFalse(capabilities.ok)
        self.assertFalse(extension.ok)
        self.assertIsNone(capabilities.output)
        self.assertIsNone(extension.output)


if __name__ == "__main__":
    unittest.main()
