import unittest

from acs.notation_registry import NotationProfileDescriptor, NotationProfileRegistry
from acs.sound_dispatch import (
    SoundDeliveryFailure,
    SoundDeliveryReport,
    SoundEventSinkRegistry,
    SoundSinkDescriptor,
)
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

    def test_descriptor_rejects_scalar_coercion_and_normalizes_metadata(self):
        invalid = (
            (True, "Profile", None, False),
            ("1profile", "Profile", None, False),
            ("profile.name", "Profile", None, False),
            ("profіle", "Profile", None, False),
            ("profile", True, None, False),
            ("profile", "First\nSecond", None, False),
            ("profile", "Profile", True, False),
            ("profile", "Profile", "en_US", False),
            ("profile", "Profile", None, 1),
        )
        for values in invalid:
            with self.subTest(descriptor=values):
                with self.assertRaises((TypeError, ValueError)):
                    NotationProfileDescriptor(*values)

        descriptor = NotationProfileDescriptor(
            "future_profile",
            "  Future profile  ",
            " EN-us ",
        )
        self.assertEqual(descriptor.title, "Future profile")
        self.assertEqual(descriptor.locale, "en-us")

    def test_registration_and_lookup_validate_without_mutating_registry(self):
        registry = NotationProfileRegistry(include_builtins=False)
        with self.assertRaisesRegex(TypeError, "NotationProfileDescriptor"):
            registry.register(object(), str)
        with self.assertRaisesRegex(TypeError, "formatter"):
            registry.register(NotationProfileDescriptor("custom", "Custom"), object())
        self.assertEqual(registry.profile_ids(), ())

        class FalseyFormatter:
            def __bool__(self):
                return False

            def __call__(self, san):
                return f"<{san}>"

        registry.register(
            NotationProfileDescriptor("custom", "Custom", "en-US"),
            FalseyFormatter(),
        )
        self.assertEqual(registry.format("e4", "  CUSTOM  "), "<e4>")
        self.assertEqual(registry.profile_ids(locale=" EN-us "), ("custom",))
        for profile_id in (True, 7, b"custom", "bad/id", "bad.id"):
            with self.subTest(profile_id=profile_id):
                with self.assertRaises((TypeError, ValueError)):
                    registry.descriptor(profile_id)

    def test_format_boundary_rejects_invalid_input_and_output_but_allows_retry(self):
        outputs = ["", "bad\noutput", "valid"]
        calls = []
        registry = NotationProfileRegistry(include_builtins=False)
        registry.register(
            NotationProfileDescriptor("retry", "Retry"),
            lambda san: calls.append(san) or outputs.pop(0),
        )

        for san in (True, "", "e4\n"):
            with self.subTest(san=san):
                with self.assertRaises((TypeError, ValueError)):
                    registry.format(san, "retry")
        self.assertEqual(calls, [])

        with self.assertRaisesRegex(ValueError, "invalid text output"):
            registry.format("e4", "retry")
        with self.assertRaisesRegex(ValueError, "invalid text output"):
            registry.format("e4", "retry")
        self.assertEqual(registry.format("e4", "retry"), "valid")

    def test_include_builtins_and_locale_selector_require_exact_types(self):
        with self.assertRaisesRegex(TypeError, "include_builtins"):
            NotationProfileRegistry(include_builtins=1)
        registry = NotationProfileRegistry()
        for locale in (True, 7, b"uk", "en_US"):
            with self.subTest(locale=locale):
                with self.assertRaises((TypeError, ValueError)):
                    registry.descriptors(locale=locale)


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

    def test_descriptor_rejects_coercion_and_mutable_or_raw_event_filters(self):
        invalid = (
            (True, "Sink", None),
            ("1sink", "Sink", None),
            ("sink.name", "Sink", None),
            ("sіnk", "Sink", None),
            ("sink", True, None),
            ("sink", "First\nSecond", None),
            ("sink", "Sink", set({SoundEvent.MOVE})),
            ("sink", "Sink", frozenset({"move"})),
            ("sink", "Sink", frozenset()),
        )
        for values in invalid:
            with self.subTest(descriptor=values):
                with self.assertRaises((TypeError, ValueError)):
                    SoundSinkDescriptor(*values)

        descriptor = SoundSinkDescriptor("future_sink", "  Future sink  ")
        self.assertEqual(descriptor.title, "Future sink")
        with self.assertRaisesRegex(TypeError, "SoundEvent"):
            descriptor.accepts("move")

    def test_registration_lookup_and_selector_validate_before_side_effects(self):
        registry = SoundEventSinkRegistry()
        with self.assertRaisesRegex(TypeError, "SoundSinkDescriptor"):
            registry.register(object(), list.append)
        with self.assertRaisesRegex(TypeError, "callable"):
            registry.register(SoundSinkDescriptor("capture", "Capture"), object())
        self.assertEqual(registry.descriptors(), ())

        received = []

        class FalseySink:
            def __bool__(self):
                return False

            def __call__(self, event):
                received.append(event)

        registry.register(SoundSinkDescriptor("capture", "Capture"), FalseySink())
        self.assertEqual(registry.descriptor("  CAPTURE  ").sink_id, "capture")
        for value in (True, 7, b"capture", "bad/id", "bad.id"):
            with self.subTest(value=value):
                with self.assertRaises((TypeError, ValueError)):
                    registry.descriptor(value)
        with self.assertRaisesRegex(TypeError, "SoundEvent"):
            registry.descriptors(event="move")
        self.assertEqual(registry.emit(SoundEvent.MOVE).delivered, 1)
        self.assertEqual(received, [SoundEvent.MOVE])

    def test_emit_many_preflights_entire_batch_before_delivery(self):
        received = []
        registry = SoundEventSinkRegistry()
        registry.register(SoundSinkDescriptor("capture", "Capture"), received.append)

        with self.assertRaisesRegex(TypeError, "only SoundEvent"):
            registry.emit_many((SoundEvent.MOVE, "capture"))
        self.assertEqual(received, [])

        def broken_iterable():
            yield SoundEvent.MOVE
            raise RuntimeError("source failed")

        with self.assertRaisesRegex(RuntimeError, "source failed"):
            registry.emit_many(broken_iterable())
        self.assertEqual(received, [])

    def test_unprintable_adapter_error_is_isolated(self):
        class UnprintableError(RuntimeError):
            def __str__(self):
                raise RuntimeError("cannot format")

        received = []
        registry = SoundEventSinkRegistry()
        registry.register(
            SoundSinkDescriptor("broken", "Broken"),
            lambda event: (_ for _ in ()).throw(UnprintableError()),
        )
        registry.register(SoundSinkDescriptor("capture", "Capture"), received.append)

        report = registry.emit(SoundEvent.CAPTURE)
        self.assertEqual((report.attempted, report.delivered), (2, 1))
        self.assertEqual(report.failures[0].message, "<unprintable adapter error>")
        self.assertEqual(received, [SoundEvent.CAPTURE])

    def test_delivery_dtos_reject_inconsistent_or_mutable_shapes(self):
        failure = SoundDeliveryFailure(
            "broken",
            SoundEvent.MOVE,
            "RuntimeError",
            "offline",
        )
        report = SoundDeliveryReport(1, 0, (failure,))
        self.assertFalse(report.ok)
        for values in (
            (True, 0, ()),
            (1, True, ()),
            (-1, 0, ()),
            (1, 0, []),
            (2, 0, (failure,)),
        ):
            with self.subTest(report=values):
                with self.assertRaises((TypeError, ValueError)):
                    SoundDeliveryReport(*values)


if __name__ == "__main__":
    unittest.main()
