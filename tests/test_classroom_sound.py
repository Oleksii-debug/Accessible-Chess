from __future__ import annotations

import unittest

from acs.classroom_sound import ClassroomSoundRuntime
from acs.sound_profiles import SoundEventPreference, SoundProfile
from acs.sound_runtime import SoundAssetRequest


class FakeAssetPlayback:
    def __init__(self, fail_sound_id: str | None = None) -> None:
        self.requests: list[SoundAssetRequest] = []
        self.fail_sound_id = fail_sound_id

    def play_sound(self, request: SoundAssetRequest) -> None:
        self.requests.append(request)
        if request.sound_id == self.fail_sound_id:
            raise FileNotFoundError(request.sound_id)


class ClassroomSoundRuntimeTests(unittest.TestCase):
    def test_dispatch_uses_namespaced_profile_selection_and_volume(self) -> None:
        assets = FakeAssetPlayback()
        profile = SoundProfile(
            pack_id="class.pack",
            master_volume_percent=80,
            events={
                "classroom.join": SoundEventPreference(True, 50, "room.join.soft"),
            },
        )
        result = ClassroomSoundRuntime(assets, profile).dispatch("classroom.join")
        self.assertTrue(result.ok)
        self.assertTrue(result.delivered)
        self.assertEqual(
            assets.requests,
            [
                SoundAssetRequest(
                    pack_id="class.pack",
                    event_id="classroom.join",
                    sound_id="room.join.soft",
                    volume=40,
                    preview=False,
                )
            ],
        )

    def test_master_or_event_silence_never_touches_adapter(self) -> None:
        profiles = (
            SoundProfile(master_enabled=False),
            SoundProfile(events={"classroom.leave": SoundEventPreference(enabled=False)}),
            SoundProfile(master_volume_percent=0),
        )
        for profile in profiles:
            with self.subTest(profile=profile):
                assets = FakeAssetPlayback()
                result = ClassroomSoundRuntime(assets, profile).dispatch("classroom.leave")
                self.assertTrue(result.ok)
                self.assertFalse(result.delivered)
                self.assertIsNone(result.request)
                self.assertEqual(assets.requests, [])

    def test_preview_is_explicit_and_uses_same_profile_contract(self) -> None:
        assets = FakeAssetPlayback()
        profile = SoundProfile(
            master_volume_percent=70,
            events={"lesson.position_deployed": SoundEventPreference(True, 20, "lesson.soft")},
        )
        result = ClassroomSoundRuntime(assets, profile).preview("lesson.position_deployed")
        self.assertTrue(result.delivered)
        self.assertEqual(result.request.volume, 14)
        self.assertTrue(result.request.preview)
        self.assertEqual(result.request.sound_id, "lesson.soft")

    def test_chat_and_file_namespaces_are_supported_without_chess_policy(self) -> None:
        assets = FakeAssetPlayback()
        runtime = ClassroomSoundRuntime(assets, SoundProfile())
        runtime.dispatch("chat.message")
        runtime.dispatch("file.transfer_complete")
        self.assertEqual(
            [request.event_id for request in assets.requests],
            ["chat.message", "file.transfer_complete"],
        )

    def test_bare_chess_event_ids_are_rejected(self) -> None:
        runtime = ClassroomSoundRuntime(FakeAssetPlayback(), SoundProfile())
        for event_id in ("move", "capture", "check", "end", "tick"):
            with self.subTest(event_id=event_id), self.assertRaises(ValueError):
                runtime.dispatch(event_id)

    def test_arbitrary_unscoped_or_malformed_event_is_rejected(self) -> None:
        runtime = ClassroomSoundRuntime(FakeAssetPlayback(), SoundProfile())
        for event_id in ("join", "ui.click", "classroom../join", "classroom.join!"):
            with self.subTest(event_id=event_id), self.assertRaises(ValueError):
                runtime.dispatch(event_id)

    def test_adapter_failure_is_explicit_and_has_no_fallback(self) -> None:
        assets = FakeAssetPlayback(fail_sound_id="room.fail")
        profile = SoundProfile(
            events={"classroom.permission": SoundEventPreference(sound_id="room.fail")}
        )
        result = ClassroomSoundRuntime(assets, profile).dispatch("classroom.permission")
        self.assertFalse(result.ok)
        self.assertFalse(result.delivered)
        self.assertEqual(result.error_type, "FileNotFoundError")
        self.assertEqual(len(assets.requests), 1)

    def test_dynamic_profile_provider_is_resolved_once_per_dispatch(self) -> None:
        assets = FakeAssetPlayback()
        calls = {"count": 0}
        profile = SoundProfile(
            pack_id="atomic.pack",
            master_volume_percent=60,
            events={"classroom.hand_raise": SoundEventPreference(True, 50, "hand.soft")},
        )

        def provider() -> SoundProfile:
            calls["count"] += 1
            return profile

        runtime = ClassroomSoundRuntime(assets, provider)
        calls["count"] = 0
        result = runtime.dispatch("classroom.hand_raise")
        self.assertEqual(calls["count"], 1)
        self.assertTrue(result.delivered)
        self.assertEqual(result.request.volume, 30)


if __name__ == "__main__":
    unittest.main()
