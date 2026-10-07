from __future__ import annotations

import asyncio
import unittest

from acs.acsdb import AcsDatabase
from acs.agent_tools import ToolCall, ToolExecutor, ToolRisk
from acs.chess_agent_tools import ChessAgentToolRegistry
from acs.chessbase_adapter import (
    component_extensions,
    primary_extensions,
    recognized_extensions,
)
from acs.chessbase_decoder import PROTOCOL_ID
from acs.chesscore import Board
from acs.format_import_report_service import FormatImportReportService


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


class AgentFormatImportReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = AcsDatabase(":memory:")
        self.executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=self.executor,
            board_provider=Board,
            board_commands_provider=lambda: None,
            format_report_service=FormatImportReportService(self.db),
        ).register_all()

    def tearDown(self) -> None:
        self.db.close()

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

    def import_game(self, event: str, source_name: str):
        return self.db.import_pgn_text(
            f'[Event "{event}"]\n[Result "*"]\n\n1. e4 *',
            source_name,
        )

    def test_single_report_is_path_safe_and_uses_persisted_authority(self) -> None:
        imported = self.import_game(
            "Private",
            r"C:\Users\owner\secret-folder\sample.pgn",
        )
        result = self.execute(
            "formats.import_report", {"attempt_id": imported.attempt_id}
        )
        self.assertTrue(result.ok, result.error)
        self.assertTrue(result.output["found"])
        report = result.output["report"]
        self.assertEqual(report["attemptId"], imported.attempt_id)
        self.assertEqual(report["sourceName"], "sample.pgn")
        self.assertEqual(report["sourceFormat"], "pgn")
        self.assertEqual(len(report["sourceSha256"]), 64)
        self.assertEqual(report["status"], "full")
        self.assertEqual(report["gameCount"], 1)
        self.assertEqual(report["warningCount"], 0)
        self.assertIsNone(report["errorMessage"])
        self.assertNotIn("secret-folder", str(report))

    def test_missing_report_is_explicit_without_fabrication(self) -> None:
        result = self.execute("formats.import_report", {"attempt_id": 999})
        self.assertTrue(result.ok, result.error)
        self.assertEqual(
            result.output,
            {"attemptId": 999, "found": False, "report": None},
        )

    def test_report_listing_uses_stable_keyset_paging_under_new_imports(self) -> None:
        first = self.import_game("A", "a.pgn")
        second = self.import_game("B", "b.pgn")
        third = self.import_game("C", "c.pgn")

        page = self.execute("formats.import_reports", {"limit": 2})
        self.assertTrue(page.ok, page.error)
        self.assertEqual(
            [item["attemptId"] for item in page.output["items"]],
            [third.attempt_id, second.attempt_id],
        )
        self.assertTrue(page.output["hasMore"])
        self.assertEqual(page.output["nextBeforeId"], second.attempt_id)

        later = self.import_game("D", "d.pgn")
        older = self.execute(
            "formats.import_reports",
            {"limit": 2, "before_id": page.output["nextBeforeId"]},
        )
        self.assertTrue(older.ok, older.error)
        self.assertEqual(
            [item["attemptId"] for item in older.output["items"]],
            [first.attempt_id],
        )
        self.assertNotIn(
            later.attempt_id,
            [item["attemptId"] for item in older.output["items"]],
        )
        self.assertFalse(older.output["hasMore"])
        self.assertIsNone(older.output["nextBeforeId"])

    def test_report_listing_filters_canonical_status(self) -> None:
        full = self.import_game("Good", "good.pgn")
        damaged = self.db.import_pgn_text("", "empty.pgn")
        page = self.execute(
            "formats.import_reports", {"status": "damaged", "limit": 10}
        )
        self.assertTrue(page.ok, page.error)
        self.assertEqual(
            [item["attemptId"] for item in page.output["items"]],
            [damaged.attempt_id],
        )
        self.assertNotEqual(full.attempt_id, damaged.attempt_id)

    def test_report_tools_are_read_only_and_accept_no_file_or_path_input(self) -> None:
        specs = {
            spec.tool_id: spec
            for spec in self.executor.specs()
            if spec.tool_id.startswith("formats.")
        }
        self.assertEqual(
            set(specs),
            {
                "formats.capabilities",
                "formats.chessbase_extension",
                "formats.import_report",
                "formats.import_reports",
            },
        )
        for spec in specs.values():
            self.assertIs(spec.risk, ToolRisk.READ_ONLY)
            self.assertNotIn("path", spec.input_schema)
            self.assertNotIn("file", spec.input_schema)

        for tool_id, arguments in (
            ("formats.import_report", {"attempt_id": 1, "path": "x.cbh"}),
            ("formats.import_reports", {"file": "x.cbh"}),
        ):
            with self.subTest(tool_id=tool_id):
                result = self.execute(tool_id, arguments)
                self.assertFalse(result.ok)
                self.assertIsNone(result.output)

    def test_report_argument_bounds_fail_closed(self) -> None:
        for arguments in (
            {"attempt_id": True},
            {"attempt_id": 0},
        ):
            with self.subTest(arguments=arguments):
                result = self.execute("formats.import_report", arguments)
                self.assertFalse(result.ok)

        with self.assertRaisesRegex(ValueError, "integer exceeds JSON safe range"):
            self.execute("formats.import_report", {"attempt_id": 1 << 63})

        for arguments in (
            {"status": "unknown"},
            {"status": 7},
            {"before_id": 0},
            {"before_id": True},
            {"limit": 0},
            {"limit": 101},
            {"limit": True},
        ):
            with self.subTest(arguments=arguments):
                result = self.execute("formats.import_reports", arguments)
                self.assertFalse(result.ok)

    def test_noncanonical_persisted_report_fails_closed(self) -> None:
        imported = self.import_game("Corrupt", "corrupt.pgn")
        with self.db.conn:
            self.db.conn.execute(
                "UPDATE import_attempts SET sha256=? WHERE id=?",
                ("not-a-canonical-digest", imported.attempt_id),
            )
        result = self.execute(
            "formats.import_report", {"attempt_id": imported.attempt_id}
        )
        self.assertFalse(result.ok)
        self.assertIsNone(result.output)


if __name__ == "__main__":
    unittest.main()
