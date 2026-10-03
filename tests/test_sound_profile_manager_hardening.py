from __future__ import annotations

import unittest

from acs.sound_profile_store import (
    SoundProfileManager,
    SoundProfileRecoveryReason,
)
from acs.sound_profiles import SoundEventPreference, SoundProfile


class _Storage:
    def __init__(self, raw=None) -> None:
        self.raw = raw
        self.writes: list[dict[str, object]] = []

    def read_profile(self):
        return self.raw

    def write_profile_atomically(self, payload):
        self.writes.append(dict(payload))
        self.raw = dict(payload)


class SoundProfileManagerHardeningTests(unittest.TestCase):
    def test_constructor_rejects_missing_storage_or_resolver_ports(self) -> None:
        with self.assertRaises(TypeError):
            SoundProfileManager(object(), lambda value: value)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            SoundProfileManager(_Storage(), object())  # type: ignore[arg-type]

    def test_resolver_result_is_not_string_coerced(self) -> None:
        for bad in (None, 7, True):
            storage = _Storage(SoundProfile().to_mapping())
            manager = SoundProfileManager(
                storage,
                lambda value, result=bad: result,  # type: ignore[return-value]
            )
            with self.subTest(result=bad), self.assertRaises(TypeError):
                manager.load()
            self.assertEqual(storage.writes, [])

    def test_reset_event_uses_same_canonical_event_identity_as_profile(self) -> None:
        profile = SoundProfile(
            events={
                "capture": SoundEventPreference(volume_percent=45),
            }
        )
        storage = _Storage(profile.to_mapping())
        manager = SoundProfileManager(storage, lambda value: value)
        manager.load()

        updated = manager.reset_event("CAPTURE")

        self.assertNotIn("capture", updated.events)
        self.assertEqual(storage.writes[-1], updated.to_mapping())

    def test_boolean_schema_version_is_malformed_not_future_schema(self) -> None:
        storage = _Storage(
            {
                "schema_version": True,
                "pack_id": "classic",
                "master_enabled": True,
                "master_volume_percent": 80,
                "events": {},
            }
        )
        manager = SoundProfileManager(storage, lambda value: value)

        result = manager.load()

        self.assertIn(
            SoundProfileRecoveryReason.MALFORMED,
            result.recovery_reasons,
        )
        self.assertNotIn(
            SoundProfileRecoveryReason.FUTURE_SCHEMA,
            result.recovery_reasons,
        )
        self.assertFalse(result.writes_blocked)
        self.assertEqual(storage.writes[-1], SoundProfile().to_mapping())


if __name__ == "__main__":
    unittest.main()
