from __future__ import annotations

import unittest

from acs.sound_events import MoveSoundFacts, SoundEvent
from acs.sound_profiles import (
    CORE_SOUND_EVENTS,
    KNOWN_SOUND_EVENTS,
    SOUND_PACK_MANIFEST_SCHEMA_VERSION,
    SOUND_PROFILE_SCHEMA_VERSION,
    SoundEventPreference,
    SoundPackManifest,
    SoundProfile,
)
from acs.sound_runtime import GameSoundRuntime, ProfiledSoundRuntime


class SoundProfileContractTests(unittest.TestCase):
    def test_core_event_ids_are_derived_from_canonical_sound_event_enum(self) -> None:
        self.assertEqual(CORE_SOUND_EVENTS, tuple(event.value for event in SoundEvent))
        self.assertEqual(len(CORE_SOUND_EVENTS), 9)

    def test_profile_round_trip_is_versioned_and_detached(self) -> None:
        source_events = {
            "capture": SoundEventPreference(True, 50, "wood.capture"),
            "check": SoundEventPreference(False, 100),
        }
        profile = SoundProfile(
            pack_id="soft.wood",
            master_enabled=True,
            master_volume_percent=80,
            events=source_events,
        )
        source_events.clear()
        self.assertEqual(profile.effective_volume("capture"), 40)
        self.assertEqual(profile.selected_sound_id("capture"), "wood.capture")
        self.assertEqual(profile.effective_volume("check"), 0)

        payload = profile.to_mapping()
        self.assertEqual(payload["schema_version"], SOUND_PROFILE_SCHEMA_VERSION)
        self.assertEqual(SoundProfile.from_mapping(payload), profile)
        with self.assertRaises(TypeError):
            profile.events["move"] = SoundEventPreference()  # type: ignore[index]

    def test_profile_rejects_scalar_coercion_unknown_events_and_unknown_fields(self) -> None:
        with self.assertRaises(TypeError):
            SoundProfile(master_volume_percent=True)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            SoundProfile(events={"future.event": SoundEventPreference()})
        with self.assertRaises(ValueError):
            SoundProfile.from_mapping(
                {
                    "schema_version": SOUND_PROFILE_SCHEMA_VERSION,
                    "pack_id": "classic",
                    "unknown": True,
                }
            )

    def test_legacy_settings_migration_is_explicit_and_strict(self) -> None:
        profile = SoundProfile.from_legacy_settings(
            {"sounds": False, "volume": 37, "other_setting": "preserved elsewhere"}
        )
        self.assertFalse(profile.master_enabled)
        self.assertEqual(profile.master_volume_percent, 37)
        with self.assertRaises(TypeError):
            SoundProfile.from_legacy_settings({"sounds": 1, "volume": 37})
        with self.assertRaises(TypeError):
            SoundProfile.from_legacy_settings({"sounds": True, "volume": "37"})

    def test_known_namespace_contains_required_classroom_events(self) -> None:
        for event_id in (
            "classroom.join",
            "classroom.leave",
            "classroom.hand_raise",
            "classroom.permission",
            "lesson.position_deployed",
            "classroom.chat",
            "classroom.file_transfer_complete",
        ):
            self.assertIn(event_id, KNOWN_SOUND_EVENTS)


class SoundPackManifestContractTests(unittest.TestCase):
    @staticmethod
    def make_pack(**overrides: object) -> SoundPackManifest:
        data: dict[str, object] = {
            "pack_id": "soft.wood",
            "version": "1.0.0",
            "title": "Soft Wood",
            "license_id": "CC0-1.0",
            "files": {
                event: f"audio/{event}.wav"
                for event in CORE_SOUND_EVENTS
            },
            "author": "Accessible Chess",
            "provenance": "project-authored fixture",
        }
        data.update(overrides)
        return SoundPackManifest(**data)  # type: ignore[arg-type]

    def test_pack_round_trip_requires_all_core_events_and_provenance(self) -> None:
        pack = self.make_pack()
        payload = pack.to_mapping()
        self.assertEqual(
            payload["schema_version"],
            SOUND_PACK_MANIFEST_SCHEMA_VERSION,
        )
        self.assertEqual(SoundPackManifest.from_mapping(payload), pack)
        self.assertEqual(pack.sound_path("move"), "audio/move.wav")
        with self.assertRaises(TypeError):
            pack.files["move"] = "other.wav"  # type: ignore[index]

    def test_pack_rejects_missing_core_event_path_escape_and_non_wav(self) -> None:
        with self.assertRaises(ValueError):
            self.make_pack(files={"move": "move.wav"})

        escaped = {event: f"{event}.wav" for event in CORE_SOUND_EVENTS}
        escaped["move"] = "../move.wav"
        with self.assertRaises(ValueError):
            self.make_pack(files=escaped)

        wrong_type = {event: f"{event}.wav" for event in CORE_SOUND_EVENTS}
        wrong_type["move"] = "move.mp3"
        with self.assertRaises(ValueError):
            self.make_pack(files=wrong_type)

    def test_pack_supports_alternate_sound_ids_but_rejects_invalid_ids(self) -> None:
        sounds = {event: f"{event}.wav" for event in CORE_SOUND_EVENTS}
        sounds["wood.capture"] = "alternate/wood-capture.wav"
        pack = self.make_pack(files=sounds)
        self.assertEqual(
            pack.sound_path("wood.capture"),
            "alternate/wood-capture.wav",
        )

        invalid = dict(sounds)
        invalid["bad/id"] = "alternate/bad.wav"
        with self.assertRaises(ValueError):
            self.make_pack(files=invalid)

    def test_pack_requires_legal_metadata(self) -> None:
        for field in ("license_id", "author", "provenance"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.make_pack(**{field: ""})


class FakeAssetPlayback:
    def __init__(self, *, fail_sound_id: str | None = None) -> None:
        self.requests = []
        self.fail_sound_id = fail_sound_id

    def play_sound(self, request) -> None:
        self.requests.append(request)
        if request.sound_id == self.fail_sound_id:
            raise RuntimeError("private playback detail")


class ProfiledSoundRuntimeTests(unittest.TestCase):
    def test_profile_filters_and_remaps_without_reordering_chess_events(self) -> None:
        playback = FakeAssetPlayback()
        profile = SoundProfile(
            pack_id="soft.wood",
            master_volume_percent=80,
            events={
                "capture": SoundEventPreference(True, 50, "wood.capture"),
                "check": SoundEventPreference(False, 100),
            },
        )
        runtime = ProfiledSoundRuntime(playback, profile)
        game = GameSoundRuntime(runtime)

        report = game.move(MoveSoundFacts(capture=True, check=True))
        self.assertEqual(
            report.requested,
            (SoundEvent.CAPTURE, SoundEvent.CHECK),
        )
        self.assertEqual(report.delivered, (SoundEvent.CAPTURE,))
        self.assertEqual(len(playback.requests), 1)
        self.assertEqual(playback.requests[0].event_id, "capture")
        self.assertEqual(playback.requests[0].sound_id, "wood.capture")
        self.assertEqual(playback.requests[0].volume, 40)
        self.assertFalse(playback.requests[0].preview)

    def test_dynamic_profile_provider_is_read_at_each_dispatch(self) -> None:
        playback = FakeAssetPlayback()
        holder = {"profile": SoundProfile(master_volume_percent=80)}
        runtime = ProfiledSoundRuntime(playback, lambda: holder["profile"])
        runtime.dispatch([SoundEvent.MOVE])

        holder["profile"] = SoundProfile(
            master_volume_percent=60,
            events={"move": SoundEventPreference(True, 25, "quiet.move")},
        )
        runtime.dispatch([SoundEvent.MOVE])
        self.assertEqual(
            [(request.sound_id, request.volume) for request in playback.requests],
            [("move", 80), ("quiet.move", 15)],
        )

    def test_preview_is_separate_and_disabled_event_never_touches_adapter(self) -> None:
        playback = FakeAssetPlayback()
        runtime = ProfiledSoundRuntime(
            playback,
            SoundProfile(
                master_volume_percent=80,
                events={
                    "check": SoundEventPreference(True, 50, "soft.check"),
                    "move": SoundEventPreference(False, 100),
                },
            ),
        )
        preview = runtime.preview("check")
        self.assertTrue(preview.ok)
        self.assertTrue(preview.delivered)
        self.assertIsNotNone(preview.request)
        self.assertTrue(preview.request.preview)
        self.assertEqual(preview.request.volume, 40)

        disabled = runtime.preview("move")
        self.assertTrue(disabled.ok)
        self.assertFalse(disabled.delivered)
        self.assertIsNone(disabled.request)
        self.assertEqual(len(playback.requests), 1)

    def test_playback_failure_is_isolated_and_later_event_continues(self) -> None:
        playback = FakeAssetPlayback(fail_sound_id="wood.capture")
        runtime = ProfiledSoundRuntime(
            playback,
            SoundProfile(
                events={
                    "capture": SoundEventPreference(True, 100, "wood.capture"),
                    "check": SoundEventPreference(True, 100, "wood.check"),
                }
            ),
        )
        report = runtime.dispatch([SoundEvent.CAPTURE, SoundEvent.CHECK])
        self.assertEqual(report.delivered, (SoundEvent.CHECK,))
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(report.failures[0].event, SoundEvent.CAPTURE)
        self.assertEqual(
            [request.sound_id for request in playback.requests],
            ["wood.capture", "wood.check"],
        )

    def test_preview_failure_exposes_only_machine_error_type_not_exception_text(self) -> None:
        playback = FakeAssetPlayback(fail_sound_id="wood.move")
        runtime = ProfiledSoundRuntime(
            playback,
            SoundProfile(
                events={"move": SoundEventPreference(True, 100, "wood.move")}
            ),
        )
        result = runtime.preview("move")
        self.assertFalse(result.ok)
        self.assertFalse(result.delivered)
        self.assertEqual(result.error_type, "RuntimeError")
        self.assertFalse(hasattr(result, "message"))


if __name__ == "__main__":
    unittest.main()
