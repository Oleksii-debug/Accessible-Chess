from __future__ import annotations

import unittest

from acs.sound_profiles import CORE_SOUND_EVENTS, SoundEventPreference, SoundPackManifest, SoundProfile


class SoundProfileTests(unittest.TestCase):
    def test_per_event_enable_and_volume_are_independent(self) -> None:
        profile = SoundProfile(
            master_volume_percent=80,
            events={
                "capture": SoundEventPreference(True, 50),
                "check": SoundEventPreference(False, 100),
            },
        )
        self.assertEqual(profile.effective_volume("capture"), 40)
        self.assertEqual(profile.effective_volume("check"), 0)
        self.assertEqual(profile.effective_volume("move"), 80)

    def test_master_disable_silences_every_event(self) -> None:
        profile = SoundProfile(master_enabled=False)
        self.assertEqual(profile.effective_volume("move"), 0)
        self.assertEqual(profile.effective_volume("classroom.join"), 0)

    def test_invalid_event_volume_fails(self) -> None:
        with self.assertRaises(ValueError):
            SoundEventPreference(volume_percent=101)


class SoundPackManifestTests(unittest.TestCase):
    def test_complete_core_pack_is_valid(self) -> None:
        pack = SoundPackManifest(
            "soft.wood",
            "1.0.0",
            "Soft Wood",
            "CC0-1.0",
            {event: f"audio/{event}.wav" for event in CORE_SOUND_EVENTS},
        )
        self.assertEqual(tuple(pack.files), CORE_SOUND_EVENTS)

    def test_missing_core_sound_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            SoundPackManifest(
                "broken",
                "1",
                "Broken",
                "MIT",
                {"move": "move.wav"},
            )

    def test_audio_path_cannot_escape_pack_root(self) -> None:
        files = {event: f"{event}.wav" for event in CORE_SOUND_EVENTS}
        files["move"] = "../move.wav"
        with self.assertRaises(ValueError):
            SoundPackManifest("broken", "1", "Broken", "MIT", files)


if __name__ == "__main__":
    unittest.main()
