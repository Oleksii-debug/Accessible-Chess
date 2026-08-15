from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.chessbase_integrity import (
    ChessBaseSourceChangedError,
    capture_integrity_snapshot,
    verify_integrity_snapshot,
)


class ChessBaseIntegrityTests(unittest.TestCase):
    def test_cbh_snapshot_includes_existing_companions_with_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cbh = root / "sample.cbh"
            cbg = root / "sample.cbg"
            cbp = root / "sample.CBP"
            cbh.write_bytes(b"header")
            cbg.write_bytes(b"moves")
            cbp.write_bytes(b"players")

            snapshot = capture_integrity_snapshot(cbh)

            self.assertEqual(snapshot.primary_path, cbh)
            self.assertEqual([item.extension for item in snapshot.files], [".cbh", ".cbg", ".cbp"])
            self.assertTrue(all(len(item.sha256) == 64 for item in snapshot.files))
            self.assertEqual([item.size_bytes for item in snapshot.files], [6, 5, 7])
            self.assertEqual(verify_integrity_snapshot(snapshot), snapshot)

    def test_changed_component_invalidates_entire_family(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cbh = root / "db.cbh"
            cbg = root / "db.cbg"
            cbh.write_bytes(b"header")
            cbg.write_bytes(b"moves-v1")
            snapshot = capture_integrity_snapshot(cbh)

            cbg.write_bytes(b"moves-v2")

            with self.assertRaises(ChessBaseSourceChangedError):
                verify_integrity_snapshot(snapshot)

    def test_added_component_invalidates_family_membership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cbh = root / "db.cbh"
            cbh.write_bytes(b"header")
            snapshot = capture_integrity_snapshot(cbh)

            (root / "db.cbt").write_bytes(b"events")

            with self.assertRaises(ChessBaseSourceChangedError):
                verify_integrity_snapshot(snapshot)

    def test_unknown_extension_is_rejected_without_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "db.xyz"
            source.write_bytes(b"unknown")
            with self.assertRaises(ValueError):
                capture_integrity_snapshot(source)

    def test_missing_primary_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "missing.cbv"
            with self.assertRaises(FileNotFoundError):
                capture_integrity_snapshot(source)


if __name__ == "__main__":
    unittest.main()
