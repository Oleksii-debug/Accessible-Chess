from __future__ import annotations

import unittest

from acs.sound_profile_store import (
    SoundProfileManager,
    SoundProfileRecoveryReason,
)
from acs.sound_profiles import SoundEventPreference, SoundProfile


class MemoryProfileStore:
    def __init__(self, payload=None):
        self.payload = payload
        self.writes = []

    def read_profile(self):
        return self.payload

    def write_profile_atomically(self, payload):
        self.payload = dict(payload)
        self.writes.append(dict(payload))


class FakePackResolver:
    def __init__(self, usable=("classic", "wood"), fallback="classic"):
        self.usable = set(usable)
        self.fallback = fallback
        self.requests = []

    def resolve_usable_pack(self, requested_pack_id: str) -> str:
        self.requests.append(requested_pack_id)
        return requested_pack_id if requested_pack_id in self.usable else self.fallback


class SoundProfileManagerTests(unittest.TestCase):
    def test_absent_profile_gets_canonical_default_persisted_atomically(self) -> None:
        store = MemoryProfileStore()
        manager = SoundProfileManager(store, FakePackResolver())

        result = manager.load()

        self.assertEqual(result.profile, SoundProfile())
        self.assertEqual(result.recovery_reasons, (SoundProfileRecoveryReason.ABSENT,))
        self.assertTrue(result.persisted_canonical)
        self.assertEqual(len(store.writes), 1)
        self.assertEqual(store.writes[0], SoundProfile().to_mapping())

    def test_legacy_flat_settings_migrate_and_are_written_once_as_current_schema(self) -> None:
        store = MemoryProfileStore({"sounds": False, "volume": 31})
        manager = SoundProfileManager(store, FakePackResolver())

        result = manager.load()

        self.assertFalse(result.profile.master_enabled)
        self.assertEqual(result.profile.master_volume_percent, 31)
        self.assertEqual(
            result.recovery_reasons,
            (SoundProfileRecoveryReason.LEGACY_MIGRATED,),
        )
        self.assertEqual(len(store.writes), 1)
        self.assertIn("schema_version", store.payload)
        self.assertNotIn("sounds", store.payload)

    def test_malformed_profile_recovers_to_safe_default_and_reports_recovery(self) -> None:
        store = MemoryProfileStore({"schema_version": 1, "master_volume_percent": 999})
        manager = SoundProfileManager(store, FakePackResolver())

        result = manager.load()

        self.assertEqual(result.profile, SoundProfile())
        self.assertIn(SoundProfileRecoveryReason.MALFORMED, result.recovery_reasons)
        self.assertTrue(result.persisted_canonical)
        self.assertEqual(len(store.writes), 1)

    def test_future_schema_is_not_overwritten_on_downgrade(self) -> None:
        raw = {"schema_version": 999, "pack_id": "future.pack", "opaque": {"x": 1}}
        store = MemoryProfileStore(raw)
        manager = SoundProfileManager(store, FakePackResolver())

        result = manager.load()

        self.assertEqual(result.profile, SoundProfile())
        self.assertEqual(
            result.recovery_reasons,
            (SoundProfileRecoveryReason.FUTURE_SCHEMA,),
        )
        self.assertFalse(result.persisted_canonical)
        self.assertEqual(store.writes, [])
        self.assertEqual(store.payload, raw)

    def test_missing_pack_falls_back_without_losing_master_or_event_preferences(self) -> None:
        profile = SoundProfile(
            pack_id="missing",
            master_enabled=False,
            master_volume_percent=47,
            events={"capture": SoundEventPreference(False, 23, "quiet.capture")},
        )
        store = MemoryProfileStore(profile.to_mapping())
        manager = SoundProfileManager(store, FakePackResolver())

        result = manager.load()

        self.assertEqual(result.profile.pack_id, "classic")
        self.assertFalse(result.profile.master_enabled)
        self.assertEqual(result.profile.master_volume_percent, 47)
        self.assertEqual(
            result.profile.preference_for("capture"),
            SoundEventPreference(False, 23, "quiet.capture"),
        )
        self.assertEqual(
            result.recovery_reasons,
            (SoundProfileRecoveryReason.PACK_FALLBACK,),
        )
        self.assertTrue(result.persisted_canonical)

    def test_set_pack_resolves_unavailable_pack_before_persisting(self) -> None:
        store = MemoryProfileStore(SoundProfile(pack_id="wood").to_mapping())
        manager = SoundProfileManager(store, FakePackResolver())
        manager.load()
        store.writes.clear()

        updated = manager.set_pack("unavailable")

        self.assertEqual(updated.pack_id, "classic")
        self.assertEqual(store.writes[-1]["pack_id"], "classic")

    def test_event_edits_are_immutable_and_persisted_through_single_manager(self) -> None:
        store = MemoryProfileStore(SoundProfile().to_mapping())
        manager = SoundProfileManager(store, FakePackResolver())
        original = manager.load().profile

        updated = manager.set_event("move", SoundEventPreference(False, 55, "soft.move"))

        self.assertNotEqual(updated, original)
        self.assertEqual(original.preference_for("move"), SoundEventPreference())
        self.assertEqual(
            updated.preference_for("move"),
            SoundEventPreference(False, 55, "soft.move"),
        )
        self.assertEqual(manager.profile_provider(), updated)
        self.assertEqual(store.writes[-1], updated.to_mapping())

    def test_reset_event_restores_default_without_touching_other_events(self) -> None:
        profile = SoundProfile(
            events={
                "move": SoundEventPreference(False, 50, "soft.move"),
                "check": SoundEventPreference(True, 40, "soft.check"),
            }
        )
        store = MemoryProfileStore(profile.to_mapping())
        manager = SoundProfileManager(store, FakePackResolver())
        manager.load()

        updated = manager.reset_event("move")

        self.assertEqual(updated.preference_for("move"), SoundEventPreference())
        self.assertEqual(
            updated.preference_for("check"),
            SoundEventPreference(True, 40, "soft.check"),
        )

    def test_master_edits_keep_pack_and_event_preferences(self) -> None:
        profile = SoundProfile(
            pack_id="wood",
            events={"tick": SoundEventPreference(False, 20, "soft.tick")},
        )
        store = MemoryProfileStore(profile.to_mapping())
        manager = SoundProfileManager(store, FakePackResolver())
        manager.load()

        updated = manager.set_master(enabled=False, volume_percent=12)

        self.assertEqual(updated.pack_id, "wood")
        self.assertFalse(updated.master_enabled)
        self.assertEqual(updated.master_volume_percent, 12)
        self.assertEqual(
            updated.preference_for("tick"),
            SoundEventPreference(False, 20, "soft.tick"),
        )

    def test_bad_resolver_result_fails_before_persistence(self) -> None:
        store = MemoryProfileStore(SoundProfile().to_mapping())
        manager = SoundProfileManager(store, lambda _pack: "")

        with self.assertRaises(ValueError):
            manager.load()

        self.assertEqual(store.writes, [])


if __name__ == "__main__":
    unittest.main()
