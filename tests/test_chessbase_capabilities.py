import json
import unittest

from acs.chessbase_adapter import probe_chessbase_source
from acs.chessbase_capabilities import (
    CAPABILITY_REPORT_SCHEMA_VERSION,
    chessbase_capabilities,
    chessbase_capability_report,
)


class ChessBaseCapabilityReportTests(unittest.TestCase):
    def test_report_uses_all_honest_statuses_and_is_json_safe(self):
        report = chessbase_capability_report()
        statuses = {item["status"] for item in report["capabilities"]}

        self.assertEqual(report["schema_version"], CAPABILITY_REPORT_SCHEMA_VERSION)
        self.assertEqual(
            statuses,
            {"SUPPORTED", "PARTIAL", "UNSUPPORTED", "CORRUPT", "BLOCKED"},
        )
        self.assertEqual(json.loads(json.dumps(report)), report)

    def test_opaque_payload_never_becomes_a_move_decode_claim(self):
        by_surface = {item.surface: item for item in chessbase_capabilities()}

        self.assertEqual(by_surface["classic-cbg-opaque-payload"].status, "PARTIAL")
        self.assertEqual(
            by_surface["classic-cbg-moves-variations-annotations"].status,
            "UNSUPPORTED",
        )
        self.assertEqual(
            by_surface["full-or-lossless-chessbase-import"].status,
            "BLOCKED",
        )

    def test_adapter_stays_fail_closed_until_canonical_move_decode_is_proven(self):
        report = chessbase_capability_report()
        probe = probe_chessbase_source("example.cbh")

        self.assertFalse(report["decoder_available"])
        self.assertFalse(report["safe_to_import"])
        self.assertFalse(probe.decoder_available)
        self.assertFalse(probe.safe_to_import)


if __name__ == "__main__":
    unittest.main()
