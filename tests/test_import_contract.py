import tempfile
import unittest
from pathlib import Path

from acs.import_contract import (
    ImportQuality,
    ImportedRecord,
    ImportReport,
    SourceFingerprint,
    SourceReadCancelledError,
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
            self.assertEqual(fingerprint(path, cancel_check=lambda: False), before)
            self.assertTrue(verify_source_unchanged(before, path))
            path.write_bytes(b'abc124')
            self.assertFalse(verify_source_unchanged(before, path))

    def test_fingerprint_cancel_check_stops_between_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'large.pgn'
            original = b'x' * (3 * 1024 * 1024 + 17)
            path.write_bytes(original)
            calls = 0

            def cancel_check():
                nonlocal calls
                calls += 1
                # Entry and the first 1 MiB read are allowed. The next chunk
                # poll cancels inside the first digest pass.
                return calls >= 3

            with self.assertRaises(SourceReadCancelledError):
                fingerprint(path, cancel_check=cancel_check)

            self.assertEqual(calls, 3)
            self.assertEqual(path.read_bytes(), original)

    def test_fingerprint_cancel_check_must_return_boolean(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'invalid-cancel.pgn'
            path.write_bytes(b'abc')
            with self.assertRaisesRegex(TypeError, 'must return a boolean'):
                fingerprint(path, cancel_check=lambda: 1)

    def test_source_fingerprint_rejects_non_passive_or_noncanonical_fields(self):
        valid = SourceFingerprint(
            path='C:/fixtures/source.pgn',
            size=0,
            sha256='0' * 64,
            suffix='.pgn',
        )
        valid.validate()

        invalid_values = (
            dict(path='', size=0, sha256='0' * 64, suffix='.pgn'),
            dict(path='bad\x00path.pgn', size=0, sha256='0' * 64, suffix='.pgn'),
            dict(path='source.pgn', size=True, sha256='0' * 64, suffix='.pgn'),
            dict(path='source.pgn', size=-1, sha256='0' * 64, suffix='.pgn'),
            dict(path='source.pgn', size=0, sha256='A' * 64, suffix='.pgn'),
            dict(path='source.pgn', size=0, sha256='0' * 63, suffix='.pgn'),
            dict(path='source.pgn', size=0, sha256='g' * 64, suffix='.pgn'),
            dict(path='source.pgn', size=0, sha256='0' * 64, suffix='pgn'),
            dict(path='source.pgn', size=0, sha256='0' * 64, suffix='.PGN'),
        )
        for fields in invalid_values:
            with self.subTest(fields=fields):
                with self.assertRaises((TypeError, ValueError)):
                    SourceFingerprint(**fields)

        with self.assertRaises((TypeError, ValueError)):
            SourceFingerprint(
                path=object(),  # type: ignore[arg-type]
                size=0,
                sha256='0' * 64,
                suffix='.pgn',
            )

    def test_report_revalidates_source_fingerprint_before_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.pgn'
            path.write_bytes(b'x')
            source = fingerprint(path)
            object.__setattr__(source, 'sha256', 'invalid')
            with self.assertRaisesRegex(ValueError, 'sha256'):
                ImportReport(source=source, format_name='test')

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
            self.assertIn('decoder is not configured', report.records[0].message)

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

    def test_non_full_records_require_explicit_loss_or_warning_evidence(self):
        for quality in (
            ImportQuality.PARTIAL,
            ImportQuality.DAMAGED,
            ImportQuality.WARNING,
        ):
            with self.subTest(quality=quality):
                with self.assertRaisesRegex(ValueError, 'must explain'):
                    ImportedRecord('record-1', quality)

        partial = ImportedRecord(
            'record-2',
            ImportQuality.PARTIAL,
            warnings=('one unsupported annotation was not imported',),
        )
        damaged = ImportedRecord(
            'record-3',
            ImportQuality.DAMAGED,
            message='move stream is malformed',
        )
        self.assertEqual(partial.quality, ImportQuality.PARTIAL)
        self.assertEqual(damaged.quality, ImportQuality.DAMAGED)

    def test_imported_record_rejects_active_or_ambiguous_scalar_shapes(self):
        with self.assertRaises(ValueError):
            ImportedRecord('', ImportQuality.FULL)
        with self.assertRaises(TypeError):
            ImportedRecord('1', 'full')  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            ImportedRecord('1', ImportQuality.FULL, game_id=True)
        with self.assertRaises(TypeError):
            ImportedRecord(
                '1',
                ImportQuality.WARNING,
                warnings=['warning'],  # type: ignore[arg-type]
            )
        with self.assertRaises(ValueError):
            ImportedRecord('1', ImportQuality.WARNING, warnings=('   ',))

    def test_report_revalidates_mutable_collections_before_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'mutated-report.pgn'
            source.write_text('x', encoding='utf-8')
            report = ImportReport(fingerprint(source), 'test')
            report.records.append(object())  # type: ignore[arg-type]
            with self.assertRaisesRegex(TypeError, 'exact ImportedRecord'):
                _ = report.counts

            clean = ImportReport(fingerprint(source), 'test')
            clean.global_warnings.append(' ')
            with self.assertRaisesRegex(ValueError, 'global_warnings'):
                clean.validate()

    def test_summary_keeps_categories_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'x.pgn'
            source.write_text('x', encoding='utf-8')
            a = ImportReport(fingerprint(source), 'a', [ImportedRecord('1', ImportQuality.FULL)])
            b = ImportReport(
                fingerprint(source),
                'b',
                [
                    ImportedRecord(
                        '2',
                        ImportQuality.PARTIAL,
                        warnings=('variation could not be represented',),
                    ),
                    ImportedRecord(
                        '3',
                        ImportQuality.WARNING,
                        message='metadata uncertain',
                    ),
                ],
            )
            self.assertEqual(summarize_reports([a, b]), {'full': 1, 'partial': 1, 'damaged': 0, 'warning': 1})


if __name__ == '__main__':
    unittest.main()
