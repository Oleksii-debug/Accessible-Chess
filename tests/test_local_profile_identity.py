from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unicodedata
import unittest
from unittest.mock import patch
import uuid

from acs.local_profile import (
    FutureProfileSchemaError,
    LocalProfile,
    LocalProfileError,
    LocalProfileStore,
    MAX_DISPLAY_NAME_CHARS,
    PROFILE_SCHEMA_VERSION,
)


class LocalProfileIdentityTests(unittest.TestCase):
    def test_first_launch_alias_is_derived_only_from_generated_uuid_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            fixed = uuid.UUID("12345678-1234-5678-1234-56789abcdef0")
            store = LocalProfileStore(path)
            with patch("acs.local_profile.uuid.uuid4", return_value=fixed):
                first = store.load_or_create()
            second = store.load_or_create()
            self.assertEqual(first.installation_id, fixed.hex)
            self.assertEqual(first, second)
            self.assertTrue(first.generated_alias)
            expected = int(fixed.hex[-8:], 16) % 10000
            self.assertEqual(first.display_name, f"Учень {expected:04d}")

    def test_skip_after_custom_name_restores_alias_without_changing_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalProfileStore(Path(tmp) / "profile.json", lang="en")
            profile = store.load_or_create()
            named = store.set_display_name(profile, "Alex")
            skipped = store.set_display_name(named, "  ")
            self.assertFalse(named.generated_alias)
            self.assertEqual(named.display_name, "Alex")
            self.assertTrue(skipped.generated_alias)
            self.assertTrue(skipped.display_name.startswith("Player "))
            self.assertEqual(skipped.installation_id, profile.installation_id)

    def test_unicode_display_name_is_nfc_normalized_and_bounded(self):
        decomposed = "Oleksii e\u0301"
        profile = LocalProfile("0" * 32, decomposed, False)
        self.assertEqual(profile.display_name, unicodedata.normalize("NFC", decomposed))
        with self.assertRaises(LocalProfileError):
            LocalProfile("0" * 32, "x" * (MAX_DISPLAY_NAME_CHARS + 1), False)
        with self.assertRaises(LocalProfileError):
            LocalProfile("0" * 32, "bad\nname", False)

    def test_installation_id_and_boolean_schema_are_strict(self):
        for value in ("abc", "g" * 32, "0" * 31, 123):
            with self.subTest(value=value):
                with self.assertRaises(LocalProfileError):
                    LocalProfile(value, "Name", False)
        with self.assertRaises(LocalProfileError):
            LocalProfile("0" * 32, "Name", 1)
        with self.assertRaises(LocalProfileError):
            LocalProfile("0" * 32, "Name", False, schema_version=True)

    def test_corrupt_profile_is_preserved_and_recovered_with_stable_warning_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "profile.json"
            path.write_text("{broken", encoding="utf-8")
            store = LocalProfileStore(path)
            recovered = store.load_or_create()
            self.assertTrue(recovered.generated_alias)
            self.assertEqual(store.warning_code, "profile_recovered_from_invalid_data")
            self.assertTrue((root / "profile.json.broken").exists())
            self.assertTrue(path.exists())

    def test_interrupted_valid_temp_save_recovers_same_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            store = LocalProfileStore(path)
            profile = LocalProfile("1" * 32, "Марія", False)
            store.temporary_path.write_text(
                json.dumps(profile.as_dict(), ensure_ascii=False),
                encoding="utf-8",
            )
            recovered = store.load_or_create()
            self.assertEqual(recovered, profile)
            self.assertEqual(store.warning_code, "profile_recovered_from_interrupted_save")
            self.assertTrue(path.exists())
            self.assertFalse(store.temporary_path.exists())

    def test_invalid_interrupted_temp_is_discarded_and_new_profile_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            store = LocalProfileStore(path)
            store.temporary_path.write_text("{invalid", encoding="utf-8")
            profile = store.load_or_create()
            self.assertTrue(profile.generated_alias)
            self.assertTrue(path.exists())
            self.assertFalse(store.temporary_path.exists())

    def test_future_main_schema_fails_closed_without_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            payload = {
                "schema_version": PROFILE_SCHEMA_VERSION + 1,
                "installation_id": "2" * 32,
                "display_name": "Future",
                "generated_alias": False,
            }
            original = json.dumps(payload, sort_keys=True).encode()
            path.write_bytes(original)
            store = LocalProfileStore(path)
            with self.assertRaises(FutureProfileSchemaError):
                store.load_or_create()
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse((Path(tmp) / "profile.json.broken").exists())

    def test_future_interrupted_temp_fails_closed_and_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            store = LocalProfileStore(path)
            payload = {
                "schema_version": PROFILE_SCHEMA_VERSION + 1,
                "installation_id": "3" * 32,
                "display_name": "Future",
                "generated_alias": False,
            }
            original = json.dumps(payload).encode()
            store.temporary_path.write_bytes(original)
            with self.assertRaises(FutureProfileSchemaError):
                store.load_or_create()
            self.assertFalse(path.exists())
            self.assertEqual(store.temporary_path.read_bytes(), original)

    def test_fsynced_temp_is_preserved_when_final_replace_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            store = LocalProfileStore(path)
            profile = LocalProfile("6" * 32, "Recoverable", False)
            with patch("acs.local_profile.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    store.save(profile)
            self.assertFalse(path.exists())
            self.assertTrue(store.temporary_path.exists())

            recovered = store.load_or_create()
            self.assertEqual(recovered, profile)
            self.assertEqual(
                store.warning_code,
                "profile_recovered_from_interrupted_save",
            )

    def test_save_round_trip_leaves_no_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            store = LocalProfileStore(path)
            profile = store.load_or_create()
            renamed = store.set_display_name(profile, "Олексій")
            self.assertEqual(store.load_or_create(), renamed)
            self.assertFalse(store.temporary_path.exists())

    def test_export_is_explicit_local_json_and_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalProfileStore(Path(tmp) / "profile.json")
            profile = LocalProfile("4" * 32, "Coach", False)
            payload = json.loads(store.export_json(profile))
            self.assertEqual(payload, profile.as_dict())
            self.assertEqual(
                set(payload),
                {"schema_version", "installation_id", "display_name", "generated_alias"},
            )

    def test_delete_hook_removes_only_profile_owned_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "profile.json"
            store = LocalProfileStore(path)
            store.load_or_create()
            store.temporary_path.write_text("stale", encoding="utf-8")
            (root / "profile.json.broken").write_text("old", encoding="utf-8")
            (root / "profile.json.broken.1").write_text("older", encoding="utf-8")
            unrelated = root / "keep.txt"
            unrelated.write_text("keep", encoding="utf-8")

            removed = store.delete_local_identity_data()
            self.assertEqual(
                {item.name for item in removed},
                {
                    "profile.json",
                    "profile.json.tmp",
                    "profile.json.broken",
                    "profile.json.broken.1",
                },
            )
            self.assertTrue(unrelated.exists())
            self.assertFalse(path.exists())

    def test_extra_fields_are_rejected_instead_of_becoming_identity_data(self):
        payload = {
            "schema_version": 1,
            "installation_id": "5" * 32,
            "display_name": "Name",
            "generated_alias": False,
            "unexpected_field": "unexpected-value",
        }
        with self.assertRaises(LocalProfileError):
            LocalProfile.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
