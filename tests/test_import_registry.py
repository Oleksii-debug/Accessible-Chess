import tempfile
import unittest
from pathlib import Path

from acs.import_contract import (
    ImportQuality,
    ImportReport,
    ImportedRecord,
    SourceFingerprint,
    fingerprint,
)
from acs.import_registry import (
    BatchInspection,
    BatchInspectionItem,
    ImportRegistry,
    ImportRegistryError,
    ImporterInspectionError,
    InvalidImporterError,
    InvalidImportReportError,
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


class ImportRegistryTests(unittest.TestCase):
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

    def test_registration_rejects_invalid_adapter_shapes_atomically(self):
        registry = ImportRegistry()
        original = FakeImporter()
        registry.register(original)

        class InvalidImporter:
            format_name = "Invalid"
            suffixes = (".foo", "bad/path")

            def inspect(self, path):
                return ImportReport(fingerprint(path), self.format_name)

        invalid = (
            FakeImporter,
            object(),
            type("NoName", (), {"suffixes": (".new",), "inspect": lambda self, path: None})(),
            type("BadName", (), {"format_name": True, "suffixes": (".new",), "inspect": lambda self, path: None})(),
            type("ListSuffix", (), {"format_name": "List", "suffixes": [".new"], "inspect": lambda self, path: None})(),
            type("RawSuffix", (), {"format_name": "Raw", "suffixes": (True,), "inspect": lambda self, path: None})(),
            type("NoInspect", (), {"format_name": "None", "suffixes": (".new",), "inspect": None})(),
            InvalidImporter(),
        )
        for importer in invalid:
            with self.subTest(importer=importer):
                with self.assertRaises(InvalidImporterError):
                    registry.register(importer, replace=True)
                self.assertIs(registry.importer_for("x.foo"), original)
                self.assertIs(registry.importer_for("x.bar"), original)

        with self.assertRaisesRegex(InvalidImporterError, "replace"):
            registry.register(SecondFooImporter(), replace=1)
        self.assertIs(registry.importer_for("x.foo"), original)

    def test_falsey_importer_is_retained_and_unknown_unregister_is_explicit(self):
        class FalseyImporter(FakeImporter):
            def __bool__(self):
                return False

        registry = ImportRegistry()
        importer = FalseyImporter()
        registration = registry.register(importer)
        self.assertIs(registration.importer, importer)
        self.assertIs(registry.importer_for("x.foo"), importer)
        with self.assertRaisesRegex(ImportRegistryError, "not registered"):
            registry.unregister(FakeImporter())
        self.assertIs(registry.importer_for("x.foo"), importer)

    def test_registered_adapter_metadata_cannot_drift_after_routing(self):
        class MutableImporter(FakeImporter):
            def __init__(self):
                self.format_name = "Mutable"
                self.suffixes = (".foo",)

        registry = ImportRegistry()
        importer = MutableImporter()
        registry.register(importer)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "source.foo"
            path.write_bytes(b"source")

            importer.format_name = "Changed"
            with self.assertRaisesRegex(InvalidImporterError, "changed"):
                registry.inspect(path)
            importer.format_name = "Mutable"
            importer.suffixes = (".bar",)
            with self.assertRaisesRegex(InvalidImporterError, "changed"):
                registry.inspect(path)

    def test_adapter_exception_is_wrapped_and_batch_continues(self):
        class ExplodingImporter:
            format_name = "Exploding"
            suffixes = (".boom",)

            def inspect(self, path):
                raise RuntimeError("decoder failed")

        registry = ImportRegistry()
        registry.register(ExplodingImporter())
        registry.register(FakeImporter())
        with tempfile.TemporaryDirectory() as td:
            broken = Path(td) / "broken.boom"
            valid = Path(td) / "valid.foo"
            broken.write_bytes(b"unchanged")
            valid.write_bytes(b"valid")

            with self.assertRaisesRegex(ImporterInspectionError, "decoder failed"):
                registry.inspect(broken)
            self.assertEqual(broken.read_bytes(), b"unchanged")

            batch = registry.inspect_batch((broken, valid))
            self.assertEqual([item.ok for item in batch.items], [False, True])
            self.assertIn("decoder failed", batch.items[0].error)
            self.assertEqual(batch.reports[0].source.sha256, fingerprint(valid).sha256)

    def test_mutation_evidence_has_priority_when_adapter_also_raises(self):
        class MutateThenRaiseImporter:
            format_name = "Mutate then raise"
            suffixes = (".mtr",)

            def inspect(self, path):
                path.write_bytes(b"changed")
                raise RuntimeError("hide mutation")

        registry = ImportRegistry()
        registry.register(MutateThenRaiseImporter())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "source.mtr"
            path.write_bytes(b"original")
            with self.assertRaises(SourceMutationError) as caught:
                registry.inspect(path)
            self.assertIsInstance(caught.exception.__cause__, RuntimeError)
            self.assertEqual(path.read_bytes(), b"changed")

    def test_report_type_format_and_mutated_shape_fail_closed(self):
        class ReportImporter:
            format_name = "Expected"
            suffixes = (".report",)

            def __init__(self, mode):
                self.mode = mode
                self.report = None

            def inspect(self, path):
                if self.mode == "wrong_type":
                    return object()
                name = "Other" if self.mode == "wrong_name" else self.format_name
                self.report = ImportReport(fingerprint(path), name)
                if self.mode == "mutated":
                    self.report.records.append(object())
                else:
                    self.report.add(ImportedRecord("1", ImportQuality.FULL))
                return self.report

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "source.report"
            path.write_bytes(b"source")
            for mode in ("wrong_type", "wrong_name", "mutated"):
                with self.subTest(mode=mode):
                    registry = ImportRegistry()
                    registry.register(ReportImporter(mode))
                    with self.assertRaises(InvalidImportReportError):
                        registry.inspect(path)

            importer = ReportImporter("valid")
            registry = ImportRegistry()
            registry.register(importer)
            result = registry.inspect(path)
            self.assertIsNot(result, importer.report)
            importer.report.records.clear()
            self.assertEqual(result.total, 1)

    def test_batch_preflights_path_types_and_unprintable_errors(self):
        calls = []

        class CountingImporter(FakeImporter):
            def inspect(self, path):
                calls.append(path)
                return super().inspect(path)

        registry = ImportRegistry()
        registry.register(CountingImporter())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "source.foo"
            path.write_bytes(b"source")
            with self.assertRaisesRegex(ImportRegistryError, "Source path"):
                registry.inspect_many((path, True))
            self.assertEqual(calls, [])
            with self.assertRaisesRegex(ImportRegistryError, "iterable"):
                registry.inspect_batch(str(path))

        class UnprintableError(RuntimeError):
            def __str__(self):
                raise RuntimeError("cannot format")

        class UnprintableImporter:
            format_name = "Unprintable"
            suffixes = (".unprintable",)

            def inspect(self, path):
                raise UnprintableError()

        registry = ImportRegistry()
        registry.register(UnprintableImporter())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "source.unprintable"
            path.write_bytes(b"source")
            batch = registry.inspect_batch((path,))
            self.assertIn("<unprintable error>", batch.items[0].error)

    def test_registration_and_batch_dtos_reject_contradictory_shapes(self):
        with self.assertRaises((TypeError, ValueError)):
            BatchInspection(items=[])
        path = Path("source.foo")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            BatchInspectionItem(path)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            BatchInspectionItem(path, report=ImportReport(
                SourceFingerprint(str(path), 0, "0" * 64, ".foo"),
                "Fake",
            ), error="failure")


if __name__ == '__main__':
    unittest.main()
