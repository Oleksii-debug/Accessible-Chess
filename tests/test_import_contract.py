import tempfile
import unittest
from pathlib import Path

from acs.import_contract import (
    ImportQuality,
    ImportedRecord,
    ImportReport,
    UnsupportedChessBaseImporter,
    fingerprint,
    summarize_reports,
    verify_source_unchanged,
)


class ImportContractTests(unittest.TestCase):
    def test_fingerprint_and_unchanged_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sample.cbh'
            path.write_bytes(b'abc123')
            before = fingerprint(path)
            self.assertEqual(before.size, 6)
            self.assertTrue(verify_source_unchanged(before, path))
            path.write_bytes(b'abc124')
            self.assertFalse(verify_source_unchanged(before, path))

    def test_chessbase_placeholder_never_claims_full_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'database.cbh'
            original = b'not-a-real-cbh-but-must-remain-untouched'
            path.write_bytes(original)
            report = UnsupportedChessBaseImporter().inspect(path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(report.total, 1)
            self.assertEqual(report.records[0].quality, ImportQuality.WARNING)
            self.assertEqual(report.counts['full'], 0)
            self.assertEqual(report.counts['damaged'], 0)
            self.assertIn('decoder not implemented', report.records[0].message)

    def test_report_distinguishes_quality_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.pgn'
            path.write_text('x', encoding='utf-8')
            report = ImportReport(fingerprint(path), 'test')
            report.add(ImportedRecord('1', ImportQuality.FULL, game_id=10))
            report.add(ImportedRecord('2', ImportQuality.PARTIAL, warnings=('comment lost',)))
            report.add(ImportedRecord('3', ImportQuality.DAMAGED, message='move stream corrupt'))
            report.add(ImportedRecord('4', ImportQuality.WARNING, message='metadata uncertain'))
            self.assertEqual(report.counts, {'full': 1, 'partial': 1, 'damaged': 1, 'warning': 1})
            self.assertTrue(report.has_damage)

    def test_summary_keeps_categories_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'x.pgn'
            source.write_text('x', encoding='utf-8')
            a = ImportReport(fingerprint(source), 'a', [ImportedRecord('1', ImportQuality.FULL)])
            b = ImportReport(fingerprint(source), 'b', [ImportedRecord('2', ImportQuality.PARTIAL), ImportedRecord('3', ImportQuality.WARNING)])
            self.assertEqual(summarize_reports([a, b]), {'full': 1, 'partial': 1, 'damaged': 0, 'warning': 1})


if __name__ == '__main__':
    unittest.main()
