from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.chessbase_adapter import probe_chessbase_source
from acs.chessbase_integrity import (
    ChessBaseIntegrityIOError,
    ChessBaseSourceChangedError,
    capture_integrity_snapshot,
    verify_integrity_snapshot,
)


class Version2TwoCbhCboneTopologyTests(unittest.TestCase):
    def test_2cbh_is_not_misclassified_as_single_file(self) -> None:
        probe = probe_chessbase_source("sample.2cbh")
        self.assertTrue(probe.recognized)
        self.assertTrue(probe.is_primary_source)
        self.assertEqual(probe.source_kind, "multi_file_database_unqualified_topology")
        self.assertEqual(probe.components, ())
        self.assertFalse(probe.decoder_available)
        self.assertFalse(probe.safe_to_import)
        rendered = " ".join(probe.warnings).casefold()
        self.assertIn("multi-file", rendered)
        self.assertIn("fail closed", rendered)

    def test_cbone_remains_truthfully_single_file_without_support_claim(self) -> None:
        probe = probe_chessbase_source("sample.cbone")
        self.assertTrue(probe.recognized)
        self.assertTrue(probe.is_primary_source)
        self.assertEqual(probe.source_kind, "single_file_database")
        self.assertEqual(probe.components, ())
        self.assertFalse(probe.decoder_available)
        self.assertFalse(probe.safe_to_import)
        self.assertTrue(any("single-file" in item.casefold() for item in probe.warnings))

    def test_2cbh_integrity_snapshot_fails_closed_even_when_primary_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            primary = Path(directory) / "modern.2cbh"
            primary.write_bytes(b"header")
            with self.assertRaises(ChessBaseIntegrityIOError) as caught:
                capture_integrity_snapshot(primary)
        rendered = str(caught.exception).casefold()
        self.assertIn("multi-file", rendered)
        self.assertIn("not evidence-qualified", rendered)

    def test_2cbh_does_not_guess_one_observed_companion_completes_family(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = root / "modern.2cbh"
            primary.write_bytes(b"header")
            (root / "modern.2cbg").write_bytes(b"moves")
            with self.assertRaises(ChessBaseIntegrityIOError):
                capture_integrity_snapshot(primary)

    def test_cbone_single_file_integrity_round_trip_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "portable.cbone"
            source.write_bytes(b"single-file-database")
            snapshot = capture_integrity_snapshot(source)
            self.assertEqual([item.extension for item in snapshot.files], [".cbone"])
            self.assertEqual(verify_integrity_snapshot(snapshot), snapshot)

    def test_cbone_mutation_invalidates_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "portable.cbone"
            source.write_bytes(b"version-one")
            snapshot = capture_integrity_snapshot(source)
            source.write_bytes(b"version-two")
            with self.assertRaises(ChessBaseSourceChangedError):
                verify_integrity_snapshot(snapshot)


if __name__ == "__main__":
    unittest.main()
