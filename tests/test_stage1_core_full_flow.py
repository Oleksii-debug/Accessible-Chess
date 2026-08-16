from __future__ import annotations

import unittest

from acs.analysis_service import AnalysisService
from acs.chesscore import Board
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


class Stage1CoreFullFlowTests(unittest.TestCase):
    """One coherent Stage-1 chess-state/engine acceptance sequence.

    Presentation delivers text and consumes snapshots; Core owns classification,
    legal mutation, exact FEN/turn/history, editor compatibility, engine-position
    invalidation/reanalysis and semantic chess events.
    """

    def test_fresh_game_e4_analysis_undo_redo_invalid_and_editor_round_trip(self) -> None:
        board = Board()
        engine = _RecordingEngine()
        analysis = AnalysisService(lambda: engine)

        start_fen = Board.START
        self.assertEqual(board.fen(), start_fen)
        self.assertEqual(board.turn, "w")
        self.assertEqual(PositionState.from_fen(start_fen).to_fen(), start_fen)

        # UI-style text submission must classify before canonical Board mutation.
        intent = parse_move_entry("e4")
        self.assertEqual(intent.kind, MoveEntryKind.CHESS_MOVE)
        self.assertEqual(intent.move_text, "e4")
        self.assertEqual(board.push_text(intent.move_text), "e4")

        e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        self.assertEqual(board.fen(), e4_fen)
        self.assertEqual(board.turn, "b")
        self.assertEqual(len(board.undo_stack), 1)
        self.assertEqual(board.undo_stack[0], (start_fen, "e4"))
        self.assertEqual(board.redo_stack, [])
        self.assertEqual(SoundEventPolicy.for_move(MoveSoundFacts()), (SoundEvent.MOVE,))

        # Every canonical position change invalidates old analysis and re-analyzes
        # the exact new FEN; the provider must never receive a presentation copy.
        analysis.invalidate(e4_fen)
        e4_result = analysis.analyze(e4_fen, multipv=5, depth=16)
        self.assertFalse(e4_result.stale)
        self.assertEqual(e4_result.fen, e4_fen)
        self.assertEqual(engine.analysis_fens[-1], e4_fen)

        editor_after_e4 = PositionState.from_fen(e4_fen)
        self.assertEqual(editor_after_e4.to_fen(), e4_fen)
        self.assertEqual(editor_after_e4.validate_playable(), ())
        self.assertEqual(Board(editor_after_e4.to_fen()).fen(), e4_fen)

        # Destructive undo and redo must preserve exact canonical snapshots and
        # force analysis onto each resulting board state.
        self.assertEqual(board.undo(), "e4")
        self.assertEqual(board.fen(), start_fen)
        self.assertEqual(board.turn, "w")
        self.assertEqual(len(board.redo_stack), 1)
        analysis.invalidate(board.fen())
        undo_result = analysis.analyze(board.fen())
        self.assertFalse(undo_result.stale)
        self.assertEqual(engine.analysis_fens[-1], start_fen)

        self.assertEqual(board.redo(), "e4")
        self.assertEqual(board.fen(), e4_fen)
        self.assertEqual(board.turn, "b")
        self.assertEqual(len(board.undo_stack), 1)
        self.assertEqual(board.redo_stack, [])
        analysis.invalidate(board.fen())
        redo_result = analysis.analyze(board.fen())
        self.assertFalse(redo_result.stale)
        self.assertEqual(engine.analysis_fens[-1], e4_fen)

        # Invalid text is atomic: no board/history/editor/analysis state may move.
        before_fen = board.fen()
        before_turn = board.turn
        before_undo = tuple(board.undo_stack)
        before_redo = tuple(board.redo_stack)
        before_last = board.last_move
        before_engine_fens = tuple(engine.analysis_fens)
        before_editor = PositionState.from_fen(before_fen)

        invalid = parse_move_entry("e9")
        self.assertEqual(invalid.kind, MoveEntryKind.CHESS_MOVE)
        with self.assertRaises(ValueError):
            board.push_text(invalid.move_text)

        self.assertEqual(board.fen(), before_fen)
        self.assertEqual(board.turn, before_turn)
        self.assertEqual(tuple(board.undo_stack), before_undo)
        self.assertEqual(tuple(board.redo_stack), before_redo)
        self.assertEqual(board.last_move, before_last)
        self.assertEqual(tuple(engine.analysis_fens), before_engine_fens)
        self.assertEqual(PositionState.from_fen(board.fen()), before_editor)
        self.assertEqual(SoundEventPolicy.for_move(MoveSoundFacts(legal=False)), (SoundEvent.ILLEGAL,))

        # Closing the owning analysis service is idempotent and closes its provider
        # exactly once, preventing an orphaned engine owner at application shutdown.
        analysis.close()
        analysis.close()
        self.assertEqual(engine.closed, 1)


if __name__ == "__main__":
    unittest.main()
