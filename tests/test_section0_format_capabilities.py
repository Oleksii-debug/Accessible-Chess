from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from acs.format_capabilities import (
    CapabilityStatus,
    FORMAT_CAPABILITIES,
    capability_by_id,
    public_capability_payload,
    render_json,
    render_markdown,
    validate_format_capabilities,
)
from acs.import_contract import ImportQuality, UnsupportedChessBaseImporter


ROOT = Path(__file__).parents[1]
MARKDOWN_MATRIX = ROOT / "docs" / "automation" / "CANONICAL_FORMAT_CAPABILITY_MATRIX.md"
CHESSBASE_MATRIX = ROOT / "docs" / "automation" / "DEV4_CHESSBASE_CAPABILITY_MATRIX.md"
CBF_EVIDENCE = ROOT / "docs" / "automation" / "V2_CHESSBASE_CAPABILITIES.json"


class CanonicalFormatCapabilityContractTests(unittest.TestCase):
    def test_registry_is_valid_and_status_vocabulary_is_closed(self) -> None:
        validate_format_capabilities()
        self.assertEqual(
            {status.value for status in CapabilityStatus},
            {"SUPPORTED", "PARTIAL", "UNSUPPORTED", "BLOCKED"},
        )
        self.assertEqual(
            public_capability_payload()["status_vocabulary"],
            ["SUPPORTED", "PARTIAL", "UNSUPPORTED", "BLOCKED"],
        )

    def test_machine_readable_projection_is_canonical_json(self) -> None:
        payload = json.loads(render_json())
        self.assertEqual(payload, public_capability_payload())
        self.assertEqual(
            payload["authority"],
            "acs.format_capabilities.FORMAT_CAPABILITIES",
        )
        self.assertEqual(
            [item["id"] for item in payload["formats"]],
            [item.format_id for item in FORMAT_CAPABILITIES],
        )

    def test_checked_human_matrix_is_exact_generated_projection(self) -> None:
        self.assertEqual(MARKDOWN_MATRIX.read_text(encoding="utf-8"), render_markdown())
        rendered = MARKDOWN_MATRIX.read_text(encoding="utf-8")
        for required in ("Read", "Edit", "Write", "Round-trip", "PARTIAL", "BLOCKED"):
            self.assertIn(required, rendered)

    def test_early_format_contracts_do_not_overclaim_round_trip(self) -> None:
        fen = capability_by_id("fen")
        self.assertIn("acs.position_editor.PositionState", fen.authority)
        self.assertNotIn("position_text.PositionState", fen.authority)
        self.assertIn(
            "acs.position_editor.PositionState",
            capability_by_id("epd").authority,
        )
        self.assertEqual(
            (fen.read, fen.edit, fen.write, fen.round_trip),
            (
                CapabilityStatus.SUPPORTED,
                CapabilityStatus.PARTIAL,
                CapabilityStatus.SUPPORTED,
                CapabilityStatus.PARTIAL,
            ),
        )

        epd = capability_by_id("epd")
        self.assertIs(epd.read, CapabilityStatus.SUPPORTED)
        self.assertIs(epd.edit, CapabilityStatus.PARTIAL)
        self.assertIs(epd.round_trip, CapabilityStatus.PARTIAL)

        pgn = capability_by_id("pgn")
        self.assertIs(pgn.read, CapabilityStatus.SUPPORTED)
        self.assertIs(pgn.edit, CapabilityStatus.SUPPORTED)
        self.assertIs(pgn.write, CapabilityStatus.SUPPORTED)
        self.assertIs(pgn.round_trip, CapabilityStatus.PARTIAL)
        self.assertIn("malformed", pgn.boundary.casefold())

        acsdb = capability_by_id("acsdb")
        self.assertTrue(
            all(
                status is CapabilityStatus.PARTIAL
                for status in (acsdb.read, acsdb.edit, acsdb.write, acsdb.round_trip)
            )
        )

    def test_semantic_book_import_does_not_claim_source_writeback(self) -> None:
        for format_id in ("book-txt", "book-markdown", "book-html", "book-epub"):
            with self.subTest(format_id=format_id):
                item = capability_by_id(format_id)
                self.assertIs(item.read, CapabilityStatus.SUPPORTED)
                self.assertIs(item.edit, CapabilityStatus.UNSUPPORTED)
                self.assertIs(item.write, CapabilityStatus.UNSUPPORTED)
                self.assertIs(item.round_trip, CapabilityStatus.UNSUPPORTED)

    def test_optional_chessbase_read_paths_remain_partial_and_read_only(self) -> None:
        detailed = CHESSBASE_MATRIX.read_text(encoding="utf-8")
        self.assertIn(".cbh", detailed)
        self.assertIn("SUPPORTED WHEN CONFIGURED", detailed)
        self.assertIn("Chess960 / Fischer Random", detailed)
        self.assertIn("UNSUPPORTED", detailed)

        for format_id in ("chessbase-cbh", "chessbase-cbv"):
            with self.subTest(format_id=format_id):
                item = capability_by_id(format_id)
                self.assertEqual(item.availability, "optional_external_backend")
                self.assertIs(item.read, CapabilityStatus.PARTIAL)
                self.assertIs(item.edit, CapabilityStatus.UNSUPPORTED)
                self.assertIs(item.write, CapabilityStatus.UNSUPPORTED)
                self.assertIs(item.round_trip, CapabilityStatus.UNSUPPORTED)

    def test_cbf_cbi_and_unqualified_families_remain_blocked(self) -> None:
        evidence = json.loads(CBF_EVIDENCE.read_text(encoding="utf-8"))
        self.assertFalse(evidence["cbf_cbi_evidence"]["real_fixture_found"])
        self.assertFalse(
            evidence["cbf_cbi_evidence"]["independent_semantic_oracle_found"]
        )
        self.assertEqual(evidence["cbf_cbi_evidence"]["support_status"], "BLOCKED")

        for format_id in (
            "chessbase-cbf-cbi",
            "chessbase-2cbh",
            "chessbase-cbone",
            "chessbase-cbz",
        ):
            with self.subTest(format_id=format_id):
                item = capability_by_id(format_id)
                self.assertEqual(item.availability, "blocked_external_evidence")
                self.assertIs(item.read, CapabilityStatus.BLOCKED)
                self.assertIs(item.edit, CapabilityStatus.UNSUPPORTED)
                self.assertIs(item.write, CapabilityStatus.UNSUPPORTED)
                self.assertIs(item.round_trip, CapabilityStatus.UNSUPPORTED)

    def test_no_duplicate_format_or_extension_authority(self) -> None:
        self.assertEqual(
            len({item.format_id for item in FORMAT_CAPABILITIES}),
            len(FORMAT_CAPABILITIES),
        )
        extensions = [
            extension
            for item in FORMAT_CAPABILITIES
            for extension in item.extensions
        ]
        self.assertEqual(len(set(extensions)), len(extensions))

    def test_unsupported_chessbase_placeholder_reports_without_mutating_source(self) -> None:
        importer = UnsupportedChessBaseImporter()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "legacy.cbf"
            source.write_bytes(b"fixture-not-a-decoder-proof")
            before = source.read_bytes()
            before_digest = hashlib.sha256(before).hexdigest()

            report = importer.inspect(source)

            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(report.source.sha256, before_digest)
            self.assertEqual(report.total, 1)
            self.assertIs(report.records[0].quality, ImportQuality.WARNING)
            self.assertIn("decoder is not configured", report.records[0].message)
            self.assertFalse(report.has_damage)

    def test_unknown_capability_and_operation_fail_closed(self) -> None:
        with self.assertRaises(KeyError):
            capability_by_id("invented-format")
        with self.assertRaises(TypeError):
            capability_by_id(object())  # type: ignore[arg-type]
        with self.assertRaises(KeyError):
            capability_by_id("fen").operation_status("decode-magic")


if __name__ == "__main__":
    unittest.main()
