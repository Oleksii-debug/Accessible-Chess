from __future__ import annotations

import unittest

from acs.sound_events import MoveSoundFacts, SoundEvent
from acs.sound_profiles import SoundEventPreference, SoundProfile
from acs.sound_runtime import GameSoundRuntime, ProfiledSoundRuntime, SoundAssetRequest


class FakeAssetPlayback:
    def __init__(self, fail_sound_id: str | None = None) -> None:
        self.requests: list[SoundAssetRequest] = []
        self.fail_sound_id = fail_sound_id

    def play_sound(self, request: SoundAssetRequest) -> None:
        self.requests.append(request)
        if request.sound_id == self.fail_sound_id:
            raise FileNotFoundError(request.sound_id)


class ProfiledSoundRuntimeTests(unittest.TestCase):
    def test_filters_selects_and_scales_without_reordering_chess_events(self) -> None:
        assets = FakeAssetPlayback()
        profile = SoundProfile(
            pack_id="wood.1",
            master_volume_percent=80,
            events={
                "capture": SoundEventPreference(True, 50, "deep.capture"),
                "check": SoundEventPreference(False, 100, "bright.check"),
                "end": SoundEventPreference(True, 25, "soft.end"),
            },
        )
        runtime = ProfiledSoundRuntime(assets, profile)
        report = runtime.dispatch([SoundEvent.CAPTURE, SoundEvent.CHECK, SoundEvent.END])
        self.assertEqual(
            [(r.event_id, r.sound_id, r.volume) for r in assets.requests],
            [("capture", "deep.capture", 40), ("end", "soft.end", 20)],
        )
        self.assertEqual(report.requested, (SoundEvent.CAPTURE, SoundEvent.CHECK, SoundEvent.END))
        self.assertEqual(report.delivered, (SoundEvent.CAPTURE, SoundEvent.END))

    def test_master_disable_never_touches_asset_adapter(self) -> None:
        assets = FakeAssetPlayback()
        report = ProfiledSoundRuntime(assets, SoundProfile(master_enabled=False)).dispatch(
            [SoundEvent.MOVE]
        )
        self.assertTrue(report.disabled)
        self.assertEqual(assets.requests, [])

    def test_preview_supports_classroom_namespace_without_chess_dispatch(self) -> None:
        assets = FakeAssetPlayback()
        profile = SoundProfile(
            pack_id="class.pack",
            master_volume_percent=60,
            events={
                "classroom.join": SoundEventPreference(
                    enabled=True,
                    volume_percent=50,
                    sound_id="room.join.soft",
                )
            },
        )
        result = ProfiledSoundRuntime(assets, profile).preview("classroom.join")
        self.assertTrue(result.ok)
        self.assertTrue(result.delivered)
        self.assertEqual(
            assets.requests,
            [
                SoundAssetRequest(
                    pack_id="class.pack",
                    event_id="classroom.join",
                    sound_id="room.join.soft",
                    volume=30,
                    preview=True,
                )
            ],
        )

    def test_disabled_event_preview_is_silent_and_does_not_call_adapter(self) -> None:
        assets = FakeAssetPlayback()
        profile = SoundProfile(
            events={"move": SoundEventPreference(enabled=False, sound_id="quiet.move")}
        )
        result = ProfiledSoundRuntime(assets, profile).preview("move")
        self.assertTrue(result.ok)
        self.assertFalse(result.delivered)
        self.assertIsNone(result.request)
        self.assertEqual(assets.requests, [])

    def test_master_disabled_preview_is_silent_and_does_not_call_adapter(self) -> None:
        assets = FakeAssetPlayback()
        profile = SoundProfile(
            master_enabled=False,
            events={"move": SoundEventPreference(enabled=True, sound_id="quiet.move")},
        )
        result = ProfiledSoundRuntime(assets, profile).preview("move")
        self.assertTrue(result.ok)
        self.assertFalse(result.delivered)
        self.assertIsNone(result.request)
        self.assertEqual(assets.requests, [])

    def test_preview_failure_is_explicit_and_has_no_fallback(self) -> None:
        assets = FakeAssetPlayback(fail_sound_id="broken.move")
        profile = SoundProfile(events={"move": SoundEventPreference(sound_id="broken.move")})
        result = ProfiledSoundRuntime(assets, profile).preview("move")
        self.assertFalse(result.ok)
        self.assertFalse(result.delivered)
        self.assertEqual(result.error_type, "FileNotFoundError")
        self.assertEqual(len(assets.requests), 1)

    def test_game_runtime_keeps_capture_check_end_order_with_profile(self) -> None:
        assets = FakeAssetPlayback()
        game = GameSoundRuntime(ProfiledSoundRuntime(assets, SoundProfile()))
        game.move(MoveSoundFacts(capture=True, check=True, game_ended=True))
        self.assertEqual(
            [request.event_id for request in assets.requests],
            ["capture", "check", "end"],
        )

    def test_dynamic_profile_provider_applies_next_dispatch_without_new_game_state(self) -> None:
        assets = FakeAssetPlayback()
        current = {"profile": SoundProfile(master_volume_percent=80)}
        runtime = ProfiledSoundRuntime(assets, lambda: current["profile"])
        runtime.dispatch([SoundEvent.MOVE])
        current["profile"] = SoundProfile(
            master_volume_percent=50,
            events={"move": SoundEventPreference(True, 20, "quiet.move")},
        )
        runtime.dispatch([SoundEvent.MOVE])
        self.assertEqual(
            [(request.sound_id, request.volume) for request in assets.requests],
            [("move", 80), ("quiet.move", 10)],
        )

    def test_one_profile_snapshot_is_used_for_entire_semantic_dispatch(self) -> None:
        assets = FakeAssetPlayback()
        profiles = [
            SoundProfile(
                pack_id="first.pack",
                master_volume_percent=80,
                events={
                    "capture": SoundEventPreference(True, 50, "first.capture"),
                    "check": SoundEventPreference(True, 25, "first.check"),
                    "end": SoundEventPreference(True, 10, "first.end"),
                },
            ),
            SoundProfile(
                pack_id="second.pack",
                master_volume_percent=20,
                events={
                    "capture": SoundEventPreference(True, 100, "second.capture"),
                    "check": SoundEventPreference(True, 100, "second.check"),
                    "end": SoundEventPreference(True, 100, "second.end"),
                },
            ),
        ]
        calls = {"count": 0}

        def provider() -> SoundProfile:
            index = min(calls["count"], len(profiles) - 1)
            calls["count"] += 1
            return profiles[index]

        runtime = ProfiledSoundRuntime(assets, provider)
        calls["count"] = 0  # constructor validation is not part of a dispatch snapshot
        runtime.dispatch([SoundEvent.CAPTURE, SoundEvent.CHECK, SoundEvent.END])
        self.assertEqual(calls["count"], 1)
        self.assertEqual(
            [(request.pack_id, request.sound_id, request.volume) for request in assets.requests],
            [
                ("first.pack", "first.capture", 40),
                ("first.pack", "first.check", 20),
                ("first.pack", "first.end", 8),
            ],
        )

    def test_preview_resolves_one_current_profile_snapshot(self) -> None:
        assets = FakeAssetPlayback()
        calls = {"count": 0}
        profile = SoundProfile(
            pack_id="preview.pack",
            master_volume_percent=70,
            events={"move": SoundEventPreference(True, 50, "preview.move")},
        )

        def provider() -> SoundProfile:
            calls["count"] += 1
            return profile

        runtime = ProfiledSoundRuntime(assets, provider)
        calls["count"] = 0
        result = runtime.preview("move")
        self.assertEqual(calls["count"], 1)
        self.assertTrue(result.delivered)
        self.assertEqual(result.request.volume, 35)
        self.assertEqual(result.request.sound_id, "preview.move")


if __name__ == "__main__":
    unittest.main()
