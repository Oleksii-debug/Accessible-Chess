from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import acs.chessbase_manifest as manifest_module

from acs.chessbase_manifest import (
    build_chessbase_manifest,
    total_manifest_bytes,
    verify_manifest_unchanged,
)


class LegacyCbfManifestPairTests(unittest.TestCase):
    def _symlink_or_skip(self, link: Path, target: Path) -> None:
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable in this environment: {exc}")

    def test_manifest_captures_and_reverifies_required_cbi_companion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = root / "Legacy.CBF"
            companion = root / "legacy.CBI"
            primary_bytes = b"legacy games"
            companion_bytes = b"legacy index"
            primary.write_bytes(primary_bytes)
            companion.write_bytes(companion_bytes)

            manifest = build_chessbase_manifest(primary)

            self.assertEqual(manifest.status, "evidence_collected")
            self.assertEqual([item.extension for item in manifest.all_evidence], [".cbf", ".cbi"])
            self.assertEqual(manifest.components[0].role, "legacy ChessBase index companion")
            self.assertEqual(
                total_manifest_bytes(manifest),
                len(primary_bytes) + len(companion_bytes),
            )
            self.assertEqual(companion.read_bytes(), companion_bytes)
            self.assertEqual(verify_manifest_unchanged(manifest), (True, ()))

            companion.write_bytes(b"legacy indeX")
            ok, problems = verify_manifest_unchanged(manifest)
            self.assertFalse(ok)
            self.assertTrue(any("SHA-256 changed" in problem for problem in problems))

    def test_missing_cbi_is_damaged_and_never_verifies_as_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            primary = Path(directory) / "legacy.cbf"
            primary.write_bytes(b"legacy games")

            manifest = build_chessbase_manifest(primary)

            self.assertEqual(manifest.status, "damaged")
            self.assertIsNotNone(manifest.primary)
            self.assertEqual(manifest.components, ())
            self.assertTrue(any("same-stem .cbi" in warning for warning in manifest.warnings))
            ok, problems = verify_manifest_unchanged(manifest)
            self.assertFalse(ok)
            self.assertTrue(any("family is incomplete or changed" in problem for problem in problems))

    def test_added_cbh_companion_invalidates_manifest_family_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = root / "study.cbh"
            existing = root / "study.cbg"
            added = root / "study.cba"
            primary.write_bytes(b"header")
            existing.write_bytes(b"moves")
            manifest = build_chessbase_manifest(primary)
            added.write_bytes(b"annotation")

            ok, problems = verify_manifest_unchanged(manifest)
            self.assertFalse(ok)
            self.assertTrue(
                any("component family membership changed" in problem for problem in problems)
            )


    def test_cbi_added_after_damaged_manifest_invalidates_family_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            primary = Path(directory) / "legacy.cbf"
            companion = Path(directory) / "legacy.cbi"
            primary.write_bytes(b"legacy games")
            manifest = build_chessbase_manifest(primary)
            companion.write_bytes(b"late index")

            ok, problems = verify_manifest_unchanged(manifest)
            self.assertFalse(ok)
            self.assertTrue(any("companion evidence is unavailable or changed" in problem for problem in problems))


    def test_symlinked_cbi_is_damaged_without_hashing_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = root / "legacy.cbf"
            target = root / "external.cbi"
            companion = root / "legacy.cbi"
            primary.write_bytes(b"legacy games")
            target.write_bytes(b"external index")
            self._symlink_or_skip(companion, target)

            manifest = build_chessbase_manifest(primary)

            self.assertEqual(manifest.status, "damaged")
            self.assertEqual(manifest.components, ())
            ok, problems = verify_manifest_unchanged(manifest)
            self.assertFalse(ok)
            self.assertTrue(problems)

    def test_unreadable_cbi_is_damaged_without_partial_companion_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = root / "legacy.cbf"
            companion = root / "legacy.cbi"
            primary.write_bytes(b"legacy games")
            companion.write_bytes(b"legacy index")
            real_hash_file = manifest_module._hash_file

            def fail_on_cbi(path: Path, *args: object, **kwargs: object):
                if path.suffix.lower() == ".cbi":
                    raise PermissionError("simulated unreadable companion")
                return real_hash_file(path, *args, **kwargs)

            with mock.patch("acs.chessbase_manifest._hash_file", side_effect=fail_on_cbi):
                manifest = build_chessbase_manifest(primary)

            self.assertEqual(manifest.status, "damaged")
            self.assertIsNotNone(manifest.primary)
            self.assertEqual(manifest.components, ())
            self.assertTrue(any("unavailable or unsafe" in warning for warning in manifest.warnings))


if __name__ == "__main__":
    unittest.main()
