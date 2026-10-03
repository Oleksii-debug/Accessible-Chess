from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.sound_profile_file_store import (
    JsonSoundProfileStorage,
    SoundProfileFileError,
)
from acs.sound_profile_store import (
    SoundProfileConflictError,
    SoundProfileManager,
    SoundProfileRecoveryReason,
    SoundProfileWriteBlockedError,
)
from acs.sound_profiles import SoundEventPreference, SoundProfile


class JsonSoundProfileStorageTests(unittest.TestCase):
    @staticmethod
    def _resolver(pack_id: str) -> str:
        return pack_id if pack_id in {"classic", "soft.wood"} else "classic"

    def test_absent_profile_round_trips_through_manager_as_canonical_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "settings" / "sound-profile.json"
            storage = JsonSoundProfileStorage(path)
            manager = SoundProfileManager(storage, self._resolver)

            result = manager.load()

            self.assertIn(SoundProfileRecoveryReason.ABSENT, result.recovery_reasons)
            self.assertTrue(result.persisted_canonical)
            self.assertEqual(result.profile, SoundProfile())
            self.assertEqual(storage.read_profile(), SoundProfile().to_mapping())

    def test_profile_path_swap_after_lstat_is_rejected_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "sound-profile.json"
            storage = JsonSoundProfileStorage(path)
            storage.write_profile_atomically(SoundProfile().to_mapping())
            replacement = path.with_name("replacement.json")
            replacement.write_bytes(path.read_bytes())
            real_open = os.open
            swapped = False

            def swap_before_open(target, flags, mode=0o777, *, dir_fd=None):
                nonlocal swapped
                if Path(target) == path and not swapped:
                    swapped = True
                    os.replace(replacement, path)
                if dir_fd is None:
                    return real_open(target, flags, mode)
                return real_open(target, flags, mode, dir_fd=dir_fd)

            with mock.patch(
                "acs.sound_profile_file_store.os.open",
                side_effect=swap_before_open,
            ), self.assertRaisesRegex(
                SoundProfileFileError,
                "changed before secure read",
            ):
                storage.read_profile()

            self.assertTrue(swapped)

    def test_atomic_round_trip_preserves_per_event_profile(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "sound-profile.json"
            storage = JsonSoundProfileStorage(path)
            profile = SoundProfile(
                pack_id="soft.wood",
                master_enabled=True,
                master_volume_percent=67,
                events={
                    "capture": SoundEventPreference(
                        enabled=True,
                        volume_percent=45,
                        sound_id="wood.capture",
                    ),
                    "classroom.join": SoundEventPreference(
                        enabled=False,
                        volume_percent=20,
                    ),
                },
            )

            storage.write_profile_atomically(profile.to_mapping())

            self.assertEqual(storage.read_profile(), profile.to_mapping())
            self.assertFalse(path.with_suffix(path.suffix + ".tmp").exists())

    def test_atomic_publish_flushes_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "settings" / "sound-profile.json"
            storage = JsonSoundProfileStorage(path)

            with mock.patch(
                "acs.sound_profile_file_store._fsync_directory"
            ) as sync_directory:
                storage.write_profile_atomically(SoundProfile().to_mapping())

            sync_directory.assert_called_once_with(path.parent)
            self.assertEqual(storage.read_profile(), SoundProfile().to_mapping())

    def test_post_replace_directory_sync_failure_is_refreshable_uncertain_commit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "sound-profile.json"
            storage = JsonSoundProfileStorage(path)
            manager = SoundProfileManager(storage, self._resolver)

            with mock.patch(
                "acs.sound_profile_file_store._fsync_directory",
                side_effect=SoundProfileFileError("directory sync failed"),
            ), self.assertRaisesRegex(SoundProfileFileError, "directory sync failed"):
                manager.load()

            self.assertTrue(path.is_file())
            self.assertEqual(SoundProfile(), manager.current)
            self.assertEqual(storage.read_profile(), SoundProfile().to_mapping())

    def test_two_process_owners_fail_closed_instead_of_lost_update(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "sound-profile.json"
            first_storage = JsonSoundProfileStorage(path)
            first = SoundProfileManager(first_storage, self._resolver)
            first.load()

            second_storage = JsonSoundProfileStorage(path)
            second = SoundProfileManager(second_storage, self._resolver)
            second.load()

            first.set_master(volume_percent=31)

            with self.assertRaisesRegex(
                SoundProfileConflictError,
                "changed in another process",
            ):
                second.set_event(
                    "move",
                    SoundEventPreference(enabled=False, volume_percent=44),
                )

            self.assertEqual(31, second.current.master_volume_percent)
            self.assertEqual(SoundEventPreference(), second.current.preference_for("move"))
            self.assertEqual(second.current.to_mapping(), second_storage.read_profile())

            retried = second.set_event(
                "move",
                SoundEventPreference(enabled=False, volume_percent=44),
            )
            self.assertEqual(31, retried.master_volume_percent)
            self.assertEqual(
                SoundEventPreference(enabled=False, volume_percent=44),
                retried.preference_for("move"),
            )

    def test_same_canonical_recovery_write_is_idempotent_across_owners(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "sound-profile.json"
            path.write_bytes(b"{bad-json")
            first = SoundProfileManager(JsonSoundProfileStorage(path), self._resolver)
            second = SoundProfileManager(JsonSoundProfileStorage(path), self._resolver)

            first_result = first.load()
            second_result = second.load()

            self.assertEqual(SoundProfile(), first_result.profile)
            self.assertEqual(SoundProfile(), second_result.profile)
            self.assertEqual(SoundProfile().to_mapping(), JsonSoundProfileStorage(path).read_profile())

    def test_duplicate_or_malformed_json_recovers_via_manager(self) -> None:
        for raw_payload in (
            b'{"schema_version":1,"schema_version":1}\n',
            b'{"schema_version":',
            b'[]\n',
            b'',
        ):
            with self.subTest(raw_payload=raw_payload):
                with tempfile.TemporaryDirectory() as raw:
                    path = Path(raw) / "sound-profile.json"
                    path.write_bytes(raw_payload)
                    storage = JsonSoundProfileStorage(path)
                    manager = SoundProfileManager(storage, self._resolver)

                    result = manager.load()

                    self.assertIn(
                        SoundProfileRecoveryReason.MALFORMED,
                        result.recovery_reasons,
                    )
                    self.assertTrue(result.persisted_canonical)
                    self.assertEqual(storage.read_profile(), SoundProfile().to_mapping())

    def test_future_schema_is_returned_unchanged_and_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "sound-profile.json"
            future = {
                "schema_version": 99,
                "pack_id": "future.pack",
                "future_data": {"keep": True},
            }
            encoded = (
                json.dumps(future, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            path.write_bytes(encoded)
            storage = JsonSoundProfileStorage(path)
            manager = SoundProfileManager(storage, self._resolver)

            result = manager.load()

            self.assertTrue(result.writes_blocked)
            self.assertIn(
                SoundProfileRecoveryReason.FUTURE_SCHEMA,
                result.recovery_reasons,
            )
            self.assertEqual(path.read_bytes(), encoded)
            with self.assertRaises(SoundProfileWriteBlockedError):
                manager.set_master(volume_percent=10)
            self.assertEqual(path.read_bytes(), encoded)

    def test_explicit_future_replacement_unlocks_atomic_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "sound-profile.json"
            path.write_text(
                '{"schema_version":2,"future":true}\n',
                encoding="utf-8",
            )
            storage = JsonSoundProfileStorage(path)
            manager = SoundProfileManager(storage, self._resolver)
            manager.load()

            replacement = SoundProfile(
                master_volume_percent=55,
                events={"move": SoundEventPreference(volume_percent=40)},
            )
            saved = manager.replace_future_profile(replacement)

            self.assertEqual(saved, replacement)
            self.assertFalse(manager.writes_blocked)
            self.assertEqual(storage.read_profile(), replacement.to_mapping())

    def test_noncanonical_and_legacy_writes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            storage = JsonSoundProfileStorage(Path(raw) / "sound-profile.json")
            with self.assertRaisesRegex(
                SoundProfileFileError,
                "current sound profile|canonical",
            ):
                storage.write_profile_atomically({"sounds": True, "volume": 80})

            canonical = SoundProfile().to_mapping()
            with_extra = dict(canonical)
            with_extra["unexpected"] = True
            with self.assertRaisesRegex(SoundProfileFileError, "canonical"):
                storage.write_profile_atomically(with_extra)

    def test_oversized_or_nonfinite_profile_is_projected_as_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "sound-profile.json"
            storage = JsonSoundProfileStorage(path, max_bytes=64)
            path.write_bytes(b"{" + b"x" * 100 + b"}")
            payload = storage.read_profile()
            self.assertIsInstance(payload, dict)
            self.assertIsInstance(payload.get("schema_version"), str)

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "sound-profile.json"
            path.write_text(
                '{"schema_version":1,"pack_id":"classic",'
                '"master_enabled":true,"master_volume_percent":NaN,"events":{}}\n',
                encoding="utf-8",
            )
            payload = JsonSoundProfileStorage(path).read_profile()
            self.assertIsInstance(payload.get("schema_version"), str)

    @unittest.skipIf(os.name == "nt", "ordinary Windows test runners cannot create symlinks")
    def test_symlinked_profile_directory_ancestor_is_rejected_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            outside = root / "outside"
            outside.mkdir()
            redirected = root / "redirected"
            redirected.symlink_to(outside, target_is_directory=True)
            path = redirected / "nested" / "sound-profile.json"
            outside_nested = outside / "nested"
            outside_nested.mkdir()
            outside_profile = outside_nested / "sound-profile.json"
            outside_profile.write_text(
                json.dumps(SoundProfile().to_mapping()) + "\n",
                encoding="utf-8",
            )
            storage = JsonSoundProfileStorage(path)

            with self.assertRaisesRegex(
                SoundProfileFileError,
                "redirected or invalid",
            ):
                storage.read_profile()
            with self.assertRaisesRegex(
                SoundProfileFileError,
                "redirected or invalid",
            ):
                storage.write_profile_atomically(SoundProfile().to_mapping())

            self.assertEqual(
                SoundProfile().to_mapping(),
                json.loads(outside_profile.read_text(encoding="utf-8")),
            )
            self.assertFalse((outside_nested / "sound-profile.json.lock").exists())

    @unittest.skipIf(os.name == "nt", "ordinary Windows test runners cannot create symlinks")
    def test_symlink_profile_target_is_rejected_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "outside.json"
            target.write_text("{}\n", encoding="utf-8")
            link = root / "sound-profile.json"
            link.symlink_to(target)
            storage = JsonSoundProfileStorage(link)

            with self.assertRaisesRegex(
                SoundProfileFileError,
                "not a regular file",
            ):
                storage.read_profile()
            with self.assertRaisesRegex(
                SoundProfileFileError,
                "not a regular file",
            ):
                storage.write_profile_atomically(SoundProfile().to_mapping())
            self.assertEqual(target.read_text(encoding="utf-8"), "{}\n")


if __name__ == "__main__":
    unittest.main()
