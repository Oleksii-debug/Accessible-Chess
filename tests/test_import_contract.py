import tempfile
import unittest
from pathlib import Path

import acs.import_contract as import_contract
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


class ActivePathCarrier:
    def __init__(self):
        self.called = False

    def __fspath__(self):
        self.called = True
        raise AssertionError('SourceFingerprint must reject path carrier before __fspath__')


class ActiveSuffix(str):
    lower_called = False

    def lower(self):
        type(self).lower_called = True
        raise AssertionError('SourceFingerprint must reject str subclass before lower')


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

        carrier = ActivePathCarrier()
        with self.assertRaises((TypeError, ValueError)):
            SourceFingerprint(
                path=carrier,  # type: ignore[arg-type]
                size=0,
                sha256='0' * 64,
                suffix='.pgn',
            )
        self.assertFalse(carrier.called)

        ActiveSuffix.lower_called = False
        with self.assertRaises((TypeError, ValueError)):
            SourceFingerprint(
                path='source.pgn',
                size=0,
                sha256='0' * 64,
                suffix=ActiveSuffix('.pgn'),
            )
        self.assertFalse(ActiveSuffix.lower_called)

    def test_canonical_fingerprint_remains_valid_passive_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.PGN'
            path.write_bytes(b'canonical')
            source = fingerprint(path)
            source.validate()
            self.assertIs(type(source.path), str)
            self.assertIs(type(source.size), int)
            self.assertEqual(source.suffix, '.pgn')
            self.assertEqual(len(source.sha256), 64)

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

    def test_import_report_diagnostic_metadata_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / 'bounded-report.pgn'
            source_path.write_text('x', encoding='utf-8')
            source = fingerprint(source_path)

            with self.assertRaisesRegex(ValueError, 'source_record_id is too long'):
                ImportedRecord(
                    'r' * (import_contract._MAX_IMPORT_RECORD_ID_CHARS + 1),
                    ImportQuality.FULL,
                )
            with self.assertRaisesRegex(ValueError, 'message is too long'):
                ImportedRecord(
                    'record-1',
                    ImportQuality.WARNING,
                    message='m' * (import_contract._MAX_IMPORT_MESSAGE_CHARS + 1),
                )
            with self.assertRaisesRegex(ValueError, 'warning text is too long'):
                ImportedRecord(
                    'record-1',
                    ImportQuality.WARNING,
                    warnings=('w' * (import_contract._MAX_IMPORT_WARNING_CHARS + 1),),
                )
            with self.assertRaisesRegex(ValueError, 'too many entries'):
                ImportedRecord(
                    'record-1',
                    ImportQuality.WARNING,
                    warnings=('warning',) * (
                        import_contract._MAX_IMPORT_WARNINGS_PER_RECORD + 1
                    ),
                )
            with self.assertRaisesRegex(ValueError, 'format_name is too long'):
                ImportReport(
                    source,
                    'f' * (import_contract._MAX_IMPORT_FORMAT_NAME_CHARS + 1),
                )

            report = ImportReport(source, 'bounded')
            report.global_warnings.extend(
                ['warning'] * (import_contract._MAX_IMPORT_GLOBAL_WARNINGS + 1)
            )
            with self.assertRaisesRegex(ValueError, 'too many entries'):
                report.validate()

    def test_report_revalidates_oversized_diagnostics_after_low_level_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / 'mutated-diagnostics.pgn'
            source_path.write_text('x', encoding='utf-8')
            record = ImportedRecord('record-1', ImportQuality.FULL)
            report = ImportReport(fingerprint(source_path), 'bounded', [record])

            object.__setattr__(
                record,
                'message',
                'm' * (import_contract._MAX_IMPORT_MESSAGE_CHARS + 1),
            )
            with self.assertRaisesRegex(ValueError, 'message is too long'):
                report.validate()

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

    def test_report_revalidates_frozen_record_scalars_after_low_level_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'mutated-record.pgn'
            source.write_text('x', encoding='utf-8')
            record = ImportedRecord('record-1', ImportQuality.FULL)
            report = ImportReport(fingerprint(source), 'test', [record])

            object.__setattr__(record, 'quality', 'partial')
            with self.assertRaisesRegex(TypeError, 'quality must be an ImportQuality'):
                report.validate()
            with self.assertRaisesRegex(TypeError, 'quality must be an ImportQuality'):
                _ = report.counts

    def test_report_revalidates_frozen_source_scalars_after_low_level_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'mutated-source.pgn'
            path.write_text('x', encoding='utf-8')
            source = fingerprint(path)
            report = ImportReport(source, 'test')

            object.__setattr__(source, 'sha256', 'not-a-digest')
            with self.assertRaisesRegex(ValueError, 'sha256'):
                report.validate()

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
