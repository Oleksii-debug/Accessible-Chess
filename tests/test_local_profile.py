from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from acs.local_profile import (
    LocalProfileConflict,
    LocalProfileError,
    LocalProfileStore,
    MAX_DISPLAY_NAME_CHARS,
    MAX_PROFILE_BYTES,
    UnsupportedLocalProfileSchema,
    new_local_profile,
    parse_local_profile_bytes,
    serialize_local_profile,
)


class LocalProfileContractTests(unittest.TestCase):
    def test_explicit_unicode_name_round_trips(self) -> None:
        profile = new_local_profile("  Олексій   Шахіст  ")
        self.assertEqual(profile.display_name, "Олексій Шахіст")
        self.assertFalse(profile.generated_alias)
        restored = parse_local_profile_bytes(serialize_local_profile(profile))
        self.assertEqual(restored, profile)

    def test_skip_alias_is_random_only_and_does_not_leak_os_identity(self) -> None:
        leaked_markers = {
            "USERNAME": "SECRET-WINDOWS-USER",
            "USER": "SECRET-POSIX-USER",
            "COMPUTERNAME": "SECRET-PC-NAME",
        }
        with mock.patch.dict(os.environ, leaked_markers, clear=False):
            profile = new_local_profile(None)
        self.assertRegex(profile.display_name, r"^Player-[0-9A-F]{8}$")
        self.assertTrue(profile.generated_alias)
        serialized = serialize_local_profile(profile).decode("utf-8")
        for marker in leaked_markers.values():
            self.assertNotIn(marker, serialized)

    def test_duplicate_authority_field_is_rejected(self) -> None:
        profile = new_local_profile("Alex")
        payload = serialize_local_profile(profile).decode("utf-8").strip()
        payload = payload[:-1] + ',"revision":99}'
        with self.assertRaisesRegex(LocalProfileError, "duplicate profile field"):
            parse_local_profile_bytes(payload.encode("utf-8"))

    def test_unknown_and_missing_fields_are_rejected(self) -> None:
        profile = new_local_profile("Alex")
        payload = json.loads(serialize_local_profile(profile))
        payload["unexpected"] = True
        with self.assertRaisesRegex(LocalProfileError, "profile fields are invalid"):
            parse_local_profile_bytes(json.dumps(payload).encode("utf-8"))
        del payload["unexpected"]
        del payload["revision"]
        with self.assertRaisesRegex(LocalProfileError, "profile fields are invalid"):
            parse_local_profile_bytes(json.dumps(payload).encode("utf-8"))

    def test_malformed_utf8_and_oversized_payload_fail_closed(self) -> None:
        with self.assertRaisesRegex(LocalProfileError, "valid UTF-8"):
            parse_local_profile_bytes(b"\xff\xfe\x00")
        with self.assertRaisesRegex(LocalProfileError, "too large"):
            parse_local_profile_bytes(b"{" + b" " * MAX_PROFILE_BYTES + b"}")

    def test_display_name_bounds_and_controls(self) -> None:
        profile = new_local_profile("x" * MAX_DISPLAY_NAME_CHARS)
        self.assertEqual(len(profile.display_name), MAX_DISPLAY_NAME_CHARS)
        with self.assertRaisesRegex(LocalProfileError, "too long"):
            new_local_profile("x" * (MAX_DISPLAY_NAME_CHARS + 1))
        with self.assertRaisesRegex(LocalProfileError, "control"):
            new_local_profile("Alex\nAdmin")


class LocalProfileStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = LocalProfileStore(self.root / "profile.json")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_create_skip_persists_same_alias_and_identifier(self) -> None:
        created = self.store.create(None)
        reopened = LocalProfileStore(self.store.path).load()
        self.assertEqual(reopened, created)
        self.assertRegex(created.profile_id, r"^[0-9a-f]{32}$")
        self.assertTrue(created.generated_alias)

    def test_create_refuses_to_replace_existing_identity(self) -> None:
        first = self.store.create("Alice")
        before = self.store.path.read_bytes()
        with self.assertRaises(LocalProfileConflict):
            self.store.create("Bob")
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.store.load(), first)

    def test_rename_preserves_identity_creates_exact_backup_and_increments_revision(self) -> None:
        original = self.store.create(None)
        original_bytes = self.store.path.read_bytes()
        renamed = self.store.rename(original, "  Alice   Coach ")
        self.assertEqual(renamed.profile_id, original.profile_id)
        self.assertEqual(renamed.display_name, "Alice Coach")
        self.assertFalse(renamed.generated_alias)
        self.assertEqual(renamed.revision, original.revision + 1)
        self.assertEqual(self.store.backup_path.read_bytes(), original_bytes)
        self.assertEqual(self.store.load(), renamed)

    def test_stale_rename_cannot_clobber_newer_state(self) -> None:
        original = self.store.create("Alice")
        current = self.store.rename(original, "Alice Two")
        before = self.store.path.read_bytes()
        with self.assertRaises(LocalProfileConflict):
            self.store.rename(original, "Stale Writer")
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.store.load(), current)

    def test_corrupt_primary_recovers_from_verified_backup_without_rewriting(self) -> None:
        original = self.store.create("Alice")
        renamed = self.store.rename(original, "Alice Two")
        backup_before = self.store.backup_path.read_bytes()
        corrupt = b"{not-json"
        self.store.path.write_bytes(corrupt)
        recovered = self.store.load()
        self.assertEqual(recovered, original)
        self.assertNotEqual(recovered, renamed)
        self.assertEqual(self.store.path.read_bytes(), corrupt)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_before)

    def test_missing_primary_recovers_from_backup_instead_of_fabricating_identity(self) -> None:
        original = self.store.create("Alice")
        self.store.rename(original, "Alice Two")
        self.store.path.unlink()
        recovered = self.store.load()
        self.assertEqual(recovered, original)
        with self.assertRaises(LocalProfileConflict):
            self.store.create("Replacement")
        self.assertFalse(self.store.path.exists())

    def test_explicit_repair_restores_missing_primary_then_allows_rename(self) -> None:
        original = self.store.create("Alice")
        self.store.rename(original, "Alice Two")
        backup_before = self.store.backup_path.read_bytes()
        self.store.path.unlink()

        repaired = self.store.repair_from_backup()
        self.assertEqual(repaired, original)
        self.assertEqual(self.store.path.read_bytes(), backup_before)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_before)

        renamed = self.store.rename(repaired, "Alice Recovered")
        self.assertEqual(renamed.profile_id, original.profile_id)
        self.assertEqual(renamed.display_name, "Alice Recovered")
        self.assertEqual(renamed.revision, original.revision + 1)

    def test_explicit_repair_replaces_corrupt_primary_only_from_verified_backup(self) -> None:
        original = self.store.create("Alice")
        self.store.rename(original, "Alice Two")
        backup_before = self.store.backup_path.read_bytes()
        self.store.path.write_bytes(b"corrupt-primary")

        repaired = self.store.repair_from_backup()
        self.assertEqual(repaired, original)
        self.assertEqual(self.store.path.read_bytes(), backup_before)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_before)

    def test_both_unreadable_refuse_fresh_identity_and_preserve_bytes(self) -> None:
        original = self.store.create("Alice")
        self.store.rename(original, "Alice Two")
        self.store.path.write_bytes(b"bad-primary")
        self.store.backup_path.write_bytes(b"bad-backup")
        primary_before = self.store.path.read_bytes()
        backup_before = self.store.backup_path.read_bytes()
        with self.assertRaises(LocalProfileError):
            self.store.load()
        with self.assertRaises(LocalProfileError):
            self.store.create("Replacement")
        with self.assertRaises(LocalProfileError):
            self.store.repair_from_backup()
        self.assertEqual(self.store.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_before)

    def test_future_primary_never_downgrades_to_older_backup(self) -> None:
        original = self.store.create("Alice")
        self.store.rename(original, "Alice Two")
        future = json.loads(self.store.path.read_text(encoding="utf-8"))
        future["schema_version"] = 2
        future_bytes = (json.dumps(future, separators=(",", ":")) + "\n").encode("utf-8")
        self.store.path.write_bytes(future_bytes)
        backup_before = self.store.backup_path.read_bytes()
        with self.assertRaises(UnsupportedLocalProfileSchema):
            self.store.load()
        with self.assertRaises(UnsupportedLocalProfileSchema):
            self.store.create("Replacement")
        with self.assertRaises(UnsupportedLocalProfileSchema):
            self.store.repair_from_backup()
        self.assertEqual(self.store.path.read_bytes(), future_bytes)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_before)

    def test_unreadable_primary_is_not_overwritten_even_with_good_backup(self) -> None:
        original = self.store.create("Alice")
        current = self.store.rename(original, "Alice Two")
        self.store.path.write_bytes(b"corrupt")
        primary_before = self.store.path.read_bytes()
        backup_before = self.store.backup_path.read_bytes()
        with self.assertRaises(LocalProfileError):
            self.store.rename(current, "Alice Three")
        self.assertEqual(self.store.path.read_bytes(), primary_before)
        self.assertEqual(self.store.backup_path.read_bytes(), backup_before)

    def test_primary_replace_failure_keeps_previous_identity_and_verified_backup(self) -> None:
        original = self.store.create("Alice")
        real_replace = os.replace

        def fail_primary_replace(source: str, target: str | os.PathLike[str]) -> None:
            if Path(target) == self.store.path:
                raise OSError("injected write failure")
            real_replace(source, target)

        with mock.patch("acs.local_profile.os.replace", side_effect=fail_primary_replace):
            with self.assertRaisesRegex(LocalProfileError, "could not be saved"):
                self.store.rename(original, "Alice Two")
        self.assertEqual(self.store.load(), original)
        self.assertEqual(parse_local_profile_bytes(self.store.backup_path.read_bytes()), original)

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_existing_symlink_profile_is_rejected(self) -> None:
        target = self.root / "target.json"
        target.write_bytes(serialize_local_profile(new_local_profile("Target")))
        link = self.root / "link.json"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are not permitted in this environment")
        linked_store = LocalProfileStore(link)
        with self.assertRaisesRegex(LocalProfileError, "symbolic link"):
            linked_store.load()


if __name__ == "__main__":
    unittest.main()
