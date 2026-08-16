from __future__ import annotations

import queue
import unittest

from acs.analysis_service import AnalysisService
from acs.chesscore import Board, sq_name
from acs.engine import UCIEngine
from acs.move_entry import MoveEntryKind, parse_move_entry
from acs.position_editor import PositionState
from acs.sound_events import MoveSoundFacts, SoundEvent, SoundEventPolicy


class _RecordingEngine:
    def __init__(self) -> None:
        self.analysis_fens: list[str] = []
        self.closed = 0

    def analyze(self, fen: str, multipv: int = 5, depth: int = 16):
        self.analysis_fens.append(fen)
        return ()

    def close(self) -> None:
        self.closed += 1


class _GenerationScriptedUCI(UCIEngine):
    def __init__(self, generation: int = 2) -> None:
        super().__init__("ignored.exe")
        self._process_generation = generation
        self.sent: list[str] = []

    def start(self) -> None:
        return None

    def send(self, command: str) -> None:
        self.sent.append(command)

    def _drain(self) -> None:
        return None


class Stage1CoreEngineCoherenceTests(unittest.TestCase):
    def test_complete_state_analysis_history_editor_and_shutdown_sequence(self) -> None:
        board = Board()
        engine = _RecordingEngine()
        analysis = AnalysisService(lambda: engine)
        start_fen = board.fen()

        intent = parse_move_entry("e4")
        self.assertEqual(MoveEntryKind.CHESS_MOVE, intent.kind)
        self.assertEqual("e4", board.push_text(intent.move_text))
        e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        self.assertEqual(e4_fen, board.fen())
        self.assertEqual("b", board.turn)
        self.assertEqual("e2", sq_name(board.last_move.frm))
        self.assertEqual("e4", sq_name(board.last_move.to))
        self.assertEqual((SoundEvent.MOVE,), SoundEventPolicy.for_move(MoveSoundFacts()))

        analysis.invalidate(board.fen())
        self.assertFalse(analysis.analyze(board.fen(), multipv=5, depth=16).stale)
        self.assertEqual(e4_fen, engine.analysis_fens[-1])

        self.assertEqual("e5", board.push_text("e5"))
        e5_fen = board.fen()
        analysis.invalidate(e5_fen)
        self.assertFalse(analysis.analyze(e5_fen).stale)
        self.assertEqual(e5_fen, engine.analysis_fens[-1])

        # Undo must expose the last move of the position we returned to (e4),
        # not erase last-move state merely because restoration uses FEN.
        self.assertEqual("e5", board.undo())
        self.assertEqual(e4_fen, board.fen())
        self.assertIsNotNone(board.last_move)
        self.assertEqual(("e2", "e4"), (sq_name(board.last_move.frm), sq_name(board.last_move.to)))
        analysis.invalidate(board.fen())
        self.assertFalse(analysis.analyze(board.fen()).stale)
        self.assertEqual(e4_fen, engine.analysis_fens[-1])

        # Redo must restore both canonical FEN and the redone move identity.
        self.assertEqual("e5", board.redo())
        self.assertEqual(e5_fen, board.fen())
        self.assertIsNotNone(board.last_move)
        self.assertEqual(("e7", "e5"), (sq_name(board.last_move.frm), sq_name(board.last_move.to)))
        analysis.invalidate(board.fen())
        self.assertFalse(analysis.analyze(board.fen()).stale)
        self.assertEqual(e5_fen, engine.analysis_fens[-1])

        before = (board.fen(), board.turn, tuple(board.undo_stack), tuple(board.redo_stack), board.last_move)
        invalid = parse_move_entry("e9")
        with self.assertRaises(ValueError):
            board.push_text(invalid.move_text)
        self.assertEqual(before, (board.fen(), board.turn, tuple(board.undo_stack), tuple(board.redo_stack), board.last_move))
        self.assertEqual((SoundEvent.ILLEGAL,), SoundEventPolicy.for_move(MoveSoundFacts(legal=False)))

        invalid_fen = "4k3/8/8/8/8/8/4K3/8 b K - 0 1"
        with self.assertRaises(ValueError):
            board.set_fen(invalid_fen)
        self.assertEqual(before, (board.fen(), board.turn, tuple(board.undo_stack), tuple(board.redo_stack), board.last_move))

        edited = PositionState.from_fen(board.fen()).with_piece("a2", None).with_piece("a3", "P")
        self.assertEqual((), edited.validate_playable())
        board.set_fen(edited.to_fen())
        self.assertEqual(edited.to_fen(), board.fen())
        self.assertIsNone(board.last_move)
        self.assertEqual([], board.undo_stack)
        self.assertEqual([], board.redo_stack)
        analysis.invalidate(board.fen())
        self.assertFalse(analysis.analyze(board.fen()).stale)
        self.assertEqual(board.fen(), engine.analysis_fens[-1])

        analysis.close()
        analysis.close()
        self.assertEqual(1, engine.closed)

    def test_stale_process_generation_cannot_satisfy_ready_or_bestmove(self) -> None:
        engine = _GenerationScriptedUCI(generation=7)
        engine.q.put((6, "readyok"))
        engine.q.put((7, "readyok"))
        self.assertEqual("readyok", engine._wait("readyok", 0.2, generation=7))

        engine.q.put((6, "bestmove a2a3"))
        engine.q.put((7, "readyok"))
        engine.q.put((7, "bestmove g1f3"))
        self.assertEqual("g1f3", engine.best_move("fen", skill_level=10, movetime_ms=50))

    def test_stale_process_generation_cannot_pollute_multipv_analysis(self) -> None:
        engine = _GenerationScriptedUCI(generation=3)
        engine.q.put((2, "readyok"))
        engine.q.put((2, "info depth 99 multipv 1 score mate 1 pv a2a3"))
        engine.q.put((2, "bestmove a2a3"))
        engine.q.put((3, "readyok"))
        engine.q.put((3, "info depth 18 multipv 1 score cp 34 pv e2e4 e7e5"))
        engine.q.put((3, "info depth 17 multipv 2 score cp 12 pv d2d4 d7d5"))
        engine.q.put((3, "bestmove e2e4"))

        lines = engine.analyze("fen", multipv=2, depth=18)
        self.assertEqual(2, len(lines))
        self.assertEqual((18, "cp", 34, ("e2e4", "e7e5")), (
            lines[0].depth, lines[0].score_kind, lines[0].score_value, lines[0].pv
        ))
        self.assertEqual((17, "cp", 12, ("d2d4", "d7d5")), (
            lines[1].depth, lines[1].score_kind, lines[1].score_value, lines[1].pv
        ))


if __name__ == "__main__":
    unittest.main()
