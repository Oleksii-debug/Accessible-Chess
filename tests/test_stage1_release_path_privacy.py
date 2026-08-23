from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs import pgn_service
from acs.engine import UCIEngine
from acs.gametree import parse_games
from acs.import_contract import ImportReport, SourceFingerprint, fingerprint
from acs.import_registry import ImportRegistry, SourceMutationError, SourceProvenanceError
from acs.pgn_service import PgnConcurrentWriteError, PgnSourceChangedError, open_pgn, save_pgn_atomic
from acs.report_paths import report_safe_name


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
        path.write_bytes(path.read_bytes() + b"\n")
        return ImportReport(source=before, format_name=self.format_name)


class _PrivatePathOSErrorImporter:
    format_name = "PGN"
    suffixes = (".pgn",)

    def inspect(self, path: Path) -> ImportReport:
        fingerprint(path)
        private_sidecar = path.parent / "decoder-cache.bin"
        raise FileNotFoundError(2, "decoder sidecar missing", str(private_sidecar))


class _PrivateStrerrorOSErrorImporter:
    format_name = "PGN"
    suffixes = (".pgn",)

    def inspect(self, path: Path) -> ImportReport:
        fingerprint(path)
        private_sidecar = r"C:\Users\PrivateUser\Documents\decoder-cache.bin"
        raise OSError(5, f"decoder failed while reading {private_sidecar}", str(path))


class _PrivatePathValueErrorImporter:
    format_name = "PGN"
    suffixes = (".pgn",)

    def inspect(self, path: Path) -> ImportReport:
        fingerprint(path)
        raise ValueError(f"invalid decoder metadata at {path.parent / 'decoder-cache.bin'}")


class Stage1ReleasePathPrivacyTests(unittest.TestCase):
    SAFE_NAME = "analysis.pgn"

    def _private_source(self, root: Path) -> Path:
        source = root / "Users" / "PrivateUser" / "Documents" / self.SAFE_NAME
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text('[Event "QA"]\n[Result "*"]\n\n*\n', encoding="utf-8")
        return source

    def _assert_safe(self, message: str, name: str = SAFE_NAME) -> None:
        self.assertIn(name, message)
        self.assertNotIn("PrivateUser", message)
        self.assertNotIn("Documents", message)
        self.assertNotIn("Users", message)

    def test_report_safe_name_is_cross_platform_and_preserves_safe_relative_provenance(self) -> None:
        self.assertEqual(report_safe_name(r"C:\Users\PrivateUser\Documents\analysis.pgn"), "analysis.pgn")
        self.assertEqual(report_safe_name(r"C:Users\PrivateUser\Documents\analysis.pgn"), "analysis.pgn")
        self.assertEqual(report_safe_name(r"D:WorkstationOwner\Chess\study.pgn"), "study.pgn")
        self.assertEqual(report_safe_name("/home/private/Documents/analysis.pgn"), "analysis.pgn")
        self.assertEqual(report_safe_name(r"\\server\share\PrivateUser\analysis.pgn"), "analysis.pgn")
        self.assertEqual(report_safe_name(r"incoming\analysis.pgn"), "incoming/analysis.pgn")
        self.assertEqual(report_safe_name("incoming/../analysis.pgn"), "analysis.pgn")

    def test_existing_destination_error_redacts_private_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = self._private_source(Path(directory))
            with self.assertRaises(FileExistsError) as raised:
                save_pgn_atomic(destination, parse_games('[Event "New"]\n[Result "*"]\n\n*\n'))
            self._assert_safe(str(raised.exception))

    def test_expected_hash_mismatch_redacts_private_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = self._private_source(Path(directory))
            with self.assertRaises(PgnConcurrentWriteError) as raised:
                save_pgn_atomic(
                    destination,
                    parse_games('[Event "New"]\n[Result "*"]\n\n*\n'),
                    overwrite=True,
                    expected_sha256="0" * 64,
                )
            self._assert_safe(str(raised.exception))

    def test_source_changed_error_redacts_private_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._private_source(Path(directory))
            actual = fingerprint(source)
            changed = SourceFingerprint(
                path=actual.path,
                size=actual.size,
                sha256="0" * 64,
                suffix=actual.suffix,
            )
            with mock.patch.object(pgn_service, "fingerprint", side_effect=[actual, changed]):
                with self.assertRaises(PgnSourceChangedError) as raised:
                    open_pgn(source)
            self._assert_safe(str(raised.exception))

    def test_import_registry_provenance_mutation_and_batch_errors_redact_private_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._private_source(root)
            registry = ImportRegistry()
            registry.register(_WrongProvenanceImporter())
            with self.assertRaises(SourceProvenanceError) as raised:
                registry.inspect(source)
            self._assert_safe(str(raised.exception))
            batch = registry.inspect_batch((source,))
            self.assertEqual(len(batch.errors), 1)
            self._assert_safe(batch.errors[0].error)

            source = self._private_source(root)
            mutating = ImportRegistry()
            mutating.register(_MutatingImporter())
            with self.assertRaises(SourceMutationError) as raised:
                mutating.inspect(source)
            self._assert_safe(str(raised.exception))

    def test_import_registry_batch_missing_source_redacts_filesystem_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "Users" / "PrivateUser" / "Documents" / self.SAFE_NAME
            registry = ImportRegistry()
            registry.register(_WrongProvenanceImporter())
            batch = registry.inspect_batch((source,))
            self.assertEqual(len(batch.errors), 1)
            self._assert_safe(batch.errors[0].error)

    def test_import_registry_batch_importer_oserror_redacts_sidecar_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._private_source(Path(directory))
            registry = ImportRegistry()
            registry.register(_PrivatePathOSErrorImporter())
            batch = registry.inspect_batch((source,))
            self.assertEqual(len(batch.errors), 1)
            self._assert_safe(batch.errors[0].error, "decoder-cache.bin")

    def test_import_registry_batch_oserror_does_not_republish_untrusted_strerror(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._private_source(Path(directory))
            registry = ImportRegistry()
            registry.register(_PrivateStrerrorOSErrorImporter())
            batch = registry.inspect_batch((source,))
            self.assertEqual(len(batch.errors), 1)
            error = batch.errors[0].error
            self._assert_safe(error)
            self.assertIn("Filesystem error", error)
            self.assertIn("errno 5", error)
            self.assertNotIn("decoder-cache.bin", error)
            self.assertNotIn("decoder failed", error)
            self.assertNotIn(r"C:\Users", error)

    def test_import_registry_batch_valueerror_does_not_republish_importer_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._private_source(Path(directory))
            registry = ImportRegistry()
            registry.register(_PrivatePathValueErrorImporter())
            batch = registry.inspect_batch((source,))
            self.assertEqual(len(batch.errors), 1)
            self._assert_safe(batch.errors[0].error)
            self.assertNotIn("decoder-cache.bin", batch.errors[0].error)

    def test_engine_start_failure_redacts_private_executable_path_and_preserves_cause(self) -> None:
        private_path = r"C:\Users\PrivateUser\Documents\Engines\stockfish.exe"

        def failing_factory(*args, **kwargs):
            raise FileNotFoundError(2, "No such file or directory", private_path)

        engine = UCIEngine(private_path, process_factory=failing_factory)
        with self.assertRaises(RuntimeError) as raised:
            engine.start()
        self.assertIn("Unable to start Stockfish", str(raised.exception))
        self.assertNotIn("PrivateUser", str(raised.exception))
        self.assertNotIn("Documents", str(raised.exception))
        self.assertNotIn("Users", str(raised.exception))
        self.assertIsInstance(raised.exception.__cause__, FileNotFoundError)


if __name__ == "__main__":
    unittest.main()
