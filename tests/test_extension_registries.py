import unittest

from acs.notation_registry import NotationProfileDescriptor, NotationProfileRegistry
from acs.sound_dispatch import SoundEventSinkRegistry, SoundSinkDescriptor
from acs.sound_events import SoundEvent, SoundEventPolicy, MoveSoundFacts


class NotationProfileRegistryTests(unittest.TestCase):
    def test_builtins_delegate_to_canonical_formatter(self):
        registry = NotationProfileRegistry()
        self.assertEqual(registry.profile_ids(), ("san", "uk_literal", "en_literal"))
        self.assertEqual(registry.format("Nf3", "SAN"), "Nf3")
        self.assertEqual(registry.format("Bb5+", "uk_literal"), "слон b 5, шах")
        self.assertEqual(registry.format("Rxe7+", "en_literal"), "rook takes e 7, check")

    def test_custom_profile_registers_without_editing_canonical_formatter(self):
        registry = NotationProfileRegistry()
        registry.register(
            NotationProfileDescriptor("compact", "Compact"),
            lambda san: f"<{san}>",
        )
        self.assertEqual(registry.format("e4", "compact"), "<e4>")
        self.assertIn("compact", registry.profile_ids())

    def test_locale_filter_and_metadata(self):
        registry = NotationProfileRegistry()
        self.assertEqual(registry.profile_ids(locale="UK"), ("uk_literal",))
        self.assertTrue(registry.descriptor("san").built_in)

    def test_duplicate_and_builtin_removal_are_rejected(self):
        registry = NotationProfileRegistry()
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(NotationProfileDescriptor("san", "Other"), str)
        with self.assertRaisesRegex(ValueError, "cannot be unregistered"):
            registry.unregister("SAN")

    def test_external_profile_can_be_unregistered(self):
        registry = NotationProfileRegistry(include_builtins=False)
        registry.register(NotationProfileDescriptor("custom", "Custom"), str)
        registry.unregister("CUSTOM")
        with self.assertRaisesRegex(KeyError, "unknown notation profile"):
            registry.descriptor("custom")

    def test_formatter_must_return_text(self):
        registry = NotationProfileRegistry(include_builtins=False)
        registry.register(NotationProfileDescriptor("bad", "Bad"), lambda san: 1)
        with self.assertRaisesRegex(TypeError, "non-string"):
            registry.format("e4", "bad")


class SoundEventSinkRegistryTests(unittest.TestCase):
    def test_multiple_sinks_receive_semantic_events_in_registration_order(self):
        registry = SoundEventSinkRegistry()
        received = []
        registry.register(SoundSinkDescriptor("wav", "WAV"), lambda event: received.append(("wav", event)))
        registry.register(SoundSinkDescriptor("log", "Log"), lambda event: received.append(("log", event)))
        report = registry.emit(SoundEvent.CAPTURE)
        self.assertTrue(report.ok)
        self.assertEqual((report.attempted, report.delivered), (2, 2))
        self.assertEqual(received, [("wav", SoundEvent.CAPTURE), ("log", SoundEvent.CAPTURE)])

    def test_event_filter_only_receives_declared_events(self):
        registry = SoundEventSinkRegistry()
        received = []
        registry.register(
            SoundSinkDescriptor("alerts", "Alerts", frozenset({SoundEvent.CHECK, SoundEvent.END})),
            received.append,
        )
        self.assertEqual(registry.emit(SoundEvent.MOVE).attempted, 0)
        self.assertEqual(registry.emit(SoundEvent.CHECK).delivered, 1)
        self.assertEqual(received, [SoundEvent.CHECK])

    def test_broken_adapter_is_isolated_and_reported(self):
        registry = SoundEventSinkRegistry()
        received = []
        def broken(event):
            raise RuntimeError("audio unavailable")
        registry.register(SoundSinkDescriptor("broken", "Broken"), broken)
        registry.register(SoundSinkDescriptor("working", "Working"), received.append)
        report = registry.emit(SoundEvent.MOVE)
        self.assertFalse(report.ok)
        self.assertEqual((report.attempted, report.delivered), (2, 1))
        self.assertEqual(report.failures[0].sink_id, "broken")
        self.assertEqual(report.failures[0].error_type, "RuntimeError")
        self.assertEqual(received, [SoundEvent.MOVE])

    def test_policy_event_sequence_can_be_dispatched_without_chess_duplication(self):
        registry = SoundEventSinkRegistry()
        received = []
        registry.register(SoundSinkDescriptor("capture", "Capture"), received.append)
        events = SoundEventPolicy.for_move(MoveSoundFacts(capture=True, check=True, game_ended=True))
        reports = registry.emit_many(events)
        self.assertEqual(received, [SoundEvent.CAPTURE, SoundEvent.CHECK, SoundEvent.END])
        self.assertTrue(all(report.ok for report in reports))

    def test_duplicate_unknown_and_invalid_event_are_rejected(self):
        registry = SoundEventSinkRegistry()
        registry.register(SoundSinkDescriptor("wav", "WAV"), lambda event: None)
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(SoundSinkDescriptor("wav", "Other"), lambda event: None)
        with self.assertRaisesRegex(KeyError, "unknown sound sink"):
            registry.unregister("missing")
        with self.assertRaisesRegex(TypeError, "SoundEvent"):
            registry.emit("move")


if __name__ == "__main__":
    unittest.main()
