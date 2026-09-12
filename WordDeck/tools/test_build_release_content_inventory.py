#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import build_release_content_inventory as builder


class PackageInventoryTests(unittest.TestCase):
    def _package(self, root: Path) -> dict:
        (root / "Content").mkdir(parents=True)
        (root / "AudioPacks" / "starter").mkdir(parents=True)
        (root / "Content" / "lesson.json").write_text('{"lesson":"one"}\n', encoding="utf-8")
        (root / "AudioPacks" / "starter" / "clip.mp3").write_bytes(b"fake-audio-for-hash-test")
        return {
            "schema_version": "1.0",
            "content_roots": ["Content", "AudioPacks"],
            "assets": [
                {"asset_id": "wd:lesson:one", "path": "Content/lesson.json"},
                {"asset_id": "wd:audio:one", "path": "AudioPacks/starter/clip.mp3"},
            ],
        }

    def test_inventory_hashes_actual_packaged_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            index = self._package(root)
            inventory, errors = builder.build_inventory(root, index, "release-1", "windows_offline")
            self.assertEqual([], errors)
            by_id = {item["asset_id"]: item for item in inventory["assets"]}
            expected = hashlib.sha256((root / "Content" / "lesson.json").read_bytes()).hexdigest()
            self.assertEqual(expected, by_id["wd:lesson:one"]["content_hash_sha256"])
            self.assertEqual("Content/lesson.json", by_id["wd:lesson:one"]["package_path"])
            self.assertEqual("CONTENT_ASSET_INDEX.json+actual_packaged_bytes", inventory["package_inventory_source"])

    def test_real_package_unregistered_content_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            index = self._package(root)
            (root / "Content" / "unregistered.json").write_text("{}\n", encoding="utf-8")
            _, errors = builder.build_inventory(root, index, "release-1", "windows_offline")
            self.assertTrue(any("unregistered packaged content file: Content/unregistered.json" in error for error in errors), errors)

    def test_indexed_missing_content_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            index = self._package(root)
            (root / "AudioPacks" / "starter" / "clip.mp3").unlink()
            _, errors = builder.build_inventory(root, index, "release-1", "windows_offline")
            self.assertTrue(any("indexed packaged content file is missing" in error for error in errors), errors)

    def test_duplicate_asset_or_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            index = self._package(root)
            index["assets"].append({"asset_id": "wd:lesson:one", "path": "AudioPacks/starter/clip.mp3"})
            _, errors = builder.build_inventory(root, index, "release-1", "windows_offline")
            self.assertTrue(any("duplicate asset ID" in error for error in errors), errors)
            self.assertTrue(any("duplicate packaged path" in error for error in errors), errors)

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            index = self._package(root)
            index["assets"][0]["path"] = "../outside.json"
            _, errors = builder.build_inventory(root, index, "release-1", "windows_offline")
            self.assertTrue(any("unsafe/non-normal relative path" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
