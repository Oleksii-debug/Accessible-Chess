from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from acs.version2_upgrade_base import (
    UserDataLayout,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
)


class V2UpgradeGeneratedArtifactAuthenticationTests(unittest.TestCase):
    def _coordinator(self, root: Path) -> Version2UpgradeCoordinator:
        return Version2UpgradeCoordinator(UserDataLayout(root))

    def _assert_symlink_alias_fails_closed(self, relative: str) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            target = Path(td) / "outside-user-data.bin"
            target.write_bytes(b"outside-user-data")
            alias = root / relative
            alias.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.symlink(target, alias)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this runner")

            with self.assertRaisesRegex(
                Version2UpgradeError,
                "symlink or reparse point",
            ):
                self._coordinator(root)._files()

            self.assertEqual(target.read_bytes(), b"outside-user-data")

    def test_exact_generated_runtime_aliases_fail_closed(self):
        digest = "a" * 64
        generated = (
            "gametree-resume.json.abcd_123.tmp",
            "gametree-resume.json.cas-abcd_123.bak",
            ".book-progress.json.abcd_123.tmp",
            ".book-progress.json.bak.abcd_123.tmp",
            ".education-workspace.json.abcd_123.tmp",
            f"training-progress/.{digest}.json.lock",
            f"training-progress/.{digest}.json.abcd_123.tmp",
            "settings.json.tmp",
            ".settings.json.abcd_123.tmp",
            "..v2-upgrade-state.json.abcd_123.tmp",
            ".settings.json.publish-guard-abcdef123456",
            ".library.acsdb.publish-guard-abcdef123456",
        )
        for relative in generated:
            with self.subTest(relative=relative):
                self._assert_symlink_alias_fails_closed(relative)

    def test_derived_runtime_descendant_aliases_fail_closed(self):
        for relative in (
            "sound-cache/cache-entry.wav",
            ".gametree-resume-discard/" + ("b" * 64) + ".guard",
        ):
            with self.subTest(relative=relative):
                self._assert_symlink_alias_fails_closed(relative)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_generated_filename_special_object_is_not_silently_discarded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            fifo = root / "gametree-resume.json.abcd_123.tmp"
            os.mkfifo(fifo)

            with self.assertRaisesRegex(
                Version2UpgradeError,
                "non-regular entry",
            ):
                self._coordinator(root)._files()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_derived_runtime_special_object_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            cache = root / "sound-cache"
            cache.mkdir()
            fifo = cache / "cache-entry"
            os.mkfifo(fifo)

            with self.assertRaisesRegex(
                Version2UpgradeError,
                "regular file or directory",
            ):
                self._coordinator(root)._files()


if __name__ == "__main__":
    unittest.main()
