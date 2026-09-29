from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.local_profile import LocalProfileStore
from acs.version2_local_profile_api import Version2ProfileAccessibleChessAPI


class Version2LocalProfileApiTests(unittest.TestCase):
    def make_api(self, root: Path) -> Version2ProfileAccessibleChessAPI:
        return Version2ProfileAccessibleChessAPI(
            keymap_path=root / "keymap.json",
            profile_store=LocalProfileStore(root / "profile.json"),
        )

    def test_first_launch_explicit_name_persists_and_stable_id_stays_private(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            api = self.make_api(root)

            before = api.profile_snapshot()
            self.assertTrue(before["ok"])
            self.assertFalse(before["exists"])

            created = api.profile_create("  Oleksii   Chess  ", False)
            self.assertTrue(created["ok"])
            self.assertEqual(created["displayName"], "Oleksii Chess")
            self.assertFalse(created["generatedAlias"])
            self.assertNotIn("profileId", created)
            self.assertNotIn("profile_id", created)

            reopened = self.make_api(root).profile_snapshot()
            self.assertEqual(reopened["displayName"], "Oleksii Chess")
            self.assertEqual(reopened["revision"], 1)

    def test_skip_creates_private_generated_alias_and_rename_preserves_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = LocalProfileStore(root / "profile.json")
            api = Version2ProfileAccessibleChessAPI(
                keymap_path=root / "keymap.json",
                profile_store=store,
            )

            skipped = api.profile_create("", True)
            self.assertTrue(skipped["ok"])
            self.assertTrue(skipped["generatedAlias"])
            self.assertRegex(str(skipped["displayName"]), r"^Player-[0-9A-F]{8}$")
            original = store.load()
            self.assertIsNotNone(original)

            renamed = api.profile_rename("Coach")
            self.assertTrue(renamed["ok"])
            self.assertEqual(renamed["displayName"], "Coach")
            self.assertFalse(renamed["generatedAlias"])
            current = store.load()
            self.assertEqual(current.profile_id, original.profile_id)
            self.assertEqual(current.revision, original.revision + 1)

    def test_corrupt_state_fails_closed_without_fabricating_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile_path = root / "profile.json"
            profile_path.write_text("{broken", encoding="utf-8")
            api = self.make_api(root)

            snapshot = api.profile_snapshot()
            self.assertFalse(snapshot["ok"])
            self.assertTrue(profile_path.exists())

            attempted = api.profile_create("Replacement", False)
            self.assertFalse(attempted["ok"])
            self.assertEqual(profile_path.read_text(encoding="utf-8"), "{broken")

    def test_backup_fallback_requires_explicit_repair_before_rename(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = LocalProfileStore(root / "profile.json")
            original = store.create("First")
            current = store.rename(original, "Second")
            self.assertEqual(current.display_name, "Second")
            profile_path = root / "profile.json"
            profile_path.write_text("{broken", encoding="utf-8")

            api = Version2ProfileAccessibleChessAPI(
                keymap_path=root / "keymap.json",
                profile_store=store,
            )
            fallback = api.profile_snapshot()
            self.assertTrue(fallback["ok"])
            self.assertTrue(fallback["exists"])
            self.assertTrue(fallback["recoveryRequired"])
            self.assertEqual(fallback["displayName"], "First")

            rejected = api.profile_rename("Third")
            self.assertFalse(rejected["ok"])
            self.assertEqual(profile_path.read_text(encoding="utf-8"), "{broken")

            repaired = api.profile_repair()
            self.assertTrue(repaired["ok"])
            self.assertFalse(repaired["recoveryRequired"])
            self.assertEqual(repaired["displayName"], "First")
            self.assertEqual(store.load().profile_id, original.profile_id)

            renamed = api.profile_rename("Third")
            self.assertTrue(renamed["ok"])
            self.assertEqual(renamed["displayName"], "Third")

    def test_blank_explicit_name_is_rejected_but_skip_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            api = self.make_api(root)

            rejected = api.profile_create("   ", False)
            self.assertFalse(rejected["ok"])
            self.assertFalse(api.profile_snapshot()["exists"])

            skipped = api.profile_create("", True)
            self.assertTrue(skipped["ok"])
            self.assertTrue(skipped["generatedAlias"])


if __name__ == "__main__":
    unittest.main()
