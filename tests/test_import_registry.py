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


class PrivateOSErrorImporter:
    format_name = 'Private filesystem failure'
    suffixes = ('.private-oserror',)

    def inspect(self, path: Path) -> ImportReport:
        raise OSError(
            5,
            r'decoder failed while reading C:\\Users\\PrivateBackend\\cache.bin',
            str(path.parent / 'decoder-cache.bin'),
        )


class HostileOSError(OSError):
    @property
    def filename(self):
        raise RuntimeError('filename attribute hook must be contained')

    @property
    def filename2(self):
        raise RuntimeError('filename2 attribute hook must be contained')

    @property
    def errno(self):
        raise RuntimeError('errno attribute hook must be contained')


class HostileOSErrorImporter:
    format_name = 'Hostile filesystem failure'
    suffixes = ('.hostile-oserror',)

    def inspect(self, path: Path) -> ImportReport:
        raise HostileOSError(
            5,
            r'private decoder strerror C:\\Users\\PrivateBackend\\secret.bin',
        )


class PrivateValueErrorImporter:
    format_name = 'Private value failure'
    suffixes = ('.private-value',)

    def inspect(self, path: Path) -> ImportReport:
        raise ValueError(f"invalid metadata at {path.parent / 'decoder-cache.bin'}")


class PrivateRuntimeErrorImporter:
    format_name = 'Private runtime failure'
    suffixes = ('.private-runtime',)

    def inspect(self, path: Path) -> ImportReport:
        raise RuntimeError(
            r'backend crashed at C:\\Users\\PrivateBackend\\Documents\\decoder.dll'
        )


class PrivateRegistryErrorImporter:
    format_name = 'Private registry-like adapter failure'
    suffixes = ('.private-registry',)

    def inspect(self, path: Path) -> ImportReport:
        raise ImportRegistryError(
            f"adapter-owned registry-like error at {path.parent / 'decoder-secret.bin'}"
        )


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


class MutatingProcessControlImporter:
    format_name = 'Mutating process control'
    suffixes = ('.interrupt-mutate',)

    def inspect(self, path: Path) -> ImportReport:
        path.write_bytes(path.read_bytes() + b' changed-before-interrupt')
        raise KeyboardInterrupt()


class DeletingProcessControlImporter:
    format_name = 'Deleting process control'
    suffixes = ('.interrupt-delete',)

    def inspect(self, path: Path) -> ImportReport:
        path.unlink()
        raise SystemExit(2)


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

    def test_registration_rejects_unroutable_or_unbounded_suffix_text(self):
        class UnsafeSuffixImporter:
            format_name = 'Unsafe suffix'

            def __init__(self, suffix: str) -> None:
                self.suffixes = (suffix,)

            def inspect(self, path: Path) -> ImportReport:
                raise AssertionError('inspection must not run')

        unsafe_suffixes = (
            '.bad\nsuffix',
            '.bad\u2028suffix',
            '.nested/path',
            '.nested\\path',
            '.',
            '..double',
            '.' + ('x' * 65),
        )
        for suffix in unsafe_suffixes:
            with self.subTest(suffix=repr(suffix)):
                with self.assertRaisesRegex(
                    ImportRegistryError,
                    'bounded canonical extension text',
                ):
                    ImportRegistry().register(UnsafeSuffixImporter(suffix))

    def test_unknown_suffix_error_is_bounded_and_control_safe(self):
        registry = ImportRegistry()
        registry.register(FakeImporter())

        unsafe_paths = (
            'source.' + ('x' * 4096),
            'source.bad\nsuffix',
            'source.bad\u2028suffix',
        )
        for source in unsafe_paths:
            with self.subTest(source=repr(source)):
                with self.assertRaises(ImportRegistryError) as ctx:
                    registry.inspect(source)
                message = str(ctx.exception)
                self.assertEqual(
                    message,
                    'No read-only importer registered for suffix: <invalid>',
                )
                self.assertNotIn('\n', message)
                self.assertNotIn('\u2028', message)
                self.assertLess(len(message), 80)

                batch = registry.inspect_batch([source])
                self.assertEqual(len(batch.items), 1)
                self.assertFalse(batch.items[0].ok)
                self.assertEqual(batch.items[0].error, message)

    def test_registration_metadata_cannot_rebind_host_route_container(self):
        registry = ImportRegistry()
        original = FakeImporter()
        registry.register(original)

        class HostileRouteMap(dict):
            def __iter__(self):
                raise AssertionError("metadata poison iteration hook must not run")

            def __contains__(self, item):
                raise AssertionError("metadata poison membership hook must not run")

            def clear(self):
                raise AssertionError("metadata poison clear hook must not run")

        class MetadataPoisoner:
            suffixes = (".metadata-poison",)

            @property
            def format_name(self):
                registry._by_suffix = HostileRouteMap()
                return "Metadata poisoner"

            def inspect(self, path: Path) -> ImportReport:
                raise AssertionError("inspection must not run")

        with self.assertRaisesRegex(
            ImportRegistryError,
            "registration changed while reading importer metadata",
        ):
            registry.register(MetadataPoisoner())

        self.assertEqual(type(registry._by_suffix), dict)
        self.assertIs(registry.importer_for("still.foo"), original)
        self.assertNotIn(".metadata-poison", registry.registered_suffixes)

    def test_registration_suffix_property_cannot_hide_route_mutation_or_runtime_error(self):
        registry = ImportRegistry()
        original = FakeImporter()
        registry.register(original)

        class PropertyPoisoner:
            format_name = "Suffix property poisoner"

            @property
            def suffixes(self):
                registry._format_name_by_suffix = {}
                raise RuntimeError("suffix property failed after route mutation")

            def inspect(self, path: Path) -> ImportReport:
                raise AssertionError("inspection must not run")

        with self.assertRaisesRegex(
            ImportRegistryError,
            "registration changed while reading importer metadata",
        ) as ctx:
            registry.register(PropertyPoisoner())

        self.assertIsInstance(ctx.exception.__cause__, RuntimeError)
        self.assertIs(registry.importer_for("still.foo"), original)
        self.assertEqual(registry.registered_suffixes, (".bar", ".foo"))

    def test_registration_suffix_container_must_match_readonly_importer_contract(self):
        class ActiveTuple(tuple):
            touched = False

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("active suffix tuple hook must not run")

            def __len__(self):
                type(self).touched = True
                raise AssertionError("active suffix tuple length hook must not run")

        class BadContainerImporter:
            format_name = "Bad suffix container"

            def __init__(self, suffixes):
                self.suffixes = suffixes

            def inspect(self, path: Path) -> ImportReport:
                raise AssertionError("inspection must not run")

        for suffixes in (
            ".x",
            [".x"],
            iter((".x",)),
            ActiveTuple((".x",)),
        ):
            with self.subTest(container=type(suffixes).__name__):
                ActiveTuple.touched = False
                with self.assertRaisesRegex(
                    ImportRegistryError,
                    "exact immutable tuple",
                ):
                    ImportRegistry().register(BadContainerImporter(suffixes))
                self.assertFalse(ActiveTuple.touched)

        registry = ImportRegistry()
        with self.assertRaisesRegex(ImportRegistryError, "exact immutable tuple"):
            registry.register(BadContainerImporter("x"))
        self.assertEqual(registry.registered_suffixes, ())

    def test_registration_suffix_tuple_count_is_bounded(self):
        class TooManyImporter:
            format_name = "Too many suffixes"
            suffixes = tuple(f".suffix-{index}" for index in range(65))

            def inspect(self, path: Path) -> ImportReport:
                raise AssertionError("inspection must not run")

        with self.assertRaisesRegex(ImportRegistryError, "too many suffixes"):
            ImportRegistry().register(TooManyImporter())

    def test_registration_replace_flag_rejects_active_boolean_coercion(self):
        class ActiveReplace:
            def __bool__(self):
                raise AssertionError("replace boolean hook must not run")

        registry = ImportRegistry()
        registry.register(FakeImporter())
        with self.assertRaisesRegex(ImportRegistryError, "replace flag must be boolean"):
            registry.register(SecondFooImporter(), replace=ActiveReplace())

        self.assertIs(registry.importer_for("still.foo"), registry.importer_for("still.bar"))

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

    def test_registry_rejects_reentrant_route_replacement_during_inspection(self):
        registry = ImportRegistry()

        class ReplacementImporter:
            format_name = 'Replacement route identity'
            suffixes = ('.reroute',)

            def inspect(self, path: Path) -> ImportReport:
                return ImportReport(source=fingerprint(path), format_name=self.format_name)

        replacement = ReplacementImporter()

        class ReentrantImporter:
            format_name = 'Original route identity'
            suffixes = ('.reroute',)

            def inspect(self, path: Path) -> ImportReport:
                registry.register(replacement, replace=True)
                # Deliberately return the replacement identity. Without a
                # stable registration snapshot this can be accepted even
                # though a different importer actually inspected the source.
                return ImportReport(
                    source=fingerprint(path),
                    format_name=replacement.format_name,
                )

        original = ReentrantImporter()
        registry.register(original)

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'source.reroute'
            original_bytes = b'reentrant-route-source'
            path.write_bytes(original_bytes)

            with self.assertRaisesRegex(ImportRegistryError, 'registration changed'):
                registry.inspect(path)

            self.assertIs(registry.importer_for(path), original)
            self.assertEqual(path.read_bytes(), original_bytes)

    def test_batch_isolates_reentrant_route_replacement_and_continues(self):
        registry = ImportRegistry()

        class ReplacementImporter:
            format_name = 'Batch replacement route'
            suffixes = ('.batch-reroute',)

            def inspect(self, path: Path) -> ImportReport:
                return ImportReport(source=fingerprint(path), format_name=self.format_name)

        replacement = ReplacementImporter()

        class ReentrantImporter:
            format_name = 'Batch original route'
            suffixes = ('.batch-reroute',)

            def inspect(self, path: Path) -> ImportReport:
                registry.register(replacement, replace=True)
                return ImportReport(
                    source=fingerprint(path),
                    format_name=replacement.format_name,
                )

        original = ReentrantImporter()
        registry.register(original)
        registry.register(FakeImporter())

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rerouted = root / 'bad.batch-reroute'
            valid = root / 'good.foo'
            rerouted.write_bytes(b'reentrant-batch-source')
            valid.write_bytes(b'valid-source')

            batch = registry.inspect_batch([rerouted, valid])

            self.assertEqual([item.ok for item in batch.items], [False, True])
            self.assertIn('registration changed', batch.items[0].error)
            self.assertIsNone(batch.items[0].report)
            self.assertEqual(len(batch.reports), 1)
            self.assertEqual(batch.reports[0].format_name, FakeImporter.format_name)
            self.assertIs(registry.importer_for(rerouted), original)
            self.assertEqual(rerouted.read_bytes(), b'reentrant-batch-source')
            self.assertEqual(valid.read_bytes(), b'valid-source')

    def test_registry_rejects_route_replacement_hidden_by_adapter_error(self):
        registry = ImportRegistry()

        class ReplacementImporter:
            format_name = 'Replacement after failing route'
            suffixes = ('.reroute-error',)

            def inspect(self, path: Path) -> ImportReport:
                return ImportReport(source=fingerprint(path), format_name=self.format_name)

        replacement = ReplacementImporter()

        class ReentrantFailingImporter:
            format_name = 'Original failing route'
            suffixes = ('.reroute-error',)

            def inspect(self, path: Path) -> ImportReport:
                registry.register(replacement, replace=True)
                raise RuntimeError('decoder failed after route replacement')

        original = ReentrantFailingImporter()
        registry.register(original)

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'source.reroute-error'
            original_bytes = b'reentrant-route-error-source'
            path.write_bytes(original_bytes)

            with self.assertRaisesRegex(ImportRegistryError, 'registration changed') as ctx:
                registry.inspect(path)

            self.assertIsInstance(ctx.exception.__cause__, RuntimeError)
            self.assertIs(registry.importer_for(path), original)
            self.assertEqual(path.read_bytes(), original_bytes)

    def test_batch_isolates_route_replacement_hidden_by_adapter_error(self):
        registry = ImportRegistry()

        class ReplacementImporter:
            format_name = 'Batch replacement after failure'
            suffixes = ('.batch-reroute-error',)

            def inspect(self, path: Path) -> ImportReport:
                return ImportReport(source=fingerprint(path), format_name=self.format_name)

        replacement = ReplacementImporter()

        class ReentrantFailingImporter:
            format_name = 'Batch original failing route'
            suffixes = ('.batch-reroute-error',)

            def inspect(self, path: Path) -> ImportReport:
                registry.register(replacement, replace=True)
                raise RuntimeError('decoder failed after route replacement')

        original = ReentrantFailingImporter()
        registry.register(original)
        registry.register(FakeImporter())

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rerouted = root / 'bad.batch-reroute-error'
            valid = root / 'good.foo'
            rerouted.write_bytes(b'reentrant-batch-route-error')
            valid.write_bytes(b'valid-source')

            batch = registry.inspect_batch([rerouted, valid])

            self.assertEqual([item.ok for item in batch.items], [False, True])
            self.assertIn('registration changed', batch.items[0].error)
            self.assertIsNone(batch.items[0].report)
            self.assertEqual(len(batch.reports), 1)
            self.assertEqual(batch.reports[0].format_name, FakeImporter.format_name)
            self.assertIs(registry.importer_for(rerouted), original)
            self.assertEqual(rerouted.read_bytes(), b'reentrant-batch-route-error')
            self.assertEqual(valid.read_bytes(), b'valid-source')

    def test_batch_restores_same_suffix_route_before_later_source(self):
        registry = ImportRegistry()

        class ReplacementImporter:
            format_name = 'Unauthorized replacement'
            suffixes = ('.same-route',)

            def __init__(self) -> None:
                self.calls = 0

            def inspect(self, path: Path) -> ImportReport:
                self.calls += 1
                return ImportReport(source=fingerprint(path), format_name=self.format_name)

        replacement = ReplacementImporter()

        class ReentrantOnceImporter:
            format_name = 'Authorized original'
            suffixes = ('.same-route',)

            def __init__(self) -> None:
                self.calls = 0

            def inspect(self, path: Path) -> ImportReport:
                self.calls += 1
                if self.calls == 1:
                    registry.register(replacement, replace=True)
                return ImportReport(source=fingerprint(path), format_name=self.format_name)

        original = ReentrantOnceImporter()
        registry.register(original)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / 'first.same-route'
            second = root / 'second.same-route'
            first.write_bytes(b'first')
            second.write_bytes(b'second')

            batch = registry.inspect_batch([first, second])

            self.assertEqual([item.ok for item in batch.items], [False, True])
            self.assertIn('registration changed', batch.items[0].error)
            self.assertEqual(batch.items[1].report.format_name, original.format_name)
            self.assertIs(registry.importer_for(second), original)
            self.assertEqual(original.calls, 2)
            self.assertEqual(replacement.calls, 0)

    def test_batch_restores_same_suffix_route_after_adapter_error(self):
        registry = ImportRegistry()

        class ReplacementImporter:
            format_name = 'Unauthorized error replacement'
            suffixes = ('.same-route-error',)

            def __init__(self) -> None:
                self.calls = 0

            def inspect(self, path: Path) -> ImportReport:
                self.calls += 1
                return ImportReport(source=fingerprint(path), format_name=self.format_name)

        replacement = ReplacementImporter()

        class ReentrantOnceFailingImporter:
            format_name = 'Authorized error original'
            suffixes = ('.same-route-error',)

            def __init__(self) -> None:
                self.calls = 0

            def inspect(self, path: Path) -> ImportReport:
                self.calls += 1
                if self.calls == 1:
                    registry.register(replacement, replace=True)
                    raise RuntimeError('first source failed after reroute')
                return ImportReport(source=fingerprint(path), format_name=self.format_name)

        original = ReentrantOnceFailingImporter()
        registry.register(original)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / 'first.same-route-error'
            second = root / 'second.same-route-error'
            first.write_bytes(b'first')
            second.write_bytes(b'second')

            batch = registry.inspect_batch([first, second])

            self.assertEqual([item.ok for item in batch.items], [False, True])
            self.assertIn('registration changed', batch.items[0].error)
            self.assertEqual(batch.items[1].report.format_name, original.format_name)
            self.assertIs(registry.importer_for(second), original)
            self.assertEqual(original.calls, 2)
            self.assertEqual(replacement.calls, 0)

    def test_registry_rejects_and_restores_cross_suffix_route_poisoning(self):
        registry = ImportRegistry()

        class VictimImporter:
            format_name = 'Victim original'
            suffixes = ('.victim-route',)

            def inspect(self, path: Path) -> ImportReport:
                return ImportReport(source=fingerprint(path), format_name=self.format_name)

        class VictimReplacement:
            format_name = 'Victim replacement'
            suffixes = ('.victim-route',)

            def __init__(self) -> None:
                self.calls = 0

            def inspect(self, path: Path) -> ImportReport:
                self.calls += 1
                return ImportReport(source=fingerprint(path), format_name=self.format_name)

        victim = VictimImporter()
        replacement = VictimReplacement()
        registry.register(victim)

        class CrossSuffixPoisoner:
            format_name = 'Cross suffix poisoner'
            suffixes = ('.poison-route',)

            def inspect(self, path: Path) -> ImportReport:
                registry.register(replacement, replace=True)
                return ImportReport(source=fingerprint(path), format_name=self.format_name)

        poisoner = CrossSuffixPoisoner()
        registry.register(poisoner)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            poison = root / 'bad.poison-route'
            victim_source = root / 'good.victim-route'
            poison.write_bytes(b'poison')
            victim_source.write_bytes(b'victim')

            batch = registry.inspect_batch([poison, victim_source])

            self.assertEqual([item.ok for item in batch.items], [False, True])
            self.assertIn('registration changed', batch.items[0].error)
            self.assertEqual(batch.items[1].report.format_name, victim.format_name)
            self.assertIs(registry.importer_for(victim_source), victim)
            self.assertEqual(replacement.calls, 0)

    def test_batch_restores_hostile_route_container_without_running_mapping_hooks(self):
        registry = ImportRegistry()
        registry.register(FakeImporter())

        class HostileRouteMap(dict):
            def __iter__(self):
                raise AssertionError("hostile route iteration hook must not run")

            def __len__(self):
                raise AssertionError("hostile route length hook must not run")

            def clear(self):
                raise AssertionError("hostile route clear hook must not run")

            def update(self, *args, **kwargs):
                raise AssertionError("hostile route update hook must not run")

            def get(self, *args, **kwargs):
                raise AssertionError("hostile route get hook must not run")

        class ContainerPoisoner:
            format_name = "Container poisoner"
            suffixes = (".container-poison",)

            def inspect(self, path: Path) -> ImportReport:
                registry._by_suffix = HostileRouteMap()
                return ImportReport(source=fingerprint(path), format_name=self.format_name)

        poisoner = ContainerPoisoner()
        registry.register(poisoner)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            poisoned = root / "bad.container-poison"
            valid = root / "good.foo"
            poisoned.write_bytes(b"poison")
            valid.write_bytes(b"valid")

            batch = registry.inspect_batch([poisoned, valid])

            self.assertEqual([item.ok for item in batch.items], [False, True])
            self.assertIn("registration changed", batch.items[0].error)
            self.assertIs(registry.importer_for(poisoned), poisoner)
            self.assertIsInstance(registry._by_suffix, dict)
            self.assertEqual(type(registry._by_suffix), dict)
            self.assertEqual(batch.items[1].report.format_name, FakeImporter.format_name)

    def test_adapter_error_restores_hostile_format_container_before_batch_continues(self):
        registry = ImportRegistry()
        registry.register(FakeImporter())

        class HostileRouteMap(dict):
            def __iter__(self):
                raise AssertionError("hostile format iteration hook must not run")

            def clear(self):
                raise AssertionError("hostile format clear hook must not run")

            def update(self, *args, **kwargs):
                raise AssertionError("hostile format update hook must not run")

        class FailingContainerPoisoner:
            format_name = "Failing container poisoner"
            suffixes = (".container-error",)

            def inspect(self, path: Path) -> ImportReport:
                registry._format_name_by_suffix = HostileRouteMap()
                raise RuntimeError("decoder failure after container poison")

        poisoner = FailingContainerPoisoner()
        registry.register(poisoner)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            poisoned = root / "bad.container-error"
            valid = root / "good.foo"
            poisoned.write_bytes(b"poison")
            valid.write_bytes(b"valid")

            batch = registry.inspect_batch([poisoned, valid])

            self.assertEqual([item.ok for item in batch.items], [False, True])
            self.assertIn("registration changed", batch.items[0].error)
            self.assertIs(registry.importer_for(poisoned), poisoner)
            self.assertEqual(type(registry._format_name_by_suffix), dict)
            self.assertEqual(batch.items[1].report.format_name, FakeImporter.format_name)

    def test_cancellation_restores_hostile_token_container_before_propagation(self):
        registry = ImportRegistry()

        class HostileRouteMap(dict):
            def __iter__(self):
                raise AssertionError("hostile token iteration hook must not run")

            def clear(self):
                raise AssertionError("hostile token clear hook must not run")

            def update(self, *args, **kwargs):
                raise AssertionError("hostile token update hook must not run")

        class CancellingContainerPoisoner:
            format_name = "Cancelling container poisoner"
            suffixes = (".container-cancel",)

            def inspect(self, path: Path) -> ImportReport:
                registry._registration_token_by_suffix = HostileRouteMap()
                raise SourceReadCancelledError("container cancellation")

        poisoner = CancellingContainerPoisoner()
        registry.register(poisoner)

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "stop.container-cancel"
            source.write_bytes(b"cancel")

            with self.assertRaisesRegex(SourceReadCancelledError, "container cancellation"):
                registry.inspect_batch([source])

            self.assertIs(registry.importer_for(source), poisoner)
            self.assertEqual(type(registry._registration_token_by_suffix), dict)
            self.assertEqual(source.read_bytes(), b"cancel")

    def test_process_control_restores_hostile_route_container_before_propagation(self):
        registry = ImportRegistry()

        class HostileRouteMap(dict):
            def __iter__(self):
                raise AssertionError("hostile process-control iteration hook must not run")

            def clear(self):
                raise AssertionError("hostile process-control clear hook must not run")

            def update(self, *args, **kwargs):
                raise AssertionError("hostile process-control update hook must not run")

        class InterruptingContainerPoisoner:
            format_name = "Interrupting container poisoner"
            suffixes = (".container-interrupt",)

            def inspect(self, path: Path) -> ImportReport:
                registry._by_suffix = HostileRouteMap()
                raise KeyboardInterrupt()

        poisoner = InterruptingContainerPoisoner()
        registry.register(poisoner)

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "stop.container-interrupt"
            source.write_bytes(b"interrupt")

            with self.assertRaises(KeyboardInterrupt):
                registry.inspect_batch([source])

            self.assertIs(registry.importer_for(source), poisoner)
            self.assertEqual(type(registry._by_suffix), dict)
            self.assertEqual(source.read_bytes(), b"interrupt")

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
            self.assertEqual(
                batch.items[0].error,
                'Importer rejected source: bad.type-report',
            )
            self.assertNotIn('exact list', batch.items[0].error)
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
            self.assertEqual(batch.items[0].error, 'Importer rejected source: bad.key-error')
            self.assertEqual(batch.items[1].error, 'Importer rejected source: bad.index-error')
            self.assertNotIn('decoder record index out of range', batch.items[1].error)
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
            self.assertEqual(batch.items[0].error, 'Importer rejected source: bad.broken-str')
            self.assertEqual(batch.items[1].error, 'Importer rejected source: bad.invalid-str')
            self.assertEqual(batch.items[2].error, 'Importer rejected source: bad.nameless-str')
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

    def test_cooperative_cancellation_restores_route_and_stops_later_work(self):
        registry = ImportRegistry()
        original_route = FakeImporter()
        replacement_route = SecondFooImporter()
        later = ObservedAfterCancelImporter()
        registry.register(original_route)
        registry.register(later)

        class CancellingRouteMutator:
            format_name = 'Cancelling route mutator'
            suffixes = ('.cancel-route',)

            def inspect(self, path: Path) -> ImportReport:
                registry.register(replacement_route, replace=True)
                raise SourceReadCancelledError('source read cancelled')

        cancelling = CancellingRouteMutator()
        registry.register(cancelling)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stop = root / 'stop.cancel-route'
            after = root / 'after.after-cancel'
            stop.write_bytes(b'cancel-route-source')
            after.write_bytes(b'must-not-be-inspected')

            with self.assertRaises(SourceReadCancelledError) as ctx:
                registry.inspect_batch([stop, after])

            self.assertEqual(str(ctx.exception), 'source read cancelled')
            self.assertEqual(later.calls, 0)
            self.assertIs(registry.importer_for('after.foo'), original_route)
            self.assertIs(registry.importer_for(stop), cancelling)
            self.assertEqual(stop.read_bytes(), b'cancel-route-source')
            self.assertEqual(after.read_bytes(), b'must-not-be-inspected')

    def test_batch_does_not_swallow_process_control_exceptions(self):
        registry = ImportRegistry()
        registry.register(ProcessControlImporter())
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'stop.interrupt'
            source.write_bytes(b'interrupt-source')
            with self.assertRaises(KeyboardInterrupt):
                registry.inspect_batch([source])
            self.assertEqual(source.read_bytes(), b'interrupt-source')

    def test_process_control_cannot_hide_source_mutation(self):
        registry = ImportRegistry()
        registry.register(MutatingProcessControlImporter())
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'stop.interrupt-mutate'
            source.write_bytes(b'original')

            with self.assertRaises(SourceMutationError) as ctx:
                registry.inspect_batch([source])

            self.assertIn('modified source bytes', str(ctx.exception))
            self.assertEqual(source.read_bytes(), b'original changed-before-interrupt')

    def test_process_control_cannot_hide_deleted_source(self):
        registry = ImportRegistry()
        registry.register(DeletingProcessControlImporter())
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'stop.interrupt-delete'
            source.write_bytes(b'original')

            with self.assertRaises(SourceMutationError) as ctx:
                registry.inspect(source)

            self.assertIn('unverifiable', str(ctx.exception))
            self.assertFalse(source.exists())

    def test_process_control_restores_cross_suffix_route_before_propagation(self):
        registry = ImportRegistry()
        original_route = FakeImporter()
        replacement_route = SecondFooImporter()
        registry.register(original_route)

        class InterruptingRouteMutator:
            format_name = 'Process control route mutator'
            suffixes = ('.interrupt-route',)

            def inspect(self, path: Path) -> ImportReport:
                registry.register(replacement_route, replace=True)
                raise KeyboardInterrupt()

        mutator = InterruptingRouteMutator()
        registry.register(mutator)

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'stop.interrupt-route'
            source.write_bytes(b'control-source')

            with self.assertRaises(KeyboardInterrupt):
                registry.inspect_batch([source])

            self.assertIs(registry.importer_for('after.foo'), original_route)
            self.assertIs(registry.importer_for(source), mutator)
            self.assertEqual(source.read_bytes(), b'control-source')

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

    def test_registry_owned_failures_hide_private_parent_paths(self):
        with tempfile.TemporaryDirectory() as td:
            private = Path(td) / 'Users' / 'PrivateUser' / 'Documents'
            private.mkdir(parents=True)

            mutation = private / 'analysis.mut'
            mutation.write_bytes(b'original')
            registry = ImportRegistry()
            registry.register(MutatingImporter())
            with self.assertRaises(SourceMutationError) as mutation_ctx:
                registry.inspect(mutation)
            mutation_message = str(mutation_ctx.exception)
            self.assertIn('analysis.mut', mutation_message)
            self.assertNotIn('PrivateUser', mutation_message)
            self.assertNotIn('Documents', mutation_message)
            self.assertNotIn('Users', mutation_message)

            provenance = private / 'analysis.lie'
            provenance.write_bytes(b'original')
            registry = ImportRegistry()
            registry.register(FalseProvenanceImporter())
            with self.assertRaises(SourceProvenanceError) as provenance_ctx:
                registry.inspect(provenance)
            provenance_message = str(provenance_ctx.exception)
            self.assertIn('analysis.lie', provenance_message)
            self.assertNotIn('PrivateUser', provenance_message)
            self.assertNotIn('Documents', provenance_message)
            self.assertNotIn('Users', provenance_message)

    def test_batch_filesystem_error_exposes_only_bounded_safe_context(self):
        registry = ImportRegistry()
        registry.register(PrivateOSErrorImporter())
        with tempfile.TemporaryDirectory() as td:
            private = Path(td) / 'Users' / 'PrivateUser' / 'Documents'
            private.mkdir(parents=True)
            source = private / 'analysis.private-oserror'
            source.write_bytes(b'source')

            error = registry.inspect_batch([source]).errors[0].error

            self.assertIn('Filesystem error', error)
            self.assertIn('errno 5', error)
            self.assertIn('decoder-cache.bin', error)
            self.assertNotIn('PrivateUser', error)
            self.assertNotIn('Documents', error)
            self.assertNotIn('PrivateBackend', error)
            self.assertNotIn('decoder failed', error)

    def test_batch_hostile_oserror_attributes_cannot_abort_recovery(self):
        registry = ImportRegistry()
        registry.register(HostileOSErrorImporter())
        registry.register(FakeImporter())
        with tempfile.TemporaryDirectory() as td:
            private = Path(td) / 'Users' / 'PrivateUser' / 'Documents'
            private.mkdir(parents=True)
            hostile = private / 'hostile.hostile-oserror'
            valid = private / 'good.foo'
            hostile.write_bytes(b'hostile')
            valid.write_bytes(b'valid')

            batch = registry.inspect_batch([hostile, valid])

            self.assertEqual([item.ok for item in batch.items], [False, True])
            self.assertEqual(
                batch.items[0].error,
                'Filesystem error: hostile.hostile-oserror',
            )
            self.assertNotIn('PrivateUser', batch.items[0].error)
            self.assertNotIn('PrivateBackend', batch.items[0].error)
            self.assertNotIn('secret.bin', batch.items[0].error)
            self.assertEqual(len(batch.reports), 1)
            self.assertEqual(batch.reports[0].format_name, FakeImporter.format_name)
            self.assertEqual(valid.read_bytes(), b'valid')

    def test_batch_ordinary_adapter_text_is_not_a_reporting_channel(self):
        registry = ImportRegistry()
        registry.register(PrivateValueErrorImporter())
        registry.register(PrivateRuntimeErrorImporter())
        registry.register(PrivateRegistryErrorImporter())
        with tempfile.TemporaryDirectory() as td:
            private = Path(td) / 'Users' / 'PrivateUser' / 'Documents'
            private.mkdir(parents=True)
            value_source = private / 'value.private-value'
            runtime_source = private / 'runtime.private-runtime'
            registry_source = private / 'registry.private-registry'
            value_source.write_bytes(b'value')
            runtime_source.write_bytes(b'runtime')
            registry_source.write_bytes(b'registry')

            batch = registry.inspect_batch([value_source, runtime_source, registry_source])

            self.assertEqual(
                batch.items[0].error,
                'Importer rejected source: value.private-value',
            )
            self.assertEqual(
                batch.items[1].error,
                'Importer rejected source: runtime.private-runtime',
            )
            self.assertEqual(
                batch.items[2].error,
                'Importer rejected source: registry.private-registry',
            )
            combined = '\n'.join(item.error for item in batch.items)
            self.assertNotIn('PrivateUser', combined)
            self.assertNotIn('Documents', combined)
            self.assertNotIn('PrivateBackend', combined)
            self.assertNotIn('decoder-cache.bin', combined)
            self.assertNotIn('decoder-secret.bin', combined)
            self.assertNotIn('backend crashed', combined)
            self.assertNotIn('registry-like error', combined)

            # Strict inspection remains an internal API that preserves the
            # original adapter exception identity and diagnostic text.
            with self.assertRaises(ValueError) as strict_ctx:
                registry.inspect(value_source)
            self.assertIn('decoder-cache.bin', str(strict_ctx.exception))
            with self.assertRaises(ImportRegistryError) as registry_ctx:
                registry.inspect(registry_source)
            self.assertIn('decoder-secret.bin', str(registry_ctx.exception))

    def test_batch_invalid_path_scalar_is_isolated_and_later_sources_continue(self):
        registry = ImportRegistry()
        registry.register(FakeImporter())
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / "first.foo"
            last = root / "last.bar"
            first.write_bytes(b"first")
            last.write_bytes(b"last")

            batch = registry.inspect_batch([first, None, last])

            self.assertEqual([item.ok for item in batch.items], [True, False, True])
            self.assertEqual(batch.items[1].path, Path("<invalid-source>"))
            self.assertEqual(batch.items[1].error, "Invalid source path")
            self.assertEqual(len(batch.reports), 2)
            self.assertEqual(first.read_bytes(), b"first")
            self.assertEqual(last.read_bytes(), b"last")

            # Strict single-source inspection keeps its fail-fast API contract.
            with self.assertRaises(TypeError):
                registry.inspect(None)

    def test_batch_pathlike_conversion_error_is_sanitized_per_source(self):
        registry = ImportRegistry()
        registry.register(FakeImporter())

        class BrokenPathLike:
            def __fspath__(self):
                raise RuntimeError(
                    r"private path conversion C:\\Users\\PrivateUser\\secret"
                )

        with tempfile.TemporaryDirectory() as td:
            valid = Path(td) / "good.foo"
            valid.write_bytes(b"valid")

            batch = registry.inspect_batch([BrokenPathLike(), valid])

            self.assertEqual([item.ok for item in batch.items], [False, True])
            self.assertEqual(batch.items[0].path, Path("<invalid-source>"))
            self.assertEqual(batch.items[0].error, "Invalid source path")
            self.assertNotIn("PrivateUser", batch.items[0].error)
            self.assertEqual(batch.items[1].report.format_name, FakeImporter.format_name)

    def test_batch_pathlike_process_control_is_not_converted_to_source_evidence(self):
        registry = ImportRegistry()

        class InterruptingPathLike:
            def __fspath__(self):
                raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            registry.inspect_batch([InterruptingPathLike()])

    def test_pathlike_cannot_rebind_route_before_strict_lookup_or_inspection(self):
        registry = ImportRegistry()
        original = FakeImporter()
        replacement = SecondFooImporter()
        registry.register(original)

        class MutatingPathLike:
            def __init__(self, value: str) -> None:
                self.value = value

            def __fspath__(self):
                registry.register(replacement, replace=True)
                return self.value

        with self.assertRaisesRegex(
            ImportRegistryError,
            "registration changed while reading source path",
        ):
            registry.importer_for(MutatingPathLike("source.foo"))
        self.assertIs(registry.importer_for("source.foo"), original)

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.foo"
            source.write_bytes(b"source")
            with self.assertRaisesRegex(
                ImportRegistryError,
                "registration changed while reading source path",
            ):
                registry.inspect(MutatingPathLike(str(source)))
            self.assertIs(registry.importer_for(source), original)
            self.assertEqual(source.read_bytes(), b"source")

    def test_batch_restores_pathlike_route_mutation_and_continues(self):
        registry = ImportRegistry()
        original = FakeImporter()
        replacement = SecondFooImporter()
        registry.register(original)

        class MutatingPathLike:
            def __init__(self, value: str) -> None:
                self.value = value

            def __fspath__(self):
                registry.register(replacement, replace=True)
                return self.value

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            poisoned = root / "poisoned.foo"
            valid = root / "valid.foo"
            poisoned.write_bytes(b"poisoned")
            valid.write_bytes(b"valid")

            batch = registry.inspect_batch([MutatingPathLike(str(poisoned)), valid])

            self.assertEqual([item.ok for item in batch.items], [False, True])
            self.assertEqual(batch.items[0].path, Path("<invalid-source>"))
            self.assertEqual(
                batch.items[0].error,
                "Importer registration changed while reading source path",
            )
            self.assertIs(registry.importer_for(valid), original)
            self.assertEqual(batch.items[1].report.format_name, original.format_name)
            self.assertEqual(poisoned.read_bytes(), b"poisoned")
            self.assertEqual(valid.read_bytes(), b"valid")

    def test_batch_pathlike_route_mutation_and_error_is_restored_without_text_leak(self):
        registry = ImportRegistry()
        original = FakeImporter()
        replacement = SecondFooImporter()
        registry.register(original)

        class MutatingBrokenPathLike:
            def __fspath__(self):
                registry.register(replacement, replace=True)
                raise RuntimeError(
                    r"private path conversion C:\Users\PrivateUser\secret"
                )

        batch = registry.inspect_batch([MutatingBrokenPathLike()])

        self.assertEqual(len(batch.items), 1)
        self.assertFalse(batch.items[0].ok)
        self.assertEqual(batch.items[0].path, Path("<invalid-source>"))
        self.assertEqual(
            batch.items[0].error,
            "Importer registration changed while reading source path",
        )
        self.assertNotIn("PrivateUser", batch.items[0].error)
        self.assertIs(registry.importer_for("source.foo"), original)

    def test_pathlike_process_control_restores_route_before_propagation(self):
        registry = ImportRegistry()
        original = FakeImporter()
        replacement = SecondFooImporter()
        registry.register(original)

        class InterruptingPathLike:
            def __fspath__(self):
                registry.register(replacement, replace=True)
                raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            registry.inspect_batch([InterruptingPathLike()])

        self.assertIs(registry.importer_for("source.foo"), original)

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
