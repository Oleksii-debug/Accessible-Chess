from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from acs.local_profile import LocalProfileStore


class LocalProfileStoreTests(unittest.TestCase):
    def test_first_launch_creates_persistent_alias_and_stable_installation_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            store = LocalProfileStore(path)
            first = store.load_or_create()
            second = store.load_or_create()
            self.assertTrue(first.generated_alias)
            self.assertTrue(first.display_name.startswith("Учень "))
            self.assertEqual(first, second)

    def test_user_name_replaces_alias_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            store = LocalProfileStore(path)
            profile = store.load_or_create()
            renamed = store.set_display_name(profile, "Марія")
            self.assertFalse(renamed.generated_alias)
            self.assertEqual(renamed.display_name, "Марія")
            self.assertEqual(store.load_or_create(), renamed)

    def test_blank_name_is_valid_skip_and_generates_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            store = LocalProfileStore(path, lang="en")
            profile = store.load_or_create()
            named = store.set_display_name(profile, "Alex")
            skipped = store.set_display_name(named, "   ")
            self.assertTrue(skipped.generated_alias)
            self.assertTrue(skipped.display_name.startswith("Player "))
            self.assertEqual(skipped.installation_id, profile.installation_id)

    def test_corrupt_profile_is_preserved_and_recovered_without_exception_leak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            path.write_text("{broken", encoding="utf-8")
            store = LocalProfileStore(path)
            profile = store.load_or_create()
            self.assertTrue(profile.generated_alias)
            self.assertIsNotNone(store.warning)
            self.assertTrue((Path(tmp) / "profile.json.broken").exists())
            self.assertTrue(path.exists())

    def test_wrong_boolean_type_is_rejected_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "installation_id": "abc",
                "display_name": "Name",
                "generated_alias": "false",
            }), encoding="utf-8")
            store = LocalProfileStore(path)
            recovered = store.load_or_create()
            self.assertTrue(recovered.generated_alias)
            self.assertNotEqual(recovered.installation_id, "abc")


if __name__ == "__main__":
    unittest.main()
