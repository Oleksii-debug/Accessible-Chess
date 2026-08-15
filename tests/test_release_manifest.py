from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from acs.release_manifest import (
    ReleaseManifest,
    build_release_manifest,
    load_release_manifest,
    read_project_version,
    validate_distribution,
    verify_release_manifest,
)


class ReleaseManifestTests(unittest.TestCase):
    def _good_package(self, root: Path) -> None:
        (root / "AccessibleChess.exe").write_bytes(b"accessible-chess-binary")
        (root / "engine").mkdir()
        (root / "engine" / "stockfish-windows-x64-avx2.exe").write_bytes(b"stockfish")
        (root / "runtime").mkdir()
        (root / "runtime" / "WebView2Loader.dll").write_bytes(b"webview2")
        (root / "assets").mkdir()
        (root / "assets" / "move.wav").write_bytes(b"wave")

    def test_good_compiled_package_passes_release_blockers(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self._good_package(root)
            self.assertEqual(validate_distribution(root), ())

    def test_manifest_is_sorted_stable_and_hashes_exact_bytes(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self._good_package(root)
            manifest = build_release_manifest(root, version="0.4.0-dev3")

            paths = [item.path for item in manifest.files]
            self.assertEqual(paths, sorted(paths, key=str.casefold))
            exe = next(item for item in manifest.files if item.path == "AccessibleChess.exe")
            self.assertEqual(
                exe.sha256,
                hashlib.sha256(b"accessible-chess-binary").hexdigest(),
            )
            self.assertEqual(manifest.version, "0.4.0-dev3")
            self.assertEqual(manifest.as_dict()["schema_version"], 1)
            self.assertTrue(manifest.to_json().endswith("\n"))

    def test_manifest_round_trip_parser_is_strict_and_canonical(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self._good_package(root)
            manifest = build_release_manifest(root, version="0.4.0-dev3")
            parsed = ReleaseManifest.from_json(manifest.to_json())
            self.assertEqual(parsed, manifest)

            value = manifest.as_dict()
            value["files"] = list(reversed(value["files"]))
            with self.assertRaisesRegex(ValueError, "canonical sorted order"):
                ReleaseManifest.from_json(json.dumps(value))

            value = manifest.as_dict()
            value["files"][0]["path"] = "../escape.dll"
            with self.assertRaisesRegex(ValueError, "unsafe release manifest path"):
                ReleaseManifest.from_json(json.dumps(value))

    def test_manifest_checksum_changes_when_binary_changes(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self._good_package(root)
            first = build_release_manifest(root, version="0.4.0-dev3")
            (root / "AccessibleChess.exe").write_bytes(b"tampered")
            second = build_release_manifest(root, version="0.4.0-dev3")
            first_hash = next(x.sha256 for x in first.files if x.path == "AccessibleChess.exe")
            second_hash = next(x.sha256 for x in second.files if x.path == "AccessibleChess.exe")
            self.assertNotEqual(first_hash, second_hash)

    def test_manifest_verifier_detects_modified_missing_and_untracked_payload(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self._good_package(root)
            manifest = build_release_manifest(root, version="0.4.0-dev3")
            self.assertEqual(
                verify_release_manifest(root, manifest, expected_version="0.4.0-dev3"),
                (),
            )

            (root / "AccessibleChess.exe").write_bytes(b"tampered-binary")
            (root / "assets" / "move.wav").unlink()
            (root / "runtime" / "injected.dll").write_bytes(b"unexpected")
            defects = verify_release_manifest(root, manifest, expected_version="0.4.0-dev3")
            self.assertTrue(any("size mismatch" in item or "SHA-256 mismatch" in item for item in defects), defects)
            self.assertTrue(any("manifest file missing: assets/move.wav" in item for item in defects), defects)
            self.assertTrue(any("unexpected unmanifested release file: runtime/injected.dll" in item for item in defects), defects)

    def test_release_metadata_created_after_manifest_is_explicitly_allowed(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self._good_package(root)
            manifest = build_release_manifest(root, version="0.4.0-dev3")
            (root / "RELEASE-MANIFEST.json").write_text(manifest.to_json(), encoding="utf-8")
            (root / "RELEASE-BUILD.txt").write_text("signing_status=UNSIGNED_INTERNAL_BUILD\n", encoding="utf-8")
            self.assertEqual(
                verify_release_manifest(root, manifest, expected_version="0.4.0-dev3"),
                (),
            )

    def test_manifest_verifier_rejects_wrong_product_or_version(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self._good_package(root)
            manifest = build_release_manifest(root, version="0.4.0-dev3", product="Wrong Product")
            defects = verify_release_manifest(root, manifest, expected_version="0.4.0-dev4")
            self.assertTrue(any("product mismatch" in item for item in defects), defects)
            self.assertTrue(any("version mismatch" in item for item in defects), defects)

    def test_manifest_file_loader_accepts_utf8_bom_and_rejects_missing_file(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self._good_package(root)
            manifest = build_release_manifest(root, version="0.4.0-dev3")
            path = root / "RELEASE-MANIFEST.json"
            path.write_text("\ufeff" + manifest.to_json(), encoding="utf-8")
            self.assertEqual(load_release_manifest(path), manifest)
            with self.assertRaisesRegex(ValueError, "release manifest is missing"):
                load_release_manifest(root / "missing.json")

    def test_production_gate_rejects_raw_python_source_and_bytecode(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self._good_package(root)
            (root / "acs").mkdir()
            (root / "acs" / "webapp.py").write_text("print('source leak')\n", encoding="utf-8")
            (root / "acs" / "engine.pyc").write_bytes(b"bytecode")
            defects = validate_distribution(root)
            self.assertTrue(any("raw Python" in item for item in defects), defects)
            self.assertTrue(any("acs/webapp.py" in item for item in defects), defects)

    def test_missing_executable_and_stockfish_are_release_blockers(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "runtime.dll").write_bytes(b"runtime")
            defects = validate_distribution(root)
            self.assertTrue(any("AccessibleChess.exe" in item for item in defects), defects)
            self.assertTrue(any("Stockfish executable" in item for item in defects), defects)

    def test_duplicate_main_executable_is_release_blocker(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self._good_package(root)
            (root / "backup").mkdir()
            (root / "backup" / "accessiblechess.EXE").write_bytes(b"duplicate")
            defects = validate_distribution(root)
            self.assertTrue(any("found 2" in item for item in defects), defects)

    def test_empty_package_and_empty_version_fail_closed(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ValueError):
                build_release_manifest(root, version="0.4.0")
            (root / "file.bin").write_bytes(b"x")
            with self.assertRaises(ValueError):
                build_release_manifest(root, version="   ")

    def test_project_version_is_read_from_single_version_file(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "VERSION.txt"
            path.write_text("0.4.0-dev3\n", encoding="utf-8")
            self.assertEqual(read_project_version(path), "0.4.0-dev3")
            path.write_text("\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_project_version(path)


if __name__ == "__main__":
    unittest.main()
