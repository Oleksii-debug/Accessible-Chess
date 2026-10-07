import tempfile
import unittest
from pathlib import Path

from acs.import_contract import (
    ImportQuality,
    ImportReport,
    ImportedRecord,
    SourceFingerprint,
    SourceReadCancelledError,
    fingerprint,
)
from acs.import_registry import (
    ImportRegistry,
    ImportRegistryError,
    SourceMutationError,
    SourceProvenanceError,
)


class FakeImporter:
    format_name = 'Fake format'
    suffixes = ('.foo', '.bar')

    def inspect(self, path: Path) -> ImportReport:
        report = ImportReport(source=fingerprint(path), format_name=self.format_name)
        report.add(ImportedRecord('1', ImportQuality.FULL, message='ok'))
        return report


class SecondFooImporter:
    format_name = 'Second fake'
    suffixes = ('.foo',)

    def inspect(self, path: Path) -> ImportReport:
        return ImportReport(source=fingerprint(path), format_name=self.format_name)


class MutatingImporter:
    format_name = 'Unsafe mutating fake'
    suffixes = ('.mut',)

    def inspect(self, path: Path) -> ImportReport:
        before = fingerprint(path)
        path.write_bytes(path.read_bytes() + b' changed')
        return ImportReport(source=before, format_name=self.format_name)


class MutatingThenErrorImporter:
    format_name = 'Mutating then failing fake'
    suffixes = ('.muterr',)

    def inspect(self, path: Path) -> ImportReport:
        path.write_bytes(path.read_bytes() + b' changed-before-error')
        raise RuntimeError('decoder failed after source mutation')


class DeletingImporter:
    format_name = 'Deleting fake'
    suffixes = ('.delete',)

    def inspect(self, path: Path) -> ImportReport:
        before = fingerprint(path)
        path.unlink()
        return ImportReport(source=before, format_name=self.format_name)


class FalseProvenanceImporter:
    format_name = 'False provenance fake'
    suffixes = ('.lie',)

    def inspect(self, path: Path) -> ImportReport:
        actual = fingerprint(path)
        false_source = SourceFingerprint(
            path=actual.path,
            size=actual.size,
            sha256='0' * 64,
            suffix=actual.suffix,
        )
        return ImportReport(source=false_source, format_name=self.format_name)


class MislabelledFormatImporter:
    format_name = 'Canonical fake format'
    suffixes = ('.mislabel',)

    def inspect(self, path: Path) -> ImportReport:
        return ImportReport(
            source=fingerprint(path),
            format_name='Different format label',
            records=[ImportedRecord('1', ImportQuality.FULL)],
        )


class MutableFormatNameImporter:
    format_name = 'Original registered format'
    suffixes = ('.mutable-format-name',)

    def inspect(self, path: Path) -> ImportReport:
        return ImportReport(
            source=fingerprint(path),
            format_name=self.format_name,
            records=[ImportedRecord('1', ImportQuality.FULL)],
        )


class InvalidFormatNameImporter:
    format_name = ''
    suffixes = ('.invalid-format-name',)

    def inspect(self, path: Path) -> ImportReport:
        return ImportReport(source=fingerprint(path), format_name='fallback')


class ActiveFakeReport:
    @property
    def source(self):
        raise AssertionError('registry must reject non-ImportReport before field access')


class NonReportImporter:
    format_name = 'Active fake report'
    suffixes = ('.active-report',)

    def inspect(self, path: Path):
        return ActiveFakeReport()


class CorruptReportImporter:
    format_name = 'Corrupt report'
    suffixes = ('.corrupt-report',)

    def inspect(self, path: Path) -> ImportReport:
        report = ImportReport(source=fingerprint(path), format_name=self.format_name)
        report.records.append(object())  # type: ignore[arg-type]
        return report


class ConstructionTypeErrorImporter:
    format_name = 'Malformed construction report'
    suffixes = ('.type-report',)

    def inspect(self, path: Path) -> ImportReport:
        return ImportReport(
            source=fingerprint(path),
            format_name=self.format_name,
            records=(ImportedRecord('1', ImportQuality.FULL),),  # type: ignore[arg-type]
        )


class KeyErrorImporter:
    format_name = 'Unexpected key failure'
    suffixes = ('.key-error',)

    def inspect(self, path: Path) -> ImportReport:
        raise KeyError()


class IndexErrorImporter:
    format_name = 'Unexpected index failure'
    suffixes = ('.index-error',)

    def inspect(self, path: Path) -> ImportReport:
        raise IndexError('decoder record index out of range')


class BrokenStringError(Exception):
    def __str__(self) -> str:
        raise RuntimeError('exception rendering failed')


class BrokenStringImporter:
    format_name = 'Broken exception rendering'
    suffixes = ('.broken-str',)

    def inspect(self, path: Path) -> ImportReport:
        raise BrokenStringError()


class InvalidStringError(Exception):
    def __str__(self):  # type: ignore[override]
        return object()


class InvalidStringImporter:
    format_name = 'Invalid exception rendering'
    suffixes = ('.invalid-str',)

    def inspect(self, path: Path) -> ImportReport:
        raise InvalidStringError()


class NamelessStringError(Exception):
    def __str__(self) -> str:
        return ''


NamelessStringError.__name__ = ''


class NamelessStringImporter:
    format_name = 'Nameless exception rendering'
    suffixes = ('.nameless-str',)

    def inspect(self, path: Path) -> ImportReport:
        raise NamelessStringError()


class CooperativeCancelImporter:
    format_name = 'Cooperative source cancellation'
    suffixes = ('.cancel-source',)

    def inspect(self, path: Path) -> ImportReport:
        raise SourceReadCancelledError('source read cancelled')


class ObservedAfterCancelImporter:
    format_name = 'Must not run after cancel'
    suffixes = ('.after-cancel',)

    def __init__(self) -> None:
        self.calls = 0

    def inspect(self, path: Path) -> ImportReport:
        self.calls += 1
        return ImportReport(source=fingerprint(path), format_name=self.format_name)


class ProcessControlImporter:
    format_name = 'Process control passthrough'
    suffixes = ('.interrupt',)

    def inspect(self, path: Path) -> ImportReport:
        raise KeyboardInterrupt()


class LowLevelMutatedRecordImporter:
    format_name = 'Low-level mutated exact report'
    suffixes = ('.mutated-record',)

    def inspect(self, path: Path) -> ImportReport:
        record = ImportedRecord('record-1', ImportQuality.FULL)
        report = ImportReport(
            source=fingerprint(path),
            format_name=self.format_name,
            records=[record],
        )
        object.__setattr__(record, 'quality', 'warning')
        return report


class LowLevelMutatedSourceImporter:
    format_name = 'Low-level mutated exact source'
    suffixes = ('.mutated-source',)

    def inspect(self, path: Path) -> ImportReport:
        source = fingerprint(path)
        report = ImportReport(source=source, format_name=self.format_name)
        object.__setattr__(source, 'sha256', 'bad')
        return report


class ImportRegistryTests(unittest.TestCase):
    def test_registration_rejects_non_text_suffix_before_normalization_hooks(self):
        class ActiveSuffix(str):
            def strip(self, *args, **kwargs):
                raise AssertionError('strip hook must not run')

        class ActiveSuffixImporter:
            format_name = 'Active suffix'
            suffixes = (ActiveSuffix('.active'),)

            def inspect(self, path: Path) -> ImportReport:
                raise AssertionError('inspection must not run')

        with self.assertRaisesRegex(ImportRegistryError, 'exact text'):
            ImportRegistry().register(ActiveSuffixImporter())

    def test_registration_routes_case_insensitive_suffixes_without_ui_or_database_knowledge(self):
        registry = ImportRegistry()
        importer = FakeImporter()
        registration = registry.register(importer)
        self.assertEqual(registration.suffixes, ('.foo', '.bar'))
        self.assertIs(registry.importer_for('Example.FOO'), importer)
        self.assertIs(registry.importer_for('x.bar'), importer)
        self.assertEqual(registry.registered_suffixes, ('.bar', '.foo'))

    def test_duplicate_suffix_is_rejected_instead_of_silently_changing_decoder(self):
        registry = ImportRegistry()
        first = FakeImporter()
        registry.register(first)
        with self.assertRaises(ImportRegistryError):
            registry.register(SecondFooImporter())
        self.assertIs(registry.importer_for('x.foo'), first)

    def test_explicit_replace_is_supported_for_verified_adapter_upgrade(self):
        registry = ImportRegistry()
        registry.register(FakeImporter())
        replacement = SecondFooImporter()
        registry.register(replacement, replace=True)
        self.assertIs(registry.importer_for('x.foo'), replacement)
        self.assertIsNotNone(registry.importer_for('x.bar'))

    def test_replace_updates_registered_format_identity_atomically(self):
        registry = ImportRegistry()
        registry.register(FakeImporter())
        replacement = SecondFooImporter()
        registry.register(replacement, replace=True)

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'source.foo'
            path.write_bytes(b'replacement-source')
            report = registry.inspect(path)

        self.assertEqual(report.format_name, replacement.format_name)

    def test_unknown_source_is_explicit_error_not_silent_drop(self):
        registry = ImportRegistry()
        registry.register(FakeImporter())
        with self.assertRaises(ImportRegistryError) as ctx:
            registry.inspect('x.unknown')
        self.assertIn('.unknown', str(ctx.exception))

    def test_inspection_preserves_read_only_source_bytes_and_provenance(self):
        registry = ImportRegistry()
        registry.register(FakeImporter())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'sample.foo'
            original = b'immutable source bytes'
            path.write_bytes(original)
            report = registry.inspect(path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(report.total, 1)
            self.assertEqual(report.counts['full'], 1)
            self.assertEqual(report.source.path, str(path.resolve()))
            self.assertEqual(report.source.sha256, fingerprint(path).sha256)

    def test_registry_detects_source_mutation_even_when_adapter_reports_old_fingerprint(self):
        registry = ImportRegistry()
        registry.register(MutatingImporter())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'sample.mut'
            path.write_bytes(b'original')
            with self.assertRaises(SourceMutationError):
                registry.inspect(path)
            self.assertEqual(path.read_bytes(), b'original changed')

    def test_registry_detects_mutation_even_when_adapter_then_raises(self):
        registry = ImportRegistry()
        registry.register(MutatingThenErrorImporter())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'sample.muterr'
            path.write_bytes(b'original')

            with self.assertRaises(SourceMutationError) as ctx:
                registry.inspect(path)

            self.assertIn('modified source bytes', str(ctx.exception))
            self.assertEqual(path.read_bytes(), b'original changed-before-error')

    def test_batch_reports_mutation_before_adapter_error_and_continues(self):
        registry = ImportRegistry()
        registry.register(MutatingThenErrorImporter())
        registry.register(FakeImporter())
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mutating = root / 'bad.muterr'
            valid = root / 'good.foo'
            mutating.write_bytes(b'original')
            valid.write_bytes(b'valid-source')

            batch = registry.inspect_batch([mutating, valid])

            self.assertEqual([item.ok for item in batch.items], [False, True])
            self.assertIn('modified source bytes', batch.items[0].error)
            self.assertNotIn('decoder failed after source mutation', batch.items[0].error)
            self.assertEqual(len(batch.reports), 1)
            self.assertEqual(batch.reports[0].format_name, FakeImporter.format_name)
            self.assertEqual(valid.read_bytes(), b'valid-source')

    def test_registry_fails_closed_when_adapter_deletes_source_before_return(self):
        registry = ImportRegistry()
        registry.register(DeletingImporter())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'sample.delete'
            path.write_bytes(b'original')

            with self.assertRaises(SourceMutationError) as ctx:
                registry.inspect(path)

            self.assertIn('unverifiable', str(ctx.exception))
            self.assertFalse(path.exists())

    def test_registry_rejects_report_for_bytes_other_than_inspected_source(self):
        registry = ImportRegistry()
        registry.register(FalseProvenanceImporter())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'sample.lie'
            path.write_bytes(b'original')
            with self.assertRaises(SourceProvenanceError):
                registry.inspect(path)
            self.assertEqual(path.read_bytes(), b'original')

    def test_batch_records_mutation_and_provenance_failures_without_hiding_later_sources(self):
        registry = ImportRegistry()
        registry.register(FakeImporter())
        registry.register(MutatingImporter())
        registry.register(FalseProvenanceImporter())
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mutating = root / 'bad.mut'
            lying = root / 'bad.lie'
            valid = root / 'good.foo'
            mutating.write_bytes(b'm')
            lying.write_bytes(b'l')
            valid.write_bytes(b'good')

            batch = registry.inspect_batch([mutating, lying, valid])

            self.assertEqual([item.ok for item in batch.items], [False, False, True])
            self.assertIn('modified source bytes', batch.items[0].error)
            self.assertIn('provenance does not match', batch.items[1].error)
            self.assertEqual(len(batch.reports), 1)
            self.assertEqual(batch.reports[0].source.sha256, fingerprint(valid).sha256)

    def test_registration_rejects_missing_canonical_format_identity(self):
        registry = ImportRegistry()
        with self.assertRaisesRegex(ImportRegistryError, 'format_name'):
            registry.register(InvalidFormatNameImporter())

    def test_registry_binds_format_identity_at_registration_time(self):
        registry = ImportRegistry()
        importer = MutableFormatNameImporter()
        registry.register(importer)
        importer.format_name = 'Changed after registration'

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'source.mutable-format-name'
            original = b'registration-time-format-identity'
            path.write_bytes(original)

            with self.assertRaisesRegex(ImportRegistryError, 'format identity'):
                registry.inspect(path)

            self.assertEqual(path.read_bytes(), original)

    def test_registry_rejects_report_with_different_format_identity(self):
        registry = ImportRegistry()
        registry.register(MislabelledFormatImporter())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'source.mislabel'
            original = b'format-identity-source'
            path.write_bytes(original)

            with self.assertRaisesRegex(ImportRegistryError, 'format identity'):
                registry.inspect(path)

            self.assertEqual(path.read_bytes(), original)

    def test_batch_isolates_mislabelled_format_and_continues(self):
        registry = ImportRegistry()
        registry.register(MislabelledFormatImporter())
        registry.register(FakeImporter())

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bad = root / 'bad.mislabel'
            good = root / 'good.foo'
            bad.write_bytes(b'mislabelled-source')
            good.write_bytes(b'valid-source')

            batch = registry.inspect_batch([bad, good])

            self.assertEqual([item.ok for item in batch.items], [False, True])
            self.assertIn('format identity', batch.items[0].error)
            self.assertIsNone(batch.items[0].report)
            self.assertEqual(len(batch.reports), 1)
            self.assertEqual(batch.reports[0].format_name, FakeImporter.format_name)
            self.assertEqual(bad.read_bytes(), b'mislabelled-source')
            self.assertEqual(good.read_bytes(), b'valid-source')

    def test_registry_rejects_non_report_before_active_field_access(self):
        registry = ImportRegistry()
        registry.register(NonReportImporter())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'source.active-report'
            path.write_bytes(b'unchanged')
            with self.assertRaisesRegex(ImportRegistryError, 'exact passive ImportReport'):
                registry.inspect(path)
            self.assertEqual(path.read_bytes(), b'unchanged')

    def test_registry_rejects_mutated_report_collections_as_invalid_contract(self):
        registry = ImportRegistry()
        registry.register(CorruptReportImporter())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'source.corrupt-report'
            path.write_bytes(b'unchanged')
            with self.assertRaisesRegex(ImportRegistryError, 'invalid ImportReport'):
                registry.inspect(path)
            self.assertEqual(path.read_bytes(), b'unchanged')

    def test_batch_isolates_report_construction_type_error_and_continues(self):
        registry = ImportRegistry()
        registry.register(ConstructionTypeErrorImporter())
        registry.register(FakeImporter())
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            malformed = root / 'bad.type-report'
            valid = root / 'good.foo'
            malformed.write_bytes(b'malformed-report-source')
            valid.write_bytes(b'valid-source')

            batch = registry.inspect_batch([malformed, valid])

            self.assertEqual([item.ok for item in batch.items], [False, True])
            self.assertIn('exact list', batch.items[0].error)
            self.assertIsNone(batch.items[0].report)
            self.assertIsNotNone(batch.items[1].report)
            self.assertEqual(batch.items[1].report.counts['full'], 1)
            self.assertEqual(malformed.read_bytes(), b'malformed-report-source')
            self.assertEqual(valid.read_bytes(), b'valid-source')

    def test_batch_isolates_ordinary_importer_exceptions_and_continues(self):
        registry = ImportRegistry()
        registry.register(KeyErrorImporter())
        registry.register(IndexErrorImporter())
        registry.register(FakeImporter())

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            key_failure = root / 'bad.key-error'
            index_failure = root / 'bad.index-error'
            valid = root / 'good.foo'
            key_failure.write_bytes(b'key-error-source')
            index_failure.write_bytes(b'index-error-source')
            valid.write_bytes(b'valid-source')

            batch = registry.inspect_batch([key_failure, index_failure, valid])

            self.assertEqual([item.ok for item in batch.items], [False, False, True])
            self.assertEqual(batch.items[0].error, 'KeyError')
            self.assertIn('decoder record index out of range', batch.items[1].error)
            self.assertIsNone(batch.items[0].report)
            self.assertIsNone(batch.items[1].report)
            self.assertIsNotNone(batch.items[2].report)
            self.assertEqual(len(batch.reports), 1)
            self.assertEqual(len(batch.errors), 2)
            self.assertEqual(key_failure.read_bytes(), b'key-error-source')
            self.assertEqual(index_failure.read_bytes(), b'index-error-source')
            self.assertEqual(valid.read_bytes(), b'valid-source')

            # The strict single-source API remains strict and still exposes
            # the adapter failure to callers that explicitly chose it.
            with self.assertRaises(KeyError):
                registry.inspect(key_failure)

    def test_batch_contains_broken_exception_rendering_and_continues(self):
        registry = ImportRegistry()
        registry.register(BrokenStringImporter())
        registry.register(InvalidStringImporter())
        registry.register(NamelessStringImporter())
        registry.register(FakeImporter())

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            broken = root / 'bad.broken-str'
            invalid = root / 'bad.invalid-str'
            nameless = root / 'bad.nameless-str'
            valid = root / 'good.foo'
            broken.write_bytes(b'broken-str-source')
            invalid.write_bytes(b'invalid-str-source')
            nameless.write_bytes(b'nameless-str-source')
            valid.write_bytes(b'valid-source')

            batch = registry.inspect_batch([broken, invalid, nameless, valid])

            self.assertEqual([item.ok for item in batch.items], [False, False, False, True])
            self.assertEqual(batch.items[0].error, 'BrokenStringError')
            self.assertEqual(batch.items[1].error, 'InvalidStringError')
            self.assertEqual(batch.items[2].error, 'Exception')
            self.assertEqual(len(batch.reports), 1)
            self.assertEqual(batch.reports[0].format_name, FakeImporter.format_name)
            self.assertEqual(broken.read_bytes(), b'broken-str-source')
            self.assertEqual(invalid.read_bytes(), b'invalid-str-source')
            self.assertEqual(nameless.read_bytes(), b'nameless-str-source')
            self.assertEqual(valid.read_bytes(), b'valid-source')

            # Strict single-source inspection keeps exposing the original
            # adapter exception instead of converting it to batch evidence.
            with self.assertRaises(BrokenStringError):
                registry.inspect(broken)

    def test_batch_propagates_cooperative_source_cancellation_without_later_work(self):
        registry = ImportRegistry()
        cancelled = CooperativeCancelImporter()
        later = ObservedAfterCancelImporter()
        registry.register(cancelled)
        registry.register(later)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stop = root / 'stop.cancel-source'
            after = root / 'after.after-cancel'
            stop.write_bytes(b'cancel-source')
            after.write_bytes(b'must-not-be-inspected')

            with self.assertRaises(SourceReadCancelledError) as batch_ctx:
                registry.inspect_batch([stop, after])

            self.assertEqual(str(batch_ctx.exception), 'source read cancelled')
            self.assertEqual(later.calls, 0)
            self.assertEqual(after.read_bytes(), b'must-not-be-inspected')

            # The strict API also preserves the exact cooperative cancellation
            # signal after proving the source was left unchanged.
            with self.assertRaises(SourceReadCancelledError) as strict_ctx:
                registry.inspect(stop)
            self.assertEqual(str(strict_ctx.exception), 'source read cancelled')

    def test_batch_does_not_swallow_process_control_exceptions(self):
        registry = ImportRegistry()
        registry.register(ProcessControlImporter())
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'stop.interrupt'
            source.write_bytes(b'interrupt-source')
            with self.assertRaises(KeyboardInterrupt):
                registry.inspect_batch([source])

    def test_registry_rejects_low_level_mutated_exact_record(self):
        registry = ImportRegistry()
        registry.register(LowLevelMutatedRecordImporter())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'source.mutated-record'
            path.write_bytes(b'unchanged')
            with self.assertRaisesRegex(ImportRegistryError, 'invalid ImportReport'):
                registry.inspect(path)
            self.assertEqual(path.read_bytes(), b'unchanged')

    def test_registry_rejects_low_level_mutated_exact_source(self):
        registry = ImportRegistry()
        registry.register(LowLevelMutatedSourceImporter())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'source.mutated-source'
            path.write_bytes(b'unchanged')
            with self.assertRaisesRegex(ImportRegistryError, 'invalid ImportReport'):
                registry.inspect(path)
            self.assertEqual(path.read_bytes(), b'unchanged')

    def test_unregister_removes_only_that_importers_suffixes(self):
        registry = ImportRegistry()
        first = FakeImporter()
        second = SecondFooImporter()
        registry.register(first)
        registry.register(second, replace=True)
        registry.unregister(second)
        self.assertIsNone(registry.importer_for('x.foo'))
        self.assertIs(registry.importer_for('x.bar'), first)

    def test_batch_preflight_reports_every_source_in_order_without_aborting(self):
        registry = ImportRegistry()
        registry.register(FakeImporter())
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / 'first.foo'
            unknown = root / 'middle.xyz'
            missing = root / 'missing.bar'
            last = root / 'last.bar'
            first.write_bytes(b'first')
            unknown.write_bytes(b'unknown')
            last.write_bytes(b'last')

            batch = registry.inspect_batch([first, unknown, missing, last])

            self.assertEqual([item.path for item in batch.items], [first, unknown, missing, last])
            self.assertEqual([item.ok for item in batch.items], [True, False, False, True])
            self.assertEqual(len(batch.reports), 2)
            self.assertEqual(len(batch.errors), 2)
            self.assertFalse(batch.all_ok)
            self.assertIn('.xyz', batch.items[1].error)
            self.assertTrue(batch.items[2].error)
            self.assertEqual(first.read_bytes(), b'first')
            self.assertEqual(last.read_bytes(), b'last')

    def test_batch_preflight_all_ok_when_every_source_is_supported(self):
        registry = ImportRegistry()
        registry.register(FakeImporter())
        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / 'a.foo'
            second = Path(td) / 'b.bar'
            first.write_bytes(b'a')
            second.write_bytes(b'b')
            batch = registry.inspect_batch([first, second])
            self.assertTrue(batch.all_ok)
            self.assertEqual(len(batch.reports), 2)
            self.assertEqual(batch.errors, ())


if __name__ == '__main__':
    unittest.main()
