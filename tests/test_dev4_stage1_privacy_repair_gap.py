from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.import_contract import ImportReport, fingerprint
from acs.import_registry import ImportRegistry


class _ExistingImporter:
    format_name = "QA existing importer"
    suffixes = (".pgn",)

    def inspect(self, path: Path) -> ImportReport:
        return ImportReport(source=fingerprint(path), format_name=self.format_name)


class _PrivatePathOSErrorImporter:
    format_name = "QA private-path OSError"
    suffixes = (".pgn",)

    def inspect(self, path: Path) -> ImportReport:
        fingerprint(path)
        private_sidecar = path.parent / "decoder-cache.bin"
        raise FileNotFoundError(2, "decoder sidecar missing", str(private_sidecar))


class Dev4Stage1PrivacyRepairGapTests(unittest.TestCase):
    def _assert_redacted(self, message: str, safe_name: str) -> None:
        self.assertIn(safe_name, message)
        self.assertNotIn("PrivateUser", message)
        self.assertNotIn("Documents", message)
        self.assertNotIn("Users", message)

    def test_batch_missing_source_error_redacts_private_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "Users" / "PrivateUser" / "Documents" / "analysis.pgn"
            registry = ImportRegistry()
            registry.register(_ExistingImporter())
            batch = registry.inspect_batch((source,))
            self.assertEqual(len(batch.errors), 1)
            self._assert_redacted(batch.errors[0].error, "analysis.pgn")

    def test_batch_importer_oserror_redacts_private_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "Users" / "PrivateUser" / "Documents" / "analysis.pgn"
            source.parent.mkdir(parents=True)
            source.write_text('[Event "QA"]\n[Result "*"]\n\n*\n', encoding="utf-8")
            registry = ImportRegistry()
            registry.register(_PrivatePathOSErrorImporter())
            batch = registry.inspect_batch((source,))
            self.assertEqual(len(batch.errors), 1)
            self._assert_redacted(batch.errors[0].error, "decoder-cache.bin")


if __name__ == "__main__":
    unittest.main()
