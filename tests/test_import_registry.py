import tempfile
import unittest
from pathlib import Path

from acs.import_contract import ImportQuality, ImportReport, ImportedRecord, fingerprint
from acs.import_registry import ImportRegistry, ImportRegistryError


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

    def test_unregister_removes_only_that_importers_suffixes(self):
        registry = ImportRegistry()
        first = FakeImporter()
        second = SecondFooImporter()
        registry.register(first)
        registry.register(second, replace=True)
        registry.unregister(second)
        self.assertIsNone(registry.importer_for('x.foo'))
        self.assertIs(registry.importer_for('x.bar'), first)


if __name__ == '__main__':
    unittest.main()
