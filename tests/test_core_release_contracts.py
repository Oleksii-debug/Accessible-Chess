from __future__ import annotations

import queue
import unittest
from unittest.mock import patch

from acs.chesscore import Board
from acs.engine import UCIEngine
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


class _TimeoutRecoveryProbe(UCIEngine):
    """Deterministic UCI probe with no subprocess or real wall-clock waits."""

    def __init__(self, lines: tuple[str, ...] = ()) -> None:
        super().__init__("fake-stockfish")
        self.proc = object()
        self._process_generation = 7
        self.lines = list(lines)
        self.sent: list[str] = []
        self.shutdown: list[object] = []
        self.stop_sync_calls: list[int] = []

    def start(self) -> None:
        return None

    def send(self, command: str) -> None:
        self.sent.append(command)

    def _wait(self, token: str, timeout: float) -> str:
        return token

    def _get_line(self, timeout: float, *, generation: int | None = None) -> str:
        if self.lines:
            return self.lines.pop(0)
        raise queue.Empty

    def _shutdown_process(self, proc) -> None:
        if proc is not None:
            self.shutdown.append(proc)


class _AnalyzeTimeoutProbe(_TimeoutRecoveryProbe):
    def _stop_and_synchronize(self, generation: int, timeout: float = 2.0) -> bool:
        self.stop_sync_calls.append(generation)
        return True


class CoreReleaseContractTests(unittest.TestCase):
    """Cross-contract release invariants for issues #5/#6/#7/#11.

    These tests intentionally exercise only presentation-neutral contracts. They
    characterize the frozen Stage-1 Core foundation without adding a new runtime
    registry or another source of truth.
    """

    def test_ui_submitted_e4_reaches_exact_canonical_core_state(self) -> None:
        """Characterize the packaged move-entry boundary below presentation/UIA.

        The UI is allowed to deliver text only. Core owns classification, legal
        move resolution, mutation, FEN/side-to-move/history and semantic events.
        This regression makes an e4 failure attributable: if this passes on the
        same source SHA, a missing packaged edit/control is not a chess-state bug.
        """

        board = Board()
        intent = parse_move_entry("e4")

        self.assertEqual(intent.kind, MoveEntryKind.CHESS_MOVE)
        self.assertEqual(intent.move_text, "e4")
        before = board.fen()
        side_before = board.turn
        san = board.push_text(intent.move_text)

        self.assertEqual(side_before, "w")
        self.assertEqual(san, "e4")
        self.assertEqual(
            board.fen(),
            "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        )
        self.assertEqual(board.turn, "b")
        self.assertEqual(len(board.undo_stack), 1)
        self.assertEqual(board.undo_stack[0], (before, "e4"))
        self.assertEqual(board.redo_stack, [])
        self.assertEqual(
            SoundEventPolicy.for_move(MoveSoundFacts()),
            (SoundEvent.MOVE,),
        )

        self.assertEqual(board.undo(), "e4")
        self.assertEqual(board.fen(), before)
        self.assertEqual(board.turn, "w")
        self.assertEqual(board.redo(), "e4")
        self.assertEqual(
            board.fen(),
            "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        )

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
        self.assertEqual(
            SoundEventPolicy.for_move(MoveSoundFacts(legal=False)),
            (SoundEvent.ILLEGAL,),
        )

    def test_uci_stop_consumes_terminal_bestmove_before_stream_reuse(self) -> None:
        engine = _TimeoutRecoveryProbe((
            "info depth 20 score cp 12 pv e2e4 e7e5",
            "bestmove e2e4 ponder e7e5",
        ))
        generation = engine._process_generation
        proc = engine.proc

        self.assertTrue(engine._stop_and_synchronize(generation))
        self.assertEqual(engine.sent, ["stop"])
        self.assertIs(engine.proc, proc)
        self.assertEqual(engine._process_generation, generation)
        self.assertEqual(engine.shutdown, [])
        self.assertEqual(engine.lines, [])

    def test_uci_unsynchronized_timeout_discards_process_generation(self) -> None:
        engine = _TimeoutRecoveryProbe()
        generation = engine._process_generation
        proc = engine.proc

        self.assertFalse(engine._stop_and_synchronize(generation, timeout=0))
        self.assertEqual(engine.sent, ["stop"])
        self.assertIsNone(engine.proc)
        self.assertIsNone(engine.reader)
        self.assertEqual(engine._process_generation, generation + 1)
        self.assertEqual(engine.shutdown, [proc])

    def test_analysis_timeout_always_routes_through_terminal_stream_sync(self) -> None:
        engine = _AnalyzeTimeoutProbe()
        generation = engine._process_generation

        with patch("acs.engine.time.monotonic", side_effect=[0.0, 61.0]):
            with self.assertRaisesRegex(RuntimeError, "analysis timed out"):
                engine.analyze(Board().fen(), multipv=5, depth=16)

        self.assertEqual(engine.stop_sync_calls, [generation])
        self.assertIn("setoption name MultiPV value 5", engine.sent)
        self.assertIn("go depth 16", engine.sent)

    def test_late_old_generation_bestmove_cannot_satisfy_new_generation(self) -> None:
        engine = UCIEngine("fake-stockfish")
        engine._process_generation = 11
        old_generation = engine._process_generation
        engine._process_generation += 1
        new_generation = engine._process_generation
        engine.q.put((old_generation, "bestmove a2a3"))
        engine.q.put((new_generation, "readyok"))

        self.assertEqual(
            engine._get_line(0.2, generation=new_generation),
            "readyok",
        )

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
                self.assertEqual(
                    registry.format(san, profile_id),
                    format_san(san, profile_id),
                    (profile_id, san),
                )

    def test_engine_registration_is_lazy_and_depends_only_on_port(self) -> None:
        created: list[str] = []
        registry = EngineProviderRegistry()
        descriptor = EngineProviderDescriptor(
            provider_id="test_engine",
            title="Test engine",
            capabilities=frozenset({EngineCapability.ANALYSIS, EngineCapability.MOVE}),
        )

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
        snapshot = EntitlementSnapshot(
            state=EntitlementState.REVOKED,
            feature_ids=CORE_FEATURE_IDS,
            source="contract_test",
        )
        gate = FeatureGate(current_version="0.4.0")

        for feature in FeatureId:
            decision = gate.evaluate(feature, snapshot)
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.state, EntitlementState.REVOKED)
            self.assertEqual(decision.reason, "revoked")
            self.assertEqual(decision.feature_id, feature.value)


if __name__ == "__main__":
    unittest.main()
