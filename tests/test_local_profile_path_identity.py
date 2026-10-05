from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from acs.local_profile import (
    LocalProfileStore,
    UnsafeLocalProfilePath,
    new_local_profile,
    serialize_local_profile,
)


class LocalProfilePathIdentityTests(unittest.TestCase):
    def _swap_to_symlink_after_precheck(
        self,
        *,
        selected_path: Path,
        hostile_target: Path,
    ):
        real_is_symlink = Path.is_symlink
        swapped = False

        def swap_after_precheck(path: Path) -> bool:
            nonlocal swapped
            observed = real_is_symlink(path)
            if path == selected_path and not swapped:
                selected_path.unlink()
                try:
                    os.symlink(hostile_target, selected_path)
                except (OSError, NotImplementedError):
                    self.skipTest("symbolic links are not permitted in this environment")
                swapped = True
            return observed

        return swap_after_precheck, lambda: swapped

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_primary_swapped_to_symlink_after_precheck_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = LocalProfileStore(root / "profile.json")
            original = store.create("Alice")
            original_bytes = store.path.read_bytes()

            hostile_target = root / "hostile-target.json"
            hostile_target.write_bytes(serialize_local_profile(new_local_profile("Mallory")))
            hostile_before = hostile_target.read_bytes()
            swap, was_swapped = self._swap_to_symlink_after_precheck(
                selected_path=store.path,
                hostile_target=hostile_target,
            )

            with mock.patch.object(Path, "is_symlink", autospec=True, side_effect=swap):
                with self.assertRaisesRegex(UnsafeLocalProfilePath, "profile path"):
                    store.load()

            self.assertTrue(was_swapped())
            self.assertTrue(store.path.is_symlink())
            self.assertEqual(hostile_target.read_bytes(), hostile_before)
            self.assertNotEqual(hostile_before, original_bytes)
            self.assertEqual(original.display_name, "Alice")

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_recovery_copy_swapped_to_symlink_after_precheck_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = LocalProfileStore(root / "profile.json")
            original = store.create("Alice")
            store.rename(original, "Alice Two")
            corrupt_primary = b"{corrupt-primary"
            store.path.write_bytes(corrupt_primary)

            hostile_target = root / "hostile-backup-target.json"
            hostile_target.write_bytes(serialize_local_profile(new_local_profile("Mallory")))
            hostile_before = hostile_target.read_bytes()
            swap, was_swapped = self._swap_to_symlink_after_precheck(
                selected_path=store.backup_path,
                hostile_target=hostile_target,
            )

            with mock.patch.object(Path, "is_symlink", autospec=True, side_effect=swap):
                with self.assertRaisesRegex(UnsafeLocalProfilePath, "profile path"):
                    store.load()

            self.assertTrue(was_swapped())
            self.assertEqual(store.path.read_bytes(), corrupt_primary)
            self.assertTrue(store.backup_path.is_symlink())
            self.assertEqual(hostile_target.read_bytes(), hostile_before)


if __name__ == "__main__":
    unittest.main()
