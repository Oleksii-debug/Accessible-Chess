from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import acs.user_library_seed as seed_module
from acs.user_library_seed import (
    BUNDLE_KIND,
    SCHEMA_VERSION,
    UserLibrarySeedError,
    load_user_library_seed,
)


_PGN = """[Event "Private seed"]
[White "A"]
[Black "B"]
[Result "*"]

1. e4 e5 *
"""


class UserLibrarySeedParentSafetyTests(unittest.TestCase):
    def _write_seed(self, root: Path) -> None:
        root.mkdir()
        payload = _PGN.encode("utf-8")
        (root / "book.pgn").write_bytes(payload)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "bundle_kind": BUNDLE_KIND,
            "runtime_network_required": False,
            "ai_required": False,
            "files": [
                {
                    "file": "book.pgn",
                    "display_name": "Private seed",
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ],
        }
        (root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def _set_display_name(self, root: Path, value: str) -> None:
        path = root / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"][0]["display_name"] = value
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def test_direct_parent_and_seed_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "release-content"
            parent.mkdir()
            root = parent / "user-library-seed"
            self._write_seed(root)

            loaded = load_user_library_seed(root)

            self.assertEqual(loaded.root, root)
            self.assertEqual(tuple(entry.file_name for entry in loaded.entries), ("book.pgn",))
            self.assertEqual(tuple(entry.display_name for entry in loaded.entries), ("Private seed",))

    def test_redirected_parent_is_rejected_before_manifest_ingress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            real_parent = base / "real-release-content"
            real_parent.mkdir()
            self._write_seed(real_parent / "user-library-seed")
            redirected_parent = base / "release-content"
            try:
                redirected_parent.symlink_to(real_parent, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlink unavailable on this host: {type(exc).__name__}")

            redirected_root = redirected_parent / "user-library-seed"
            self.assertTrue(redirected_root.is_dir())
            with self.assertRaisesRegex(
                UserLibrarySeedError,
                "user Library seed parent directory must be direct",
            ):
                load_user_library_seed(redirected_root)

    def test_display_name_is_not_silently_whitespace_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "release-content"
            parent.mkdir()
            root = parent / "user-library-seed"
            self._write_seed(root)
            self._set_display_name(root, " Private seed ")

            with self.assertRaisesRegex(UserLibrarySeedError, "display name is invalid"):
                load_user_library_seed(root)

    def test_display_name_rejects_multiline_control_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "release-content"
            parent.mkdir()
            root = parent / "user-library-seed"
            self._write_seed(root)
            self._set_display_name(root, "Private seed\nInjected label")

            with self.assertRaisesRegex(UserLibrarySeedError, "display name is invalid"):
                load_user_library_seed(root)

    def test_same_size_manifest_inode_swap_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "release-content"
            parent.mkdir()
            root = parent / "user-library-seed"
            self._write_seed(root)
            manifest_path = root / "manifest.json"
            original = manifest_path.read_bytes()
            replacement_path = root / "replacement.json"
            replacement = json.loads(original.decode("utf-8"))
            replacement["files"][0]["display_name"] = "Foreign seed"
            replacement_bytes = json.dumps(
                replacement,
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            self.assertEqual(
                len(original),
                len(replacement_bytes),
                "regression requires a same-size manifest replacement",
            )
            replacement_path.write_bytes(replacement_bytes)

            real_read_bytes = seed_module.Path.read_bytes
            injected = False

            def swap_before_read(candidate: Path) -> bytes:
                nonlocal injected
                if candidate == manifest_path and not injected:
                    os.replace(replacement_path, manifest_path)
                    injected = True
                return real_read_bytes(candidate)

            with mock.patch.object(
                seed_module.Path,
                "read_bytes",
                autospec=True,
                side_effect=swap_before_read,
            ):
                with self.assertRaisesRegex(
                    UserLibrarySeedError,
                    "manifest changed while reading",
                ):
                    load_user_library_seed(root)

            self.assertTrue(injected)
            self.assertEqual(
                "Foreign seed",
                json.loads(manifest_path.read_text(encoding="utf-8"))["files"][0]["display_name"],
                "foreign replacement was not preserved after rejection",
            )


if __name__ == "__main__":
    unittest.main()
