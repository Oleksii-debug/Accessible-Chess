from __future__ import annotations

import unittest

from acs.sound_profiles import (
    CORE_SOUND_EVENTS,
    SOUND_PROFILE_SCHEMA_VERSION,
    SoundEventPreference,
    SoundPackManifest,
    SoundProfile,
)


class SoundProfileTests(unittest.TestCase):
    def test_per_event_enable_volume_and_sound_selection_are_independent(self) -> None:
        profile = SoundProfile(
            master_volume_percent=80,
            events={
                "capture": SoundEventPreference(True, 50, "wood.capture"),
                "check": SoundEventPreference(False, 100),
            },
        )
        self.assertEqual(profile.effective_volume("capture"), 40)
        self.assertEqual(profile.selected_sound_id("capture"), "wood.capture")
        self.assertEqual(profile.effective_volume("check"), 0)
        self.assertEqual(profile.selected_sound_id("move"), "move")

    def test_master_disable_silences_every_event(self) -> None:
        profile = SoundProfile(master_enabled=False)
        self.assertEqual(profile.effective_volume("move"), 0)
        self.assertEqual(profile.effective_volume("classroom.join"), 0)

    def test_invalid_event_volume_fails(self) -> None:
        with self.assertRaises(ValueError):
            SoundEventPreference(volume_percent=101)

    def test_profile_round_trip_is_versioned(self) -> None:
        profile = SoundProfile(
            pack_id="soft.wood",
            master_enabled=True,
            master_volume_percent=63,
            events={
                "move": SoundEventPreference(True, 70, "quiet.move"),
                "classroom.join": SoundEventPreference(False, 25, "room.join"),
            },
        )
        payload = profile.to_mapping()
        self.assertEqual(payload["schema_version"], SOUND_PROFILE_SCHEMA_VERSION)
        self.assertEqual(SoundProfile.from_mapping(payload), profile)

    def test_legacy_flat_settings_migrate_once_into_profile(self) -> None:
        profile = SoundProfile.from_mapping({"sounds": False, "volume": 37})
        self.assertEqual(profile.pack_id, "classic")
        self.assertFalse(profile.master_enabled)
        self.assertEqual(profile.master_volume_percent, 37)

    def test_unknown_future_profile_schema_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            SoundProfile.from_mapping({"schema_version": 999})


class SoundPackManifestTests(unittest.TestCase):
    @staticmethod
    def _pack(**overrides):
        data = {
            "pack_id": "soft.wood",
            "version": "1.0.0",
            "title": "Soft Wood",
            "license_id": "CC0-1.0",
            "files": {event: f"audio/{event}.wav" for event in CORE_SOUND_EVENTS},
            "author": "Accessible Chess",
            "provenance": "https://example.invalid/soft-wood",
        }
        data.update(overrides)
        return SoundPackManifest(**data)

    def test_complete_core_pack_is_valid_and_resolves_sound_id(self) -> None:
        pack = self._pack()
        self.assertEqual(tuple(pack.files), CORE_SOUND_EVENTS)
        self.assertEqual(pack.sound_path("move"), "audio/move.wav")

    def test_license_author_and_provenance_are_mandatory(self) -> None:
        for field in ("license_id", "author", "provenance"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self._pack(**{field: ""})

    def test_missing_core_sound_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            self._pack(files={"move": "move.wav"})

    def test_audio_path_cannot_escape_pack_root(self) -> None:
        files = {event: f"{event}.wav" for event in CORE_SOUND_EVENTS}
        files["move"] = "../move.wav"
        with self.assertRaises(ValueError):
            self._pack(files=files)

    def test_executable_payload_is_rejected(self) -> None:
        files = {event: f"{event}.wav" for event in CORE_SOUND_EVENTS}
        files["move"] = "move.exe"
        with self.assertRaises(ValueError):
            self._pack(files=files)


if __name__ == "__main__":
    unittest.main()
