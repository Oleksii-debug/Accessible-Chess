from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.chessbase_integrity import capture_integrity_snapshot
from acs.chessbase_manifest import build_chessbase_manifest


class Dev4ChessBaseSymlinkSecurityTests(unittest.TestCase):
    """QA gate for untrusted ChessBase filesystem indirection.

    The full-product DEV4 security contract requires ChessBase/import inputs to
    fail closed on symlink/reparse-style indirection. These tests intentionally
    exercise public provenance/integrity entry points rather than private helpers.
    """

    def _symlink_or_skip(self, link: Path, target: Path) -> None:
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable in this environment: {exc}")

    def test_integrity_snapshot_rejects_symlink_primary_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "real.cbh"
            target.write_bytes(b"header")
            submitted = root / "submitted.cbh"
            self._symlink_or_skip(submitted, target)

            with self.assertRaises((ValueError, OSError, RuntimeError)):
                capture_integrity_snapshot(submitted)

    def test_manifest_does_not_follow_symlink_primary_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "real.cbh"
            target.write_bytes(b"header")
            submitted = root / "submitted.cbh"
            self._symlink_or_skip(submitted, target)

            manifest = build_chessbase_manifest(submitted)

            self.assertNotIn(manifest.status, {"evidence_collected", "partial"})
            self.assertIsNone(manifest.primary)

    def test_manifest_does_not_hash_symlink_companion_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = root / "db.cbh"
            primary.write_bytes(b"header")
            external_target = root / "external.bin"
            external_target.write_bytes(b"untrusted-moves")
            submitted_component = root / "db.cbg"
            self._symlink_or_skip(submitted_component, external_target)

            manifest = build_chessbase_manifest(primary)

            self.assertEqual(manifest.components, ())


if __name__ == "__main__":
    unittest.main()
