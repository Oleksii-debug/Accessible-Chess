from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.import_contract import ImportQuality, ImportReport, ImportedRecord, fingerprint
from acs.import_registry import ImportRegistry


class RuntimeFailingImporter:
    format_name = "Runtime-failing fake importer"
    suffixes = (".boom",)

    def inspect(self, path: Path) -> ImportReport:
        raise RuntimeError("decoder/provider runtime failure")


class HealthyImporter:
    format_name = "Healthy fake importer"
    suffixes = (".ok",)

    def inspect(self, path: Path) -> ImportReport:
        report = ImportReport(source=fingerprint(path), format_name=self.format_name)
        report.add(ImportedRecord("1", ImportQuality.FULL, message="ok"))
        return report


class Dev4ImportBatchAdapterFailureTests(unittest.TestCase):
    """QA gate for the non-aborting multi-source import preflight contract."""

    def test_runtime_adapter_failure_is_recorded_and_later_sources_are_still_inspected(self) -> None:
        """One importer runtime failure must not abort the remaining batch.

        ``ImportRegistry.inspect_batch`` documents adapter errors as per-source
        results and promises that later sources are still inspected. A decoder
        or provider can legitimately fail with ``RuntimeError``; that failure
        must become a failed ``BatchInspectionItem`` rather than escaping the
        batch boundary and hiding subsequent evidence.
        """

        registry = ImportRegistry()
        registry.register(RuntimeFailingImporter())
        registry.register(HealthyImporter())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failing = root / "first.boom"
            healthy = root / "second.ok"
            failing.write_bytes(b"decoder input")
            healthy.write_bytes(b"healthy input")

            batch = registry.inspect_batch([failing, healthy])

            self.assertEqual([item.path for item in batch.items], [failing, healthy])
            self.assertEqual([item.ok for item in batch.items], [False, True])
            self.assertIn("runtime failure", batch.items[0].error.lower())
            self.assertEqual(len(batch.reports), 1)
            self.assertEqual(batch.reports[0].source.sha256, fingerprint(healthy).sha256)


if __name__ == "__main__":
    unittest.main()
