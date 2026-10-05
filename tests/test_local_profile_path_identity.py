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

            real_is_symlink = Path.is_symlink
            swapped = False

            def swap_after_precheck(path: Path) -> bool:
                nonlocal swapped
                observed = real_is_symlink(path)
                if path == store.path and not swapped:
                    store.path.unlink()
                    try:
                        os.symlink(hostile_target, store.path)
                    except (OSError, NotImplementedError):
                        self.skipTest("symbolic links are not permitted in this environment")
                    swapped = True
                return observed

            with mock.patch.object(Path, "is_symlink", autospec=True, side_effect=swap_after_precheck):
                with self.assertRaisesRegex(UnsafeLocalProfilePath, "profile path"):
                    store.load()

            self.assertTrue(swapped)
            self.assertTrue(store.path.is_symlink())
            self.assertEqual(hostile_target.read_bytes(), hostile_before)
            self.assertNotEqual(hostile_before, original_bytes)
            self.assertEqual(original.display_name, "Alice")


if __name__ == "__main__":
    unittest.main()
