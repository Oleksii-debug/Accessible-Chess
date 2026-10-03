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

    def test_event_ids_cannot_collide_after_canonicalization(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate.*event"):
            SoundProfile(
                events={
                    "move": SoundEventPreference(enabled=True),
                    " MOVE ": SoundEventPreference(enabled=False),
                }
            )

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
        for version in (
            "1.0.0",
            "12.34.56-beta.1",
            "0.0.1-rc.2",
            "1.0.0-alpha-beta.1",
        ):
            with self.subTest(version=version):
                self.assertEqual(version, self._pack(version=version).version)

    def test_noncanonical_semantic_versions_fail_closed(self) -> None:
        for version in (
            "1.0",
            "01.0.0",
            "1.00.0",
            "v1.0.0",
            "1.0.0+build",
            "1.0.0-",
            "1.0.0-01",
            "1.0.0-alpha.01",
        ):
            with self.subTest(version=version), self.assertRaisesRegex(
                ValueError, "canonical semantic version"
            ):
                self._pack(version=version)

    def test_license_author_and_provenance_are_mandatory(self) -> None:
        for field in ("license_id", "author", "provenance"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self._pack(**{field: ""})

    def test_manifest_metadata_is_bounded_and_single_line(self) -> None:
        cases = (
            ("title", "x" * 257, "resource limit"),
            ("author", "x" * 257, "resource limit"),
            ("license_id", "x" * 257, "resource limit"),
            ("provenance", "x" * 4097, "resource limit"),
            ("title", "Visible\nSpoofed", "control characters"),
            ("author", "Author\tHidden", "control characters"),
            ("provenance", "source\u2028second-line", "control characters"),
            ("title", "Normal\u202eesrever", "control characters"),
            ("author", "Visible\u200bHidden", "control characters"),
            ("license_id", "CC0\u200e-1.0", "control characters"),
        )
        for field, value, message in cases:
            with self.subTest(field=field, value=value[:20]), self.assertRaisesRegex(
                ValueError,
                message,
            ):
                self._pack(**{field: value})

    def test_manifest_bounds_identifier_version_and_sound_id_cardinality(self) -> None:
        with self.assertRaisesRegex(ValueError, "resource limit"):
            self._pack(pack_id="p" * 129)
        with self.assertRaisesRegex(ValueError, "resource limit"):
            self._pack(version="1.0.0-" + "a" * 123)

        files = {event: f"audio/{event}.wav" for event in CORE_SOUND_EVENTS}
        for index in range(2048 - len(files) + 1):
            files[f"variant.{index}"] = f"audio/variant-{index}.wav"
        self.assertGreater(len(files), 2048)
        with self.assertRaisesRegex(ValueError, "too many sound ids"):
            self._pack(files=files)

    def test_manifest_and_profile_defensively_freeze_validated_mappings(self) -> None:
        files = {event: f"audio/{event}.wav" for event in CORE_SOUND_EVENTS}
        manifest = self._pack(files=files)
        files["move"] = "../tampered.wav"

        self.assertEqual("audio/move.wav", manifest.files["move"])
        with self.assertRaises(TypeError):
            manifest.files["move"] = "audio/other.wav"  # type: ignore[index]

        events = {"move": SoundEventPreference(volume_percent=37)}
        profile = SoundProfile(events=events)
        events["move"] = SoundEventPreference(volume_percent=99)

        self.assertEqual(37, profile.preference_for("move").volume_percent)
        with self.assertRaises(TypeError):
            profile.events["move"] = SoundEventPreference()  # type: ignore[index]

    def test_missing_core_sound_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            self._pack(files={"move": "move.wav"})

    def test_audio_path_cannot_escape_pack_root(self) -> None:
        files = {event: f"{event}.wav" for event in CORE_SOUND_EVENTS}
        files["move"] = "../move.wav"
        with self.assertRaises(ValueError):
            self._pack(files=files)

    def test_audio_path_resources_are_bounded_before_filesystem_use(self) -> None:
        cases = (
            "audio/" + ("x" * 252) + ".wav",
            "/".join(["a"] * 65) + "/move.wav",
            "audio/" + ("x" * 4090) + ".wav",
        )
        for unsafe in cases:
            files = {event: f"audio/{event}.wav" for event in CORE_SOUND_EVENTS}
            files["move"] = unsafe
            with self.subTest(length=len(unsafe)), self.assertRaisesRegex(
                ValueError,
                "resource limit",
            ):
                self._pack(files=files)

    def test_executable_payload_is_rejected(self) -> None:
        files = {event: f"{event}.wav" for event in CORE_SOUND_EVENTS}
        files["move"] = "move.exe"
        with self.assertRaises(ValueError):
            self._pack(files=files)

    def test_audio_path_windows_utf16_units_are_bounded(self) -> None:
        files = {event: f"audio/{event}.wav" for event in CORE_SOUND_EVENTS}
        files["move"] = "audio/" + ("😀" * 125) + ".wav"
        pack = self._pack(files=files)
        self.assertEqual(files["move"], pack.files["move"])

        files = dict(files)
        files["move"] = "audio/" + ("😀" * 126) + ".wav"
        with self.assertRaisesRegex(ValueError, "resource limit"):
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

    def test_windows_reserved_devices_and_forbidden_filename_chars_are_rejected(self) -> None:
        for unsafe in (
            "audio/CON.wav",
            "audio/con.mp3",
            "audio/AUX.ogg",
            "audio/NUL.wav",
            "audio/COM1.wav",
            "audio/lpt9.wav",
            "audio/COM¹.wav",
            "audio/com².ogg",
            "audio/LPT³.mp3",
            "CONIN$.wav",
            "audio/bad:name.wav",
            'audio/bad"name.wav',
            "audio/bad|name.wav",
            "audio/bad?name.wav",
            "audio/bad*name.wav",
            "audio/bad\x1fname.wav",
        ):
            files = {event: f"audio/{event}.wav" for event in CORE_SOUND_EVENTS}
            files["move"] = unsafe
            with self.subTest(path=unsafe), self.assertRaisesRegex(
                ValueError, "Windows"
            ):
                self._pack(files=files)

    def test_windows_case_colliding_asset_paths_are_rejected(self) -> None:
        files = {event: f"audio/{event}.wav" for event in CORE_SOUND_EVENTS}
        files["move"] = "Audio/shared.wav"
        files["capture"] = "audio/SHARED.WAV"
        with self.assertRaisesRegex(ValueError, "case-colliding"):
            self._pack(files=files)


class SoundProfileMappingShapeTests(unittest.TestCase):
    def test_current_schema_rejects_unknown_or_missing_fields(self) -> None:
        canonical = SoundProfile().to_mapping()
        unknown = dict(canonical)
        unknown["future_without_version_bump"] = True
        missing = dict(canonical)
        missing.pop("events")
        for payload in (unknown, missing):
            with self.subTest(payload=payload), self.assertRaisesRegex(
                ValueError, "fields"
            ):
                SoundProfile.from_mapping(payload)

    def test_event_mapping_rejects_unknown_or_missing_fields(self) -> None:
        canonical = SoundEventPreference().to_mapping()
        unknown = dict(canonical)
        unknown["unexpected"] = 1
        missing = dict(canonical)
        missing.pop("sound_id")
        for payload in (unknown, missing):
            with self.subTest(payload=payload), self.assertRaisesRegex(
                ValueError, "fields"
            ):
                SoundEventPreference.from_mapping(payload)

    def test_legacy_mapping_requires_only_known_legacy_fields(self) -> None:
        self.assertEqual(
            SoundProfile(master_enabled=False, master_volume_percent=37),
            SoundProfile.from_mapping({"sounds": False, "volume": 37}),
        )
        for payload in ({}, {"other": True}, {"sounds": True, "other": 1}):
            with self.subTest(payload=payload), self.assertRaisesRegex(
                ValueError, "legacy.*fields"
            ):
                SoundProfile.from_mapping(payload)


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
