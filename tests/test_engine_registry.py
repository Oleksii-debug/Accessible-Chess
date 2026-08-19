import unittest

from acs.engine_ports import (
    ChessEnginePort,
    EngineContractError,
    EngineContractErrorCode,
)
from acs.engine_registry import (
    EngineCapability,
    EngineProviderDescriptor,
    EngineProviderRegistry,
)


class FakeEngine:
    def analyze(self, fen, multipv=5, depth=16):
        return []

    def best_move(self, fen, skill_level=10, movetime_ms=500):
        return "e2e4"

    def close(self):
        pass


class IncompleteEngine:
    def close(self):
        pass


class EngineProviderRegistryTests(unittest.TestCase):
    def descriptor(self, provider_id="stockfish", *, capabilities=None):
        return EngineProviderDescriptor(
            provider_id,
            provider_id.title(),
            frozenset(capabilities or {EngineCapability.ANALYSIS, EngineCapability.MOVE}),
        )

    def test_register_is_lazy_and_create_uses_selected_factory(self):
        created = []
        registry = EngineProviderRegistry()
        registry.register(self.descriptor(), lambda: created.append("stockfish") or FakeEngine())
        self.assertEqual((), tuple(created))
        self.assertEqual(("stockfish",), registry.provider_ids())

        engine = registry.create("stockfish", require=EngineCapability.ANALYSIS)
        self.assertIsInstance(engine, ChessEnginePort)
        self.assertEqual(["stockfish"], created)

    def test_multiple_providers_can_be_added_without_replacing_registry_logic(self):
        registry = EngineProviderRegistry()
        registry.register(self.descriptor("stockfish"), FakeEngine)
        registry.register(self.descriptor("futureuci"), FakeEngine)
        self.assertEqual(("stockfish", "futureuci"), registry.provider_ids())
        self.assertIsInstance(registry.create("futureuci"), FakeEngine)

    def test_duplicate_stable_provider_id_is_rejected(self):
        registry = EngineProviderRegistry()
        registry.register(self.descriptor(), FakeEngine)
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(self.descriptor(), FakeEngine)

    def test_descriptor_requires_stable_lowercase_id_title_and_capability(self):
        with self.assertRaises(ValueError):
            self.descriptor("Stockfish")
        with self.assertRaises(ValueError):
            EngineProviderDescriptor("stockfish", " ", frozenset({EngineCapability.MOVE}))
        with self.assertRaises(ValueError):
            EngineProviderDescriptor("stockfish", "Stockfish", frozenset())

    def test_capability_filter_does_not_instantiate_provider(self):
        created = []
        registry = EngineProviderRegistry()
        registry.register(
            self.descriptor("analysis", capabilities={EngineCapability.ANALYSIS}),
            lambda: created.append(True) or FakeEngine(),
        )
        registry.register(
            self.descriptor("play", capabilities={EngineCapability.MOVE}),
            FakeEngine,
        )
        self.assertEqual(("analysis",), registry.provider_ids(capability=EngineCapability.ANALYSIS))
        self.assertEqual([], created)

    def test_required_capability_is_enforced_before_factory_runs(self):
        created = []
        registry = EngineProviderRegistry()
        registry.register(
            self.descriptor("play", capabilities={EngineCapability.MOVE}),
            lambda: created.append(True) or FakeEngine(),
        )
        with self.assertRaisesRegex(ValueError, "does not support analysis"):
            registry.create("play", require=EngineCapability.ANALYSIS)
        self.assertEqual([], created)

    def test_incompatible_factory_result_is_rejected_at_creation_boundary(self):
        registry = EngineProviderRegistry()
        registry.register(self.descriptor(), IncompleteEngine)
        with self.assertRaisesRegex(EngineContractError, "incompatible adapter") as caught:
            registry.create("stockfish")
        self.assertEqual(
            caught.exception.code,
            EngineContractErrorCode.INVALID_PROVIDER,
        )

    def test_unregister_removes_provider_without_affecting_others(self):
        registry = EngineProviderRegistry()
        registry.register(self.descriptor("stockfish"), FakeEngine)
        registry.register(self.descriptor("futureuci"), FakeEngine)
        registry.unregister("STOCKFISH")
        self.assertEqual(("futureuci",), registry.provider_ids())
        with self.assertRaises(KeyError):
            registry.create("stockfish")

    def test_unknown_and_empty_provider_ids_fail_cleanly(self):
        registry = EngineProviderRegistry()
        with self.assertRaises(ValueError):
            registry.create(" ")
        with self.assertRaises(KeyError):
            registry.create("missing")

    def test_descriptor_rejects_scalar_and_container_coercion(self):
        valid_caps = frozenset({EngineCapability.ANALYSIS})
        invalid = (
            (True, "Engine", valid_caps),
            ("1engine", "Engine", valid_caps),
            ("engine.provider", "Engine", valid_caps),
            ("engіne", "Engine", valid_caps),
            ("engine", True, valid_caps),
            ("engine", "First\nSecond", valid_caps),
            ("engine", "Engine", {EngineCapability.ANALYSIS}),
            ("engine", "Engine", [EngineCapability.ANALYSIS]),
            ("engine", "Engine", frozenset({"analysis"})),
            ("engine", "Engine", frozenset({True})),
        )
        for values in invalid:
            with self.subTest(descriptor=values):
                with self.assertRaises(EngineContractError) as caught:
                    EngineProviderDescriptor(*values)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_CONFIG,
                )

        normalized = EngineProviderDescriptor(
            "future_uci-2",
            "  Future UCI  ",
            valid_caps,
        )
        self.assertEqual(normalized.title, "Future UCI")

    def test_registration_validates_inputs_before_mutation_and_keeps_falsey_factory(self):
        registry = EngineProviderRegistry()
        with self.assertRaisesRegex(TypeError, "EngineProviderDescriptor"):
            registry.register(object(), FakeEngine)
        with self.assertRaises(EngineContractError) as factory_error:
            registry.register(self.descriptor(), object())
        self.assertEqual(
            factory_error.exception.code,
            EngineContractErrorCode.INVALID_PROVIDER,
        )
        self.assertEqual(registry.provider_ids(), ())

        class FalseyFactory:
            def __init__(self):
                self.calls = 0

            def __bool__(self):
                return False

            def __call__(self):
                self.calls += 1
                return FakeEngine()

        factory = FalseyFactory()
        registry.register(self.descriptor(), factory)
        self.assertIsInstance(registry.create("stockfish"), FakeEngine)
        self.assertEqual(factory.calls, 1)

    def test_capability_selectors_reject_raw_strings_before_factory_use(self):
        created = []
        registry = EngineProviderRegistry()
        registry.register(
            self.descriptor(),
            lambda: created.append(True) or FakeEngine(),
        )

        for operation in (
            lambda: registry.descriptors(capability="analysis"),
            lambda: registry.provider_ids(capability="analysis"),
            lambda: registry.create("stockfish", require="analysis"),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(EngineContractError) as caught:
                    operation()
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_REQUEST,
                )
        self.assertEqual(created, [])

    def test_provider_id_lookup_rejects_non_text_and_non_slug_values(self):
        registry = EngineProviderRegistry()
        registry.register(self.descriptor(), FakeEngine)
        for provider_id in (True, 7, b"stockfish", "bad/id", "bad.id"):
            with self.subTest(provider_id=provider_id):
                with self.assertRaises(EngineContractError) as caught:
                    registry.create(provider_id)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_REQUEST,
                )
        self.assertIsInstance(registry.create("  STOCKFISH  "), FakeEngine)

    def test_incompatible_class_result_does_not_poison_factory_retry(self):
        registry = EngineProviderRegistry()
        outputs = [FakeEngine, FakeEngine()]
        registry.register(self.descriptor(), lambda: outputs.pop(0))

        with self.assertRaises(EngineContractError) as caught:
            registry.create("stockfish")
        self.assertEqual(
            caught.exception.code,
            EngineContractErrorCode.INVALID_PROVIDER,
        )
        self.assertIsInstance(registry.create("stockfish"), FakeEngine)


if __name__ == "__main__":
    unittest.main()
