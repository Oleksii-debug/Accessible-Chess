from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.import_contract import ImportQuality
from acs.pgn_service import PgnFileImporter


class Dev4PgnEncodingQualityTests(unittest.TestCase):
    """QA gate: lossy source decoding must not be counted as fully clean import."""

    def test_invalid_utf8_cannot_report_only_full_quality_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lossy.pgn"
            path.write_bytes(
                b'[Event "Lossy \xff source"]\n[Result "*"]\n\n1. e4 *\n'
            )

            report = PgnFileImporter().inspect(path)

            self.assertTrue(
                report.global_warnings,
                "Invalid UTF-8 replacement must remain explicit in import evidence.",
            )
            self.assertEqual(
                report.counts[ImportQuality.FULL.value],
                0,
                "A game parsed from lossy replacement-decoded source bytes must not be counted as FULL.",
            )
            self.assertGreaterEqual(
                report.counts[ImportQuality.WARNING.value]
                + report.counts[ImportQuality.PARTIAL.value]
                + report.counts[ImportQuality.DAMAGED.value],
                1,
                "Lossy source decoding must be represented in record-level quality, not only a side warning.",
            )


if __name__ == "__main__":
    unittest.main()
