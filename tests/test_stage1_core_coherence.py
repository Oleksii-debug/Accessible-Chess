from __future__ import annotations

import unittest

from acs.analysis_service import AnalysisService
from acs.chesscore import Board
from acs.engine_ports import RawAnalysisLine
from acs.move_entry import MoveEntryKind, parse_move_entry
from acs.position_editor import PositionState
from acs.sound_events import MoveSoundFacts, SoundEvent, SoundEventPolicy


class _RecordingEngine:
    def __init__(self) -> None:
        self.analyzed: list[tuple[str, int, int]] = []
        self.close_calls = 0

    def analyze(self, fen: str, multipv: int = 5, depth: int = 16):
        self.analyzed.append((fen, multipv, depth))
        return (
            RawAnalysisLine(depth, "cp", 23, ("e7e5", "g1f3")),
            RawAnalysisLine(depth, "cp", 11, ("c7c5", "g1f3")),
        )

    def close(self) -> None:
        self.close_calls += 1


class Stage1CoreCoherenceTests(unittest.TestCase):
    """One coherent Stage-1 state/engine/editor regression.

    This suite deliberately crosses the application-neutral boundaries used by
    the packaged UI: text classification, canonical Board mutation, history,
    analysis invalidation/reanalysis, editor/FEN compatibility, semantic sound
    events and owned-engine shutdown.
    """

    def test_full_stage1_state_engine_editor_sequence_is_coherent(self) -> None:
        engine = _RecordingEngine()
        analysis = AnalysisService(lambda: engine)
        board = Board()
        start_fen = board.fen()

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
        self.assertEqual(
            SoundEventPolicy.for_move(MoveSoundFacts()),
            (SoundEvent.MOVE,),
        )

        first = analysis.analyze(board.fen(), multipv=5, depth=16)
        self.assertFalse(first.stale)
        self.assertIsNone(first.error)
        self.assertEqual(first.fen, e4_fen)
        self.assertEqual(len(first.lines), 2)
        self.assertEqual(engine.analyzed[-1], (e4_fen, 5, 16))

        self.assertEqual(board.undo(), "e4")
        self.assertEqual(board.fen(), start_fen)
        analysis.invalidate(board.fen())
        undone = analysis.analyze(board.fen(), multipv=5, depth=12)
        self.assertFalse(undone.stale)
        self.assertEqual(engine.analyzed[-1], (start_fen, 5, 12))

        self.assertEqual(board.redo(), "e4")
        self.assertEqual(board.fen(), e4_fen)
        analysis.invalidate(board.fen())
        redone = analysis.analyze(board.fen(), multipv=5, depth=14)
        self.assertFalse(redone.stale)
        self.assertEqual(engine.analyzed[-1], (e4_fen, 5, 14))

        before_invalid = (
            board.fen(),
            board.turn,
            tuple(board.undo_stack),
            tuple(board.redo_stack),
            board.last_move,
        )
        invalid = parse_move_entry("e9")
        self.assertEqual(invalid.kind, MoveEntryKind.CHESS_MOVE)
        with self.assertRaises(ValueError):
            board.push_text(invalid.move_text)
        self.assertEqual(
            (
                board.fen(),
                board.turn,
                tuple(board.undo_stack),
                tuple(board.redo_stack),
                board.last_move,
            ),
            before_invalid,
        )
        self.assertEqual(
            SoundEventPolicy.for_move(MoveSoundFacts(legal=False)),
            (SoundEvent.ILLEGAL,),
        )

        editor = PositionState.from_fen(
            "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 12"
        )
        self.assertEqual(editor.validate_playable(), ())
        board.set_fen(editor.to_fen())
        self.assertEqual(board.fen(), editor.to_fen())
        self.assertEqual(board.turn, "w")
        self.assertEqual(board.undo_stack, [])
        self.assertEqual(board.redo_stack, [])
        self.assertIsNone(board.last_move)

        analysis.invalidate(board.fen())
        edited = analysis.analyze(board.fen(), multipv=5, depth=10)
        self.assertFalse(edited.stale)
        self.assertEqual(engine.analyzed[-1], (editor.to_fen(), 5, 10))

        analysis.close()
        self.assertEqual(engine.close_calls, 1)
        after_close = analysis.analyze(board.fen())
        self.assertEqual(after_close.error, AnalysisService.CLOSED_ERROR)
        self.assertEqual(engine.close_calls, 1)
        self.assertEqual(len(engine.analyzed), 4)

    def test_editor_playability_matches_canonical_board_for_adjacent_kings_and_ep(self) -> None:
        adjacent = PositionState.from_fen("8/8/8/8/8/8/4k3/4K3 w - - 0 1")
        self.assertIn("kings must not be adjacent", adjacent.validate_playable())
        with self.assertRaises(ValueError):
            Board(adjacent.to_fen())

        bad_ep_cases = (
            (
                "4k3/8/8/8/8/4N3/4P3/4K3 b - e3 0 1",
                "en-passant target square must be empty",
            ),
            (
                "4k3/8/8/8/8/8/8/4K3 b - e3 0 1",
                "en-passant target lacks the pawn from the completed double push",
            ),
            (
                "4k3/8/8/8/4P3/8/4P3/4K3 b - e3 0 1",
                "en-passant double-push origin square must be empty",
            ),
        )
        for fen, problem in bad_ep_cases:
            with self.subTest(fen=fen):
                position = PositionState.from_fen(fen)
                self.assertIn(problem, position.validate_playable())
                with self.assertRaises(ValueError):
                    Board(position.to_fen())

    def test_typed_position_command_fails_before_canonical_mutation_when_not_playable(self) -> None:
        with self.assertRaisesRegex(ValueError, "kings must not be adjacent"):
            parse_move_entry("W: K e1 B: K e2")

        with self.assertRaisesRegex(ValueError, "pawn on invalid first rank"):
            parse_move_entry("W: K e1 P a1 B: K e8")

        valid = parse_move_entry("W: K e1 Q d1 P e4 B: K e8 P e5")
        self.assertEqual(valid.kind, MoveEntryKind.POSITION)
        self.assertIsNotNone(valid.position)
        self.assertEqual(valid.position.validate_playable(), ())
        board = Board(valid.position.to_fen())
        self.assertEqual(board.turn, "w")
        self.assertEqual(board.fen(), valid.position.to_fen())


if __name__ == "__main__":
    unittest.main()
