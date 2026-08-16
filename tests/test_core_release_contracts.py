from __future__ import annotations

import unittest

from acs.chesscore import Board
from acs.engine_ports import ChessEnginePort
from acs.engine_registry import (
    EngineCapability,
    EngineProviderDescriptor,
    EngineProviderRegistry,
)
from acs.entitlements import (
    CORE_FEATURE_IDS,
    EntitlementSnapshot,
    EntitlementState,
    FeatureGate,
    FeatureId,
    FreeBetaLicensePolicy,
)
from acs.keybindings import ActionRegistry, BindingContext
from acs.move_entry import MoveEntryKind, parse_move_entry
from acs.notation import format_san
from acs.notation_registry import NotationProfileRegistry
from acs.sound_dispatch import SoundEventSinkRegistry, SoundSinkDescriptor
from acs.sound_events import MoveSoundFacts, SoundEvent, SoundEventPolicy


class _FakeEngine:
    def analyze(self, fen: str, multipv: int = 5, depth: int = 16):
        return ()

    def best_move(self, fen: str, skill_level: int = 10, movetime_ms: int = 500):
        return None

    def close(self) -> None:
        return None


class CoreReleaseContractTests(unittest.TestCase):
    def test_ui_submitted_e4_reaches_exact_canonical_core_state(self) -> None:
        board = Board()
        intent = parse_move_entry("e4")
        self.assertEqual(intent.kind, MoveEntryKind.CHESS_MOVE)
        self.assertEqual(intent.move_text, "e4")
        before = board.fen()
        side_before = board.turn
        san = board.push_text(intent.move_text)
        self.assertEqual(side_before, "w")
        self.assertEqual(san, "e4")
        self.assertEqual(board.fen(), "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
        self.assertEqual(board.turn, "b")
        self.assertEqual(len(board.undo_stack), 1)
        self.assertEqual(board.undo_stack[0], (before, "e4"))
        self.assertEqual(board.redo_stack, [])
        self.assertEqual(SoundEventPolicy.for_move(MoveSoundFacts()), (SoundEvent.MOVE,))
        self.assertEqual(board.undo(), "e4")
        self.assertEqual(board.fen(), before)
        self.assertEqual(board.turn, "w")
        self.assertEqual(board.redo(), "e4")
        self.assertEqual(board.fen(), "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")

    def test_invalid_e9_is_atomic_and_emits_only_illegal_semantics(self) -> None:
        board = Board()
        board.push_text("e4")
        before = board.fen()
        undo_before = tuple(board.undo_stack)
        redo_before = tuple(board.redo_stack)
        last_before = board.last_move
        intent = parse_move_entry("e9")
        self.assertEqual(intent.kind, MoveEntryKind.CHESS_MOVE)
        self.assertEqual(intent.move_text, "e9")
        with self.assertRaises(ValueError):
            board.push_text(intent.move_text)
        self.assertEqual(board.fen(), before)
        self.assertEqual(board.turn, "b")
        self.assertEqual(tuple(board.undo_stack), undo_before)
        self.assertEqual(tuple(board.redo_stack), redo_before)
        self.assertEqual(board.last_move, last_before)
        self.assertEqual(SoundEventPolicy.for_move(MoveSoundFacts(legal=False)), (SoundEvent.ILLEGAL,))

    def test_default_action_registry_is_unambiguous_and_ids_are_stable(self) -> None:
        registry = ActionRegistry()
        definitions = registry.definitions()
        action_ids = [item.action_id for item in definitions]
        self.assertEqual(len(action_ids), len(set(action_ids)))
        self.assertTrue(all(action_id == action_id.strip().casefold() for action_id in action_ids))
        self.assertFalse([item for item in registry.validate() if item.severity == "error"])

    def test_literal_position_syntax_wins_over_remappable_command_aliases(self) -> None:
        registry = ActionRegistry()
        registry.set_alias("move.white_to_move", "position")
        registry.set_alias("move.black_to_move", "side")
        intent = parse_move_entry("W: K e1 P e4 B: K e8 P e5", registry)
        self.assertEqual(intent.kind, MoveEntryKind.POSITION)
        self.assertIsNotNone(intent.position)
        self.assertEqual(intent.position.turn, "w")

    def test_context_resolution_keeps_global_recovery_actions_visible(self) -> None:
        registry = ActionRegistry()
        undo = registry.resolve_binding(BindingContext.BOARD, "Ctrl+Z")
        redo = registry.resolve_binding(BindingContext.ANALYSIS, "Ctrl+Shift+Z")
        self.assertIsNotNone(undo)
        self.assertIsNotNone(redo)
        self.assertEqual(undo.action_id, "edit.undo")
        self.assertEqual(redo.action_id, "edit.redo")
        self.assertEqual(undo.context, BindingContext.GLOBAL)
        self.assertEqual(redo.context, BindingContext.GLOBAL)

    def test_notation_registry_delegates_all_builtins_to_canonical_formatter(self) -> None:
        registry = NotationProfileRegistry()
        samples = ("Nf3", "Rxe7+", "exd8=Q+", "O-O-O+")
        for profile_id in registry.profile_ids():
            descriptor = registry.descriptor(profile_id)
            self.assertTrue(descriptor.built_in)
            for san in samples:
                self.assertEqual(registry.format(san, profile_id), format_san(san, profile_id), (profile_id, san))

    def test_engine_registration_is_lazy_and_depends_only_on_port(self) -> None:
        created: list[str] = []
        registry = EngineProviderRegistry()
        descriptor = EngineProviderDescriptor(provider_id="test_engine", title="Test engine", capabilities=frozenset({EngineCapability.ANALYSIS, EngineCapability.MOVE}))
        def factory() -> ChessEnginePort:
            created.append("created")
            return _FakeEngine()
        registry.register(descriptor, factory)
        self.assertEqual(created, [])
        self.assertEqual(registry.provider_ids(), ("test_engine",))
        engine = registry.create("TEST_ENGINE", require=EngineCapability.ANALYSIS)
        self.assertIsInstance(engine, ChessEnginePort)
        self.assertEqual(created, ["created"])

    def test_sound_adapter_failure_isolated_from_other_sinks(self) -> None:
        received: list[SoundEvent] = []
        registry = SoundEventSinkRegistry()
        def broken(_: SoundEvent) -> None:
            raise RuntimeError("device unavailable")
        registry.register(SoundSinkDescriptor("broken", "Broken sink"), broken)
        registry.register(SoundSinkDescriptor("capture", "Capture sink"), received.append)
        report = registry.emit(SoundEvent.CAPTURE)
        self.assertEqual(report.attempted, 2)
        self.assertEqual(report.delivered, 1)
        self.assertFalse(report.ok)
        self.assertEqual(received, [SoundEvent.CAPTURE])
        self.assertEqual(report.failures[0].sink_id, "broken")

    def test_free_beta_policy_and_feature_gate_share_stable_feature_ids(self) -> None:
        self.assertEqual(CORE_FEATURE_IDS, frozenset(feature.value for feature in FeatureId))
        snapshot = FreeBetaLicensePolicy().entitlement_for()
        gate = FeatureGate(current_version="0.4.0")
        self.assertEqual(snapshot.feature_ids, CORE_FEATURE_IDS)
        for feature in FeatureId:
            decision = gate.evaluate(feature, snapshot)
            self.assertTrue(decision.allowed, feature.value)
            self.assertEqual(decision.feature_id, feature.value)

    def test_revocation_fails_closed_without_changing_feature_identity(self) -> None:
        snapshot = EntitlementSnapshot(state=EntitlementState.REVOKED, feature_ids=CORE_FEATURE_IDS, source="contract_test")
        gate = FeatureGate(current_version="0.4.0")
        for feature in FeatureId:
            decision = gate.evaluate(feature, snapshot)
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.state, EntitlementState.REVOKED)
            self.assertEqual(decision.reason, "revoked")
            self.assertEqual(decision.feature_id, feature.value)


if __name__ == "__main__":
    unittest.main()
