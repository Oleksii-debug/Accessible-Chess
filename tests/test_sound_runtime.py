import json
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from acs.sound_events import MoveSoundFacts, SoundEvent
from acs.sound_runtime import GameSoundRuntime, SoundRuntime, SoundRuntimeSettings
from acs.sound_profiles import SoundEventPreference, SoundProfile
from acs.sound_windows import (
    PackagedSoundAssetResolver,
    REQUIRED_SOUND_EVENTS,
    WindowsSoundPlaybackAdapter,
)


class FakePlayback:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def play(self, event, *, volume):
        self.calls.append((event, volume))
        if event == self.fail_on:
            raise FileNotFoundError(f"missing {event.value}")


class SoundRuntimeTests(unittest.TestCase):
    def test_required_move_sequences_are_deterministic(self):
        cases = [
            (MoveSoundFacts(), [SoundEvent.MOVE]),
            (MoveSoundFacts(capture=True), [SoundEvent.CAPTURE]),
            (MoveSoundFacts(check=True), [SoundEvent.MOVE, SoundEvent.CHECK]),
            (MoveSoundFacts(castle=True), [SoundEvent.CASTLE]),
            (MoveSoundFacts(promotion=True), [SoundEvent.PROMOTION]),
        ]
        for facts, expected in cases:
            fake = FakePlayback()
            game = GameSoundRuntime(SoundRuntime(fake))
            game.move(facts)
            self.assertEqual([event for event, _ in fake.calls], expected)

    def test_illegal_start_end_and_tick_are_consumable(self):
        fake = FakePlayback()
        game = GameSoundRuntime(SoundRuntime(fake))
        game.start()
        game.illegal()
        game.tick()
        game.end()
        self.assertEqual(
            [event for event, _ in fake.calls],
            [SoundEvent.START, SoundEvent.ILLEGAL, SoundEvent.TICK, SoundEvent.END],
        )

    def test_terminal_move_does_not_duplicate_game_end(self):
        fake = FakePlayback()
        game = GameSoundRuntime(SoundRuntime(fake))
        game.start()
        game.move(MoveSoundFacts(capture=True, check=True, game_ended=True))
        game.end()
        self.assertEqual(
            [event for event, _ in fake.calls],
            [SoundEvent.START, SoundEvent.CAPTURE, SoundEvent.CHECK, SoundEvent.END],
        )

    def test_takeback_rearms_game_end_without_replaying_start(self):
        fake = FakePlayback()
        game = GameSoundRuntime(SoundRuntime(fake))
        game.start()
        game.end()

        report = game.resume_after_takeback()
        game.end()

        self.assertEqual(report.requested, ())
        self.assertEqual(
            [event for event, _ in fake.calls],
            [SoundEvent.START, SoundEvent.END, SoundEvent.END],
        )

    def test_duplicate_event_ids_collapse_within_one_batch(self):
        fake = FakePlayback()
        runtime = SoundRuntime(fake)
        report = runtime.dispatch([SoundEvent.CHECK, SoundEvent.CHECK, SoundEvent.END])
        self.assertEqual(report.requested, (SoundEvent.CHECK, SoundEvent.END))
        self.assertEqual(len(fake.calls), 2)

    def test_master_disable_and_zero_volume_never_touch_adapter(self):
        for settings in (
            SoundRuntimeSettings(enabled=False, volume=80),
            SoundRuntimeSettings(enabled=True, volume=0),
        ):
            fake = FakePlayback()
            report = SoundRuntime(fake, settings=settings).dispatch([SoundEvent.MOVE])
            self.assertTrue(report.disabled)
            self.assertEqual(fake.calls, [])

    def test_volume_is_forwarded_to_adapter(self):
        fake = FakePlayback()
        SoundRuntime(fake, settings=SoundRuntimeSettings(volume=37)).dispatch([SoundEvent.MOVE])
        self.assertEqual(fake.calls, [(SoundEvent.MOVE, 37)])

    def test_adapter_failure_is_explicit_and_later_events_continue(self):
        failures = []
        fake = FakePlayback(fail_on=SoundEvent.CAPTURE)
        report = SoundRuntime(fake, error_sink=failures.append).dispatch(
            [SoundEvent.CAPTURE, SoundEvent.CHECK]
        )
        self.assertEqual(report.delivered, (SoundEvent.CHECK,))
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(report.failures[0].event, SoundEvent.CAPTURE)
        self.assertEqual(failures, list(report.failures))


class ProfiledFakePlayback(FakePlayback):
    def __init__(self, fail_on=None):
        super().__init__(fail_on=fail_on)
        self.profiled_calls = []

    def play_profiled(self, event, *, pack_id, sound_id, volume):
        self.profiled_calls.append((event, pack_id, sound_id, volume))
        if event == self.fail_on:
            raise FileNotFoundError(f"missing {event.value}")


class ProfiledSoundRuntimeTests(unittest.TestCase):
    def test_profile_preserves_semantic_order_and_applies_per_event_volume(self):
        fake = ProfiledFakePlayback()
        profile = SoundProfile(
            pack_id="soft.wood",
            master_volume_percent=80,
            events={
                "capture": SoundEventPreference(True, 50, "wood.capture"),
                "check": SoundEventPreference(True, 25, "wood.check"),
            },
        )
        game = GameSoundRuntime(SoundRuntime(fake, profile=profile))
        report = game.move(MoveSoundFacts(capture=True, check=True))

        self.assertEqual(
            [call[0] for call in fake.profiled_calls],
            [SoundEvent.CAPTURE, SoundEvent.CHECK],
        )
        self.assertEqual(
            fake.profiled_calls,
            [
                (SoundEvent.CAPTURE, "soft.wood", "wood.capture", 40),
                (SoundEvent.CHECK, "soft.wood", "wood.check", 20),
            ],
        )
        self.assertEqual(report.delivered, (SoundEvent.CAPTURE, SoundEvent.CHECK))
        self.assertEqual(report.silenced, ())

    def test_disabled_event_is_silenced_without_beep_or_adapter_call(self):
        fake = ProfiledFakePlayback()
        profile = SoundProfile(
            events={"check": SoundEventPreference(enabled=False)}
        )
        report = SoundRuntime(fake, profile=profile).dispatch(
            [SoundEvent.MOVE, SoundEvent.CHECK, SoundEvent.END]
        )
        self.assertEqual(
            [call[0] for call in fake.profiled_calls],
            [SoundEvent.MOVE, SoundEvent.END],
        )
        self.assertEqual(report.silenced, (SoundEvent.CHECK,))
        self.assertTrue(report.ok)

    def test_master_disable_marks_entire_batch_disabled_and_silenced(self):
        fake = ProfiledFakePlayback()
        report = SoundRuntime(
            fake,
            profile=SoundProfile(master_enabled=False),
        ).dispatch([SoundEvent.MOVE, SoundEvent.CHECK])
        self.assertTrue(report.disabled)
        self.assertEqual(report.silenced, (SoundEvent.MOVE, SoundEvent.CHECK))
        self.assertEqual(fake.profiled_calls, [])

    def test_profiled_playback_failure_is_reported_and_later_event_continues(self):
        fake = ProfiledFakePlayback(fail_on=SoundEvent.CAPTURE)
        report = SoundRuntime(fake, profile=SoundProfile()).dispatch(
            [SoundEvent.CAPTURE, SoundEvent.CHECK]
        )
        self.assertEqual(report.delivered, (SoundEvent.CHECK,))
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(report.failures[0].event, SoundEvent.CAPTURE)

    def test_profile_mode_requires_explicit_profiled_playback_contract(self):
        with self.assertRaisesRegex(TypeError, "play_profiled"):
            SoundRuntime(FakePlayback(), profile=SoundProfile())


class PackagedSoundResolverTests(unittest.TestCase):
    @staticmethod
    def _write_silent_wav(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(8000)
            writer.writeframes(b"\x00\x00" * 8)

    def test_exact_packaged_manifest_contract_resolves_every_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "assets" / "sounds"
            files = {}
            for event in REQUIRED_SOUND_EVENTS:
                name = f"{event.value}.wav"
                files[event.value] = name
                self._write_silent_wav(root / name)
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "files": files}), encoding="utf-8"
            )
            resolver = PackagedSoundAssetResolver(tmp)
            for event in REQUIRED_SOUND_EVENTS:
                self.assertEqual(resolver.resolve(event), (root / f"{event.value}.wav").resolve())

    def test_missing_asset_is_explicit_error_not_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "assets" / "sounds"
            root.mkdir(parents=True)
            files = {event.value: f"{event.value}.wav" for event in REQUIRED_SOUND_EVENTS}
            for event in REQUIRED_SOUND_EVENTS:
                if event is not SoundEvent.CHECK:
                    self._write_silent_wav(root / files[event.value])
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "files": files}), encoding="utf-8"
            )
            with self.assertRaises(FileNotFoundError):
                PackagedSoundAssetResolver(tmp).resolve(SoundEvent.CHECK)

    def test_manifest_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "assets" / "sounds"
            root.mkdir(parents=True)
            files = {event.value: f"{event.value}.wav" for event in REQUIRED_SOUND_EVENTS}
            files[SoundEvent.MOVE.value] = "../move.wav"
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "files": files}), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                PackagedSoundAssetResolver(tmp).load_manifest()

    def test_windows_playback_uses_python312_compatible_synchronous_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "move.wav"
            self._write_silent_wav(source)

            class StaticResolver:
                def resolve(self, event):
                    self.event = event
                    return source

            calls = []
            fake_winsound = types.SimpleNamespace(
                SND_FILENAME=0x00020000,
                SND_NODEFAULT=0x00000002,
                PlaySound=lambda sound, flags: calls.append((sound, flags)),
            )
            adapter = WindowsSoundPlaybackAdapter(
                StaticResolver(),
                cache_dir=Path(tmp) / "cache",
            )

            with patch("acs.sound_windows.sys.platform", "win32"), patch.dict(
                sys.modules,
                {"winsound": fake_winsound},
            ):
                adapter.play(SoundEvent.MOVE, volume=100)

            self.assertFalse(hasattr(fake_winsound, "SND_SYNC"))
            self.assertEqual(
                calls,
                [
                    (
                        str(source),
                        fake_winsound.SND_FILENAME | fake_winsound.SND_NODEFAULT,
                    )
                ],
            )


class WindowsProfiledSoundPlaybackTests(unittest.TestCase):
    @staticmethod
    def _write_silent_wav(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(8000)
            writer.writeframes(b"\x00\x00" * 8)

    def _fake_winsound(self, calls):
        return types.SimpleNamespace(
            SND_FILENAME=0x00020000,
            SND_NODEFAULT=0x00000002,
            PlaySound=lambda sound, flags: calls.append((sound, flags)),
        )

    def test_custom_profile_resolves_exact_custom_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            classic = root / "classic.wav"
            custom = root / "custom.wav"
            self._write_silent_wav(classic)
            self._write_silent_wav(custom)

            class Classic:
                def resolve(self, event):
                    return classic

            class Packs:
                def resolve(self, pack_id, sound_id):
                    self.request = (pack_id, sound_id)
                    return custom

            packs = Packs()
            calls = []
            adapter = WindowsSoundPlaybackAdapter(
                Classic(),
                cache_dir=root / "cache",
                pack_resolver=packs,
            )
            fake = self._fake_winsound(calls)
            with patch("acs.sound_windows.sys.platform", "win32"), patch.dict(
                sys.modules, {"winsound": fake}
            ):
                adapter.play_profiled(
                    SoundEvent.MOVE,
                    pack_id="soft.wood",
                    sound_id="alternate.move",
                    volume=100,
                )

            self.assertEqual(packs.request, ("soft.wood", "alternate.move"))
            self.assertEqual(calls[0][0], str(custom))

    def test_missing_custom_core_sound_falls_back_to_packaged_semantic_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            classic = root / "classic.wav"
            self._write_silent_wav(classic)

            class Classic:
                def resolve(self, event):
                    self.event = event
                    return classic

            class Packs:
                def resolve(self, pack_id, sound_id):
                    raise FileNotFoundError("gone")

            classic_resolver = Classic()
            calls = []
            adapter = WindowsSoundPlaybackAdapter(
                classic_resolver,
                cache_dir=root / "cache",
                pack_resolver=Packs(),
            )
            fake = self._fake_winsound(calls)
            with patch("acs.sound_windows.sys.platform", "win32"), patch.dict(
                sys.modules, {"winsound": fake}
            ):
                adapter.play_profiled(
                    SoundEvent.CHECK,
                    pack_id="gone.pack",
                    sound_id="custom.check",
                    volume=100,
                )

            self.assertEqual(classic_resolver.event, SoundEvent.CHECK)
            self.assertEqual(calls[0][0], str(classic))

    def test_classroom_custom_sound_has_no_system_or_classic_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            classic = root / "classic.wav"
            self._write_silent_wav(classic)

            class Classic:
                def resolve(self, event):
                    raise AssertionError("classic resolver must not be touched")

            class Packs:
                def resolve(self, pack_id, sound_id):
                    raise FileNotFoundError("gone")

            adapter = WindowsSoundPlaybackAdapter(
                Classic(),
                cache_dir=root / "cache",
                pack_resolver=Packs(),
            )
            with patch("acs.sound_windows.sys.platform", "win32"):
                with self.assertRaises(FileNotFoundError):
                    adapter.play_sound(
                        pack_id="gone.pack",
                        sound_id="classroom.join",
                        volume=100,
                        fallback_event=None,
                    )

    def test_scaled_cache_key_includes_source_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "one" / "move.wav"
            second = root / "two" / "move.wav"
            self._write_silent_wav(first)
            self._write_silent_wav(second)

            class Classic:
                def resolve(self, event):
                    return first

            adapter = WindowsSoundPlaybackAdapter(
                Classic(),
                cache_dir=root / "cache",
            )
            one = adapter._scaled_copy(first, 50)
            two = adapter._scaled_copy(second, 50)
            self.assertNotEqual(one.name, two.name)
            self.assertTrue(one.is_file())
            self.assertTrue(two.is_file())


if __name__ == "__main__":
    unittest.main()
