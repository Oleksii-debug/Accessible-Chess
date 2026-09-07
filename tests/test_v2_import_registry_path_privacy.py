from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.import_contract import ImportReport, SourceFingerprint, fingerprint
from acs.import_registry import ImportRegistry, SourceMutationError, SourceProvenanceError


class _WrongProvenanceImporter:
    format_name = "PGN"
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
    format_name = "PGN"
    suffixes = (".pgn",)

    def inspect(self, path: Path) -> ImportReport:
        before = fingerprint(path)
        path.write_bytes(path.read_bytes() + b" changed")
        return ImportReport(source=before, format_name=self.format_name)


class _PrivateOSErrorImporter:
    format_name = "PGN"
    suffixes = (".pgn",)

    def inspect(self, path: Path) -> ImportReport:
        raise OSError(
            5,
            r"decoder failed while reading C:\Users\PrivateBackend\cache.bin",
            str(path.parent / "decoder-cache.bin"),
        )


class _PrivateValueErrorImporter:
    format_name = "PGN"
    suffixes = (".pgn",)

    def inspect(self, path: Path) -> ImportReport:
        raise ValueError(f"invalid metadata at {path.parent / 'decoder-cache.bin'}")


class _PrivateRuntimeErrorImporter:
    format_name = "PGN"
    suffixes = (".pgn",)

    def inspect(self, path: Path) -> ImportReport:
        raise RuntimeError(
            r"backend crashed at C:\Users\PrivateBackend\Documents\decoder.dll"
        )


class _KeyboardInterruptImporter:
    format_name = "PGN"
    suffixes = (".pgn",)

    def inspect(self, path: Path) -> ImportReport:
        raise KeyboardInterrupt()


class V2ImportRegistryPathPrivacyTests(unittest.TestCase):
    SAFE_NAME = "analysis.pgn"

    def _source(self, root: Path) -> Path:
        source = root / "Users" / "PrivateUser" / "Documents" / self.SAFE_NAME
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"source")
        return source

    def _assert_private_parent_hidden(self, message: str, *, name: str | None = None) -> None:
        if name is not None:
            self.assertIn(name, message)
        self.assertNotIn("PrivateUser", message)
        self.assertNotIn("Documents", message)
        self.assertNotIn("Users", message)

    def test_direct_mutation_and_provenance_errors_expose_only_safe_source_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            source = self._source(root)
            registry = ImportRegistry()
            registry.register(_WrongProvenanceImporter())
            with self.assertRaises(SourceProvenanceError) as raised:
                registry.inspect(source)
            self._assert_private_parent_hidden(str(raised.exception), name=self.SAFE_NAME)

            source = self._source(root)
            registry = ImportRegistry()
            registry.register(_MutatingImporter())
            with self.assertRaises(SourceMutationError) as raised:
                registry.inspect(source)
            self._assert_private_parent_hidden(str(raised.exception), name=self.SAFE_NAME)

    def test_batch_oserror_does_not_republish_path_bearing_strerror(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._source(Path(directory))
            registry = ImportRegistry()
            registry.register(_PrivateOSErrorImporter())

            error = registry.inspect_batch((source,)).errors[0].error

            self._assert_private_parent_hidden(error)
            self.assertIn("Filesystem error", error)
            self.assertIn("errno 5", error)
            self.assertIn("decoder-cache.bin", error)
            self.assertNotIn("PrivateBackend", error)
            self.assertNotIn("decoder failed", error)

    def test_batch_valueerror_and_runtimeerror_do_not_republish_adapter_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._source(Path(directory))
            for importer in (_PrivateValueErrorImporter(), _PrivateRuntimeErrorImporter()):
                with self.subTest(importer=type(importer).__name__):
                    registry = ImportRegistry()
                    registry.register(importer)
                    error = registry.inspect_batch((source,)).errors[0].error
                    self._assert_private_parent_hidden(error, name=self.SAFE_NAME)
                    self.assertIn("Importer rejected source", error)
                    self.assertNotIn("decoder-cache.bin", error)
                    self.assertNotIn("PrivateBackend", error)
                    self.assertNotIn("backend crashed", error)

    def test_missing_and_unknown_batch_sources_do_not_expose_private_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Users" / "PrivateUser" / "Documents"
            missing = root / self.SAFE_NAME
            unknown = root / "study.unknown"

            registry = ImportRegistry()
            registry.register(_WrongProvenanceImporter())
            batch = registry.inspect_batch((missing, unknown))

            self.assertEqual(len(batch.errors), 2)
            for item in batch.errors:
                self._assert_private_parent_hidden(item.error)
            self.assertIn(self.SAFE_NAME, batch.errors[0].error)
            self.assertIn(".unknown", batch.errors[1].error)

    def test_process_control_exceptions_are_not_swallowed_by_batch_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._source(Path(directory))
            registry = ImportRegistry()
            registry.register(_KeyboardInterruptImporter())
            with self.assertRaises(KeyboardInterrupt):
                registry.inspect_batch((source,))


if __name__ == "__main__":
    unittest.main()
