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
                    enabled=False,
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


if __name__ == "__main__":
    unittest.main()
