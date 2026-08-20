import json
import tempfile
import unittest
import wave
from pathlib import Path

from acs.sound_events import MoveSoundFacts, SoundEvent
from acs.sound_runtime import GameSoundRuntime, SoundRuntime, SoundRuntimeSettings
from acs.sound_windows import PackagedSoundAssetResolver, REQUIRED_SOUND_EVENTS


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


if __name__ == "__main__":
    unittest.main()
