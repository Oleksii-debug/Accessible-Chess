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

    def test_pack_change_clears_pack_relative_sound_ids_but_preserves_controls(self) -> None:
        profile = SoundProfile(
            pack_id="soft.wood",
            master_enabled=False,
            master_volume_percent=63,
            events={
                "move": SoundEventPreference(False, 45, "quiet.move"),
                "check": SoundEventPreference(True, 70),
            },
        )

        changed = profile.with_pack("classic")

        self.assertEqual("classic", changed.pack_id)
        self.assertFalse(changed.master_enabled)
        self.assertEqual(63, changed.master_volume_percent)
        self.assertEqual(SoundEventPreference(False, 45), changed.preference_for("move"))
        self.assertEqual(SoundEventPreference(True, 70), changed.preference_for("check"))
        self.assertEqual(profile, profile.with_pack("soft.wood"))

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

    def test_canonical_semantic_versions_accept_stable_and_prerelease(self) -> None:
        for version in ("1.0.0", "12.34.56-beta.1", "0.0.1-rc.2"):
            with self.subTest(version=version):
                self.assertEqual(version, self._pack(version=version).version)

    def test_noncanonical_semantic_versions_fail_closed(self) -> None:
        for version in ("1.0", "01.0.0", "1.00.0", "v1.0.0", "1.0.0+build", "1.0.0-"):
            with self.subTest(version=version), self.assertRaisesRegex(
                ValueError, "canonical semantic version"
            ):
                self._pack(version=version)

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

    def test_windows_drive_unc_and_unstable_paths_are_rejected(self) -> None:
        for unsafe in (
            r"C:\\temp\\move.wav",
            r"\\\\server\\share\\move.wav",
            "audio/../move.wav",
            "audio./move.wav ",
        ):
            files = {event: f"{event}.wav" for event in CORE_SOUND_EVENTS}
            files["move"] = unsafe
            with self.subTest(path=unsafe), self.assertRaises(ValueError):
                self._pack(files=files)

    def test_windows_case_colliding_asset_paths_are_rejected(self) -> None:
        files = {event: f"audio/{event}.wav" for event in CORE_SOUND_EVENTS}
        files["move"] = "Audio/shared.wav"
        files["capture"] = "audio/SHARED.WAV"
        with self.assertRaisesRegex(ValueError, "case-colliding"):
            self._pack(files=files)


class SoundProfileStrictScalarTests(unittest.TestCase):
    def test_profile_and_event_volumes_do_not_coerce_strings_floats_or_booleans(self) -> None:
        for value in ("80", 80.0, True):
            with self.subTest(event_volume=value), self.assertRaises(TypeError):
                SoundEventPreference(volume_percent=value)  # type: ignore[arg-type]
            with self.subTest(master_volume=value), self.assertRaises(TypeError):
                SoundProfile(master_volume_percent=value)  # type: ignore[arg-type]

    def test_identifiers_paths_and_manifest_metadata_require_text(self) -> None:
        with self.assertRaises(TypeError):
            SoundProfile(pack_id=123)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            SoundProfile(events={1: SoundEventPreference()})  # type: ignore[dict-item]
        with self.assertRaises(TypeError):
            SoundPackManifestTests._pack(version=1)  # type: ignore[arg-type]
        files = {event: f"{event}.wav" for event in CORE_SOUND_EVENTS}
        files["move"] = 7  # type: ignore[assignment]
        with self.assertRaises(TypeError):
            SoundPackManifestTests._pack(files=files)

    def test_boolean_schema_version_cannot_alias_integer_schema_one(self) -> None:
        with self.assertRaises(ValueError):
            SoundProfile.from_mapping(
                {
                    "schema_version": True,
                    "pack_id": "classic",
                    "master_enabled": True,
                    "master_volume_percent": 80,
                    "events": {},
                }
            )

    def test_event_keys_from_wire_mapping_are_not_string_coerced(self) -> None:
        with self.assertRaises(TypeError):
            SoundProfile.from_mapping(
                {
                    "schema_version": SOUND_PROFILE_SCHEMA_VERSION,
                    "pack_id": "classic",
                    "master_enabled": True,
                    "master_volume_percent": 80,
                    "events": {1: {"enabled": True}},
                }
            )


if __name__ == "__main__":
    unittest.main()
