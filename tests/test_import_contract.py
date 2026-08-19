import tempfile
import unittest
from pathlib import Path

from acs.import_contract import (
    ImportQuality,
    ImportedRecord,
    ImportReport,
    SourceFingerprint,
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

    def test_fingerprint_dto_rejects_scalar_and_digest_coercion(self):
        valid = ("/tmp/source.foo", 1, "0" * 64, ".foo")
        SourceFingerprint(*valid)
        invalid = (
            (True, 1, "0" * 64, ".foo"),
            ("/tmp/source.foo", True, "0" * 64, ".foo"),
            ("/tmp/source.foo", -1, "0" * 64, ".foo"),
            ("/tmp/source.foo", 1, b"0" * 64, ".foo"),
            ("/tmp/source.foo", 1, "A" * 64, ".foo"),
            ("/tmp/source.foo", 1, "0" * 63, ".foo"),
            ("/tmp/source.foo", 1, "0" * 64, ".FOO"),
            ("/tmp/source.foo", 1, "0" * 64, "foo/bar"),
        )
        for values in invalid:
            with self.subTest(fingerprint=values):
                with self.assertRaises((TypeError, ValueError)):
                    SourceFingerprint(*values)

    def test_record_and_report_shapes_are_typed_and_detached(self):
        record = ImportedRecord(
            "record-1",
            ImportQuality.WARNING,
            game_id=0,
            warnings=("metadata uncertain",),
        )
        for values in (
            (True, ImportQuality.FULL, None, "", ()),
            ("1", "full", None, "", ()),
            ("1", ImportQuality.FULL, True, "", ()),
            ("1", ImportQuality.FULL, -1, "", ()),
            ("1", ImportQuality.FULL, None, True, ()),
            ("1", ImportQuality.FULL, None, "", ["warning"]),
            ("1", ImportQuality.FULL, None, "", ("",)),
        ):
            with self.subTest(record=values):
                with self.assertRaises((TypeError, ValueError)):
                    ImportedRecord(*values)

        source = SourceFingerprint("/tmp/source.foo", 1, "0" * 64, ".foo")
        records = [record]
        warnings = ["source warning"]
        report = ImportReport(source, "Fake", records, warnings)
        records.clear()
        warnings.clear()
        self.assertEqual(report.records, [record])
        self.assertEqual(report.global_warnings, ["source warning"])

        report.records.append(object())
        with self.assertRaisesRegex(TypeError, "ImportedRecord"):
            report.validate()
        with self.assertRaisesRegex(TypeError, "ImportedRecord"):
            report.counts
        with self.assertRaisesRegex(TypeError, "ImportedRecord"):
            report.add(record)

    def test_fingerprint_chunk_and_summary_inputs_fail_before_false_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.foo"
            path.write_bytes(b"not empty")
            for chunk_size in (True, 0, -1, 1.5, "1"):
                with self.subTest(chunk_size=chunk_size):
                    with self.assertRaises((TypeError, ValueError)):
                        fingerprint(path, chunk_size=chunk_size)
            with self.assertRaisesRegex(TypeError, "path"):
                fingerprint(True)

            report = ImportReport(fingerprint(path), "Fake")
            with self.assertRaisesRegex(TypeError, "only ImportReport"):
                summarize_reports((report, object()))


if __name__ == '__main__':
    unittest.main()
