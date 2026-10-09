import unittest

from acs.sound_events import MoveSoundFacts, SoundEvent, SoundEventPolicy
from acs.sound_runtime import GameSoundRuntime, SoundRuntime, SoundRuntimeSettings


class RecordingPlayback:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def play(self, event, *, volume):
        self.calls.append((event, volume))
        if event is self.fail_on:
            raise FileNotFoundError("C:/private/build/assets/missing.wav")


class FalseySettingsProvider:
    def __init__(self, settings):
        self.settings = settings
        self.calls = 0

    def __bool__(self):
        return False

    def __call__(self):
        self.calls += 1
        return self.settings


class Dev3SoundFailureIsolationTests(unittest.TestCase):
    def test_move_sound_facts_reject_truthy_scalar_coercion(self):
        fields = ("legal", "capture", "check", "castle", "promotion", "game_ended")
        for field in fields:
            for invalid in (1, 0, "true", None):
                with self.subTest(field=field, invalid=invalid):
                    values = {field: invalid}
                    with self.assertRaises(TypeError):
                        MoveSoundFacts(**values)

        with self.assertRaises(TypeError):
            SoundEventPolicy.for_move(object())

    def test_settings_mapping_rejects_string_bool_and_numeric_coercion(self):
        self.assertEqual(
            SoundRuntimeSettings.from_mapping({"sounds": False, "volume": 37}),
            SoundRuntimeSettings(False, 37),
        )
        invalid = (
            {"sounds": "false", "volume": 80},
            {"sounds": 0, "volume": 80},
            {"sounds": True, "volume": "80"},
            {"sounds": True, "volume": True},
        )
        for mapping in invalid:
            with self.subTest(mapping=mapping):
                with self.assertRaises((TypeError, ValueError)):
                    SoundRuntimeSettings.from_mapping(mapping)

        with self.assertRaises(TypeError):
            SoundRuntimeSettings.from_mapping(object())

    def test_falsey_settings_provider_is_preserved_and_disable_never_touches_playback(self):
        playback = RecordingPlayback()
        provider = FalseySettingsProvider(SoundRuntimeSettings(False, 80))
        report = SoundRuntime(playback, settings=provider).dispatch((SoundEvent.MOVE,))
        self.assertTrue(report.disabled)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(playback.calls, [])

    def test_error_sink_failure_cannot_abort_later_sound_delivery(self):
        playback = RecordingPlayback(fail_on=SoundEvent.CAPTURE)
        sink_calls = []

        def broken_sink(failure):
            sink_calls.append(failure.event)
            raise RuntimeError("logger unavailable")

        report = SoundRuntime(playback, error_sink=broken_sink).dispatch(
            (SoundEvent.CAPTURE, SoundEvent.CHECK, SoundEvent.END)
        )

        self.assertEqual(sink_calls, [SoundEvent.CAPTURE])
        self.assertEqual(report.delivered, (SoundEvent.CHECK, SoundEvent.END))
        self.assertEqual(tuple(item.event for item in report.failures), (SoundEvent.CAPTURE,))
        self.assertEqual(
            tuple(event for event, _ in playback.calls),
            (SoundEvent.CAPTURE, SoundEvent.CHECK, SoundEvent.END),
        )

    def test_runtime_constructor_rejects_false_green_infrastructure_shapes(self):
        with self.assertRaises(TypeError):
            SoundRuntime(object())
        with self.assertRaises(TypeError):
            SoundRuntime(RecordingPlayback, settings=SoundRuntimeSettings())
        with self.assertRaises(TypeError):
            SoundRuntime(RecordingPlayback(), settings=object())
        with self.assertRaises(TypeError):
            SoundRuntime(RecordingPlayback(), error_sink=object())
        with self.assertRaises(TypeError):
            GameSoundRuntime(object())


if __name__ == "__main__":
    unittest.main()
