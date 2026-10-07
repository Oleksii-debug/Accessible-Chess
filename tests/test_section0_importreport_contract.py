import tempfile
import unittest
from pathlib import Path

from acs.import_contract import ImportQuality, ImportedRecord, ImportReport, UnsupportedChessBaseImporter, fingerprint


class Section0ImportReportContractTests(unittest.TestCase):
    def test_unsupported_source_never_claims_a_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hostile.cbh"
            payload = b"not-a-valid-chess-database"
            path.write_bytes(payload)
            report = UnsupportedChessBaseImporter().inspect(path)
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(report.total, 1)
            record = report.records[0]
            self.assertIs(record.quality, ImportQuality.WARNING)
            self.assertIsNone(record.game_id)
            self.assertEqual(report.counts["full"], 0)
            self.assertEqual(report.counts["partial"], 0)
            self.assertEqual(report.counts["damaged"], 0)

    def test_quality_states_remain_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.pgn"
            path.write_bytes(b"x")
            report = ImportReport(source=fingerprint(path), format_name="contract")
            report.add(ImportedRecord("full", ImportQuality.FULL, game_id=1))
            report.add(ImportedRecord("partial", ImportQuality.PARTIAL, warnings=("bounded loss",)))
            report.add(ImportedRecord("damaged", ImportQuality.DAMAGED, message="corrupt record"))
            report.add(ImportedRecord("warning", ImportQuality.WARNING, message="unsupported semantics"))
            self.assertEqual(report.counts, {"full": 1, "partial": 1, "damaged": 1, "warning": 1})
            self.assertTrue(report.has_damage)

    def test_unknown_suffix_has_warning_and_no_fabricated_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unknown.bin"
            path.write_bytes(b"arbitrary")
            report = UnsupportedChessBaseImporter().inspect(path)
            self.assertEqual(report.total, 0)
            self.assertEqual(report.counts, {"full": 0, "partial": 0, "damaged": 0, "warning": 0})
            self.assertEqual(len(report.global_warnings), 1)


if __name__ == "__main__":
    unittest.main()
