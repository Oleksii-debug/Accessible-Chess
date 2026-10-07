from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.import_contract import (
    ImportQuality,
    ImportedRecord,
    ImportReport,
    SourceFingerprint,
    fingerprint,
    validate_import_report,
)
from acs.import_registry import ImportRegistry, SourceMutationError


class _BaseImporter:
    format_name = "section0-test"
    suffixes = (".pgn",)


class _ReportSubclassImporter(_BaseImporter):
    def inspect(self, path: Path) -> ImportReport:
        class DerivedReport(ImportReport):
            pass

        return DerivedReport(source=fingerprint(path), format_name=self.format_name)


class _DuplicateRecordImporter(_BaseImporter):
    def inspect(self, path: Path) -> ImportReport:
        return ImportReport(
            source=fingerprint(path),
            format_name=self.format_name,
            records=[
                ImportedRecord("same", ImportQuality.FULL),
                ImportedRecord("same", ImportQuality.PARTIAL, message="truncated metadata"),
            ],
        )


class _MutateThenFailImporter(_BaseImporter):
    def inspect(self, path: Path) -> ImportReport:
        path.write_bytes(b"changed-by-bad-adapter")
        raise RuntimeError("decoder failed after touching source")


class _GoodImporter(_BaseImporter):
    def inspect(self, path: Path) -> ImportReport:
        report = ImportReport(source=fingerprint(path), format_name=self.format_name)
        report.add(ImportedRecord("1", ImportQuality.FULL))
        return report


class Section0ImportReportContractTests(unittest.TestCase):
    def test_non_full_record_requires_explicit_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.pgn"
            path.write_bytes(b"x")
            report = ImportReport(fingerprint(path), "test")

            for quality in (
                ImportQuality.PARTIAL,
                ImportQuality.DAMAGED,
                ImportQuality.WARNING,
            ):
                with self.subTest(quality=quality):
                    with self.assertRaisesRegex(ValueError, "must explain"):
                        report.add(ImportedRecord("record-" + quality.value, quality))

    def test_damaged_and_warning_records_cannot_claim_published_game_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.pgn"
            path.write_bytes(b"x")
            report = ImportReport(fingerprint(path), "test")

            for quality in (ImportQuality.DAMAGED, ImportQuality.WARNING):
                with self.subTest(quality=quality):
                    with self.assertRaisesRegex(ValueError, "cannot publish a game_id"):
                        report.add(
                            ImportedRecord(
                                quality.value,
                                quality,
                                game_id=17,
                                message="not publishable",
                            )
                        )

    def test_partial_record_may_reference_a_published_game_only_with_loss_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.pgn"
            path.write_bytes(b"x")
            report = ImportReport(fingerprint(path), "test")
            report.add(
                ImportedRecord(
                    "partial-1",
                    ImportQuality.PARTIAL,
                    game_id=23,
                    warnings=("source comment could not be represented",),
                )
            )

            self.assertEqual(report.counts["partial"], 1)
            self.assertEqual(report.records[0].game_id, 23)

    def test_report_rejects_duplicate_source_record_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.pgn"
            path.write_bytes(b"x")
            report = ImportReport(
                fingerprint(path),
                "test",
                [
                    ImportedRecord("same", ImportQuality.FULL),
                    ImportedRecord("same", ImportQuality.FULL),
                ],
            )

            with self.assertRaisesRegex(ValueError, "must be unique"):
                validate_import_report(report)

    def test_report_rejects_non_passive_provenance_subclass(self) -> None:
        class DerivedFingerprint(SourceFingerprint):
            pass

        report = ImportReport(
            DerivedFingerprint("/tmp/source.pgn", 1, "0" * 64, ".pgn"),
            "test",
        )
        with self.assertRaisesRegex(TypeError, "exact SourceFingerprint"):
            validate_import_report(report)

    def test_registry_rejects_report_subclass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.pgn"
            path.write_bytes(b"unchanged")
            registry = ImportRegistry()
            registry.register(_ReportSubclassImporter())

            with self.assertRaisesRegex(TypeError, "exact ImportReport"):
                registry.inspect(path)
            self.assertEqual(path.read_bytes(), b"unchanged")

    def test_registry_rejects_duplicate_record_report_from_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.pgn"
            path.write_bytes(b"unchanged")
            registry = ImportRegistry()
            registry.register(_DuplicateRecordImporter())

            with self.assertRaisesRegex(ValueError, "must be unique"):
                registry.inspect(path)
            self.assertEqual(path.read_bytes(), b"unchanged")

    def test_adapter_mutation_cannot_hide_behind_decoder_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.pgn"
            path.write_bytes(b"original")
            registry = ImportRegistry()
            registry.register(_MutateThenFailImporter())

            with self.assertRaisesRegex(SourceMutationError, "modified source bytes"):
                registry.inspect(path)

    def test_batch_keeps_later_valid_source_after_invalid_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp) / "first.pgn"
            second = Path(temp) / "second.pgn"
            first.write_bytes(b"first")
            second.write_bytes(b"second")

            registry = ImportRegistry()
            bad = _DuplicateRecordImporter()
            good = _GoodImporter()
            registry.register(bad)
            # Replace the same suffix only after the first path is inspected by
            # using a small routing importer that switches deterministically.
            class RoutedImporter(_BaseImporter):
                def inspect(self, path: Path) -> ImportReport:
                    return bad.inspect(path) if path.name == "first.pgn" else good.inspect(path)

            registry.register(RoutedImporter(), replace=True)
            batch = registry.inspect_batch((first, second))

            self.assertEqual(len(batch.items), 2)
            self.assertFalse(batch.items[0].ok)
            self.assertIn("must be unique", batch.items[0].error)
            self.assertTrue(batch.items[1].ok)
            self.assertEqual(batch.items[1].report.total, 1)


if __name__ == "__main__":
    unittest.main()
