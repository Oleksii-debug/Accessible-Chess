from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

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

    def test_direct_parent_and_seed_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "release-content"
            parent.mkdir()
            root = parent / "user-library-seed"
            self._write_seed(root)

            loaded = load_user_library_seed(root)

            self.assertEqual(loaded.root, root)
            self.assertEqual(tuple(entry.file_name for entry in loaded.entries), ("book.pgn",))

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


if __name__ == "__main__":
    unittest.main()
