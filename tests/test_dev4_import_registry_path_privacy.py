from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.import_contract import ImportReport, SourceFingerprint, fingerprint
from acs.import_registry import ImportRegistry, SourceMutationError, SourceProvenanceError


class _WrongProvenanceImporter:
    format_name = "QA wrong provenance"
    suffixes = (".pgn",)

    def inspect(self, path: Path) -> ImportReport:
        actual = fingerprint(path)
        forged = SourceFingerprint(
            path=str(path.parent / "different.pgn"),
            size=actual.size,
            sha256=actual.sha256,
            suffix=actual.suffix,
        )
        return ImportReport(source=forged, format_name=self.format_name)


class _MutatingImporter:
    format_name = "QA mutator"
    suffixes = (".pgn",)

    def inspect(self, path: Path) -> ImportReport:
        before = fingerprint(path)
        path.write_bytes(path.read_bytes() + b"\n")
        return ImportReport(source=before, format_name=self.format_name)


class _PrivatePathOSErrorImporter:
    format_name = "QA private-path OSError"
    suffixes = (".pgn",)

    def inspect(self, path: Path) -> ImportReport:
        fingerprint(path)
        private_sidecar = path.parent / "decoder-cache.bin"
        raise FileNotFoundError(2, "decoder sidecar missing", str(private_sidecar))


class Dev4ImportRegistryPathPrivacyTests(unittest.TestCase):
    SAFE_NAME = "analysis.pgn"

    def _private_source(self, root: Path) -> Path:
        source = root / "Users" / "PrivateUser" / "Documents" / self.SAFE_NAME
        source.parent.mkdir(parents=True)
        source.write_text('[Event "QA"]\n[Result "*"]\n\n*\n', encoding="utf-8")
        return source

    def _assert_safe_error(self, message: str, *, safe_name: str | None = None) -> None:
        self.assertIn(safe_name or self.SAFE_NAME, message)
        self.assertNotIn("PrivateUser", message)
        self.assertNotIn("Documents", message)
        self.assertNotIn("Users", message)

    def test_provenance_mismatch_error_does_not_leak_absolute_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._private_source(Path(directory))
            registry = ImportRegistry()
            registry.register(_WrongProvenanceImporter())
            with self.assertRaises(SourceProvenanceError) as caught:
                registry.inspect(source)
            self._assert_safe_error(str(caught.exception))

    def test_mutation_error_does_not_leak_absolute_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._private_source(Path(directory))
            registry = ImportRegistry()
            registry.register(_MutatingImporter())
            with self.assertRaises(SourceMutationError) as caught:
                registry.inspect(source)
            self._assert_safe_error(str(caught.exception))

    def test_batch_error_payload_does_not_republish_private_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._private_source(Path(directory))
            registry = ImportRegistry()
            registry.register(_WrongProvenanceImporter())
            batch = registry.inspect_batch((source,))
            self.assertEqual(len(batch.errors), 1)
            self._assert_safe_error(batch.errors[0].error)

    def test_batch_missing_source_error_does_not_leak_absolute_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "Users" / "PrivateUser" / "Documents" / self.SAFE_NAME
            registry = ImportRegistry()
            registry.register(_WrongProvenanceImporter())
            batch = registry.inspect_batch((source,))
            self.assertEqual(len(batch.errors), 1)
            self._assert_safe_error(batch.errors[0].error)

    def test_batch_importer_oserror_does_not_republish_private_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._private_source(Path(directory))
            registry = ImportRegistry()
            registry.register(_PrivatePathOSErrorImporter())
            batch = registry.inspect_batch((source,))
            self.assertEqual(len(batch.errors), 1)
            self._assert_safe_error(batch.errors[0].error, safe_name="decoder-cache.bin")


if __name__ == "__main__":
    unittest.main()
