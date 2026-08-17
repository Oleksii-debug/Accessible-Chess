from __future__ import annotations

import unittest

from acs.analysis_service import AnalysisService
from acs.chesscore import Board
from acs.engine_ports import RawAnalysisLine
from acs.move_entry import MoveEntryKind, parse_move_entry
from acs.position_editor import PositionState, standard_position


class _RecordingEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []
        self.close_calls = 0

    def analyze(self, fen: str, multipv: int = 5, depth: int = 16):
        self.calls.append((fen, multipv, depth))
        return (RawAnalysisLine(depth, "cp", 17, ("e7e5", "g1f3")),)

    def close(self) -> None:
        self.close_calls += 1


class Stage1EditorFenCanonicalizationTests(unittest.TestCase):
    def test_complete_stage1_flow_keeps_editor_fen_canonical(self) -> None:
        engine = _RecordingEngine()
        analysis = AnalysisService(lambda: engine)
        board = Board()
        start_fen = board.fen()

        intent = parse_move_entry("e4")
        self.assertEqual(intent.kind, MoveEntryKind.CHESS_MOVE)
        self.assertEqual(board.push_text(intent.move_text), "e4")
        e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        self.assertEqual(board.fen(), e4_fen)
        self.assertEqual(board.turn, "b")
        self.assertEqual(len(board.undo_stack), 1)
        self.assertEqual(board.redo_stack, [])
        self.assertEqual(analysis.analyze(board.fen()).fen, e4_fen)
        self.assertEqual(engine.calls[-1][0], e4_fen)

        self.assertEqual(board.undo(), "e4")
        self.assertEqual(board.fen(), start_fen)
        analysis.invalidate(board.fen())
        self.assertEqual(analysis.analyze(board.fen()).fen, start_fen)

        self.assertEqual(board.redo(), "e4")
        self.assertEqual(board.fen(), e4_fen)
        analysis.invalidate(board.fen())
        self.assertEqual(analysis.analyze(board.fen()).fen, e4_fen)

        before_invalid = (
            board.fen(),
            board.turn,
            tuple(board.undo_stack),
            tuple(board.redo_stack),
            board.last_move,
        )
        invalid = parse_move_entry("e9")
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

        base = PositionState.from_fen("4k3/8/8/8/4P3/8/8/4K3 b - e3 0 1")
        editor = PositionState(
            base.pieces,
            turn="b",
            castling=" - ",
            en_passant=" E3 ",
            halfmove=0,
            fullmove=1,
        )
        self.assertEqual(editor.castling, "-")
        self.assertEqual(editor.en_passant, "e3")
        self.assertEqual(editor.validate_playable(), ())
        self.assertEqual(editor.to_fen(), "4k3/8/8/8/4P3/8/8/4K3 b - e3 0 1")

        board.set_fen(editor.to_fen())
        self.assertEqual(board.fen(), editor.to_fen())
        self.assertEqual(board.turn, "b")
        self.assertEqual(board.undo_stack, [])
        self.assertEqual(board.redo_stack, [])
        self.assertIsNone(board.last_move)
        analysis.invalidate(board.fen())
        edited = analysis.analyze(board.fen(), multipv=5, depth=12)
        self.assertFalse(edited.stale)
        self.assertEqual(engine.calls[-1], (editor.to_fen(), 5, 12))

        analysis.close()
        analysis.close()
        self.assertEqual(engine.close_calls, 1)
        self.assertEqual(analysis.analyze(board.fen()).error, AnalysisService.CLOSED_ERROR)

    def test_editor_metadata_is_canonical_before_serialization(self) -> None:
        standard = standard_position()
        reordered = PositionState(
            standard.pieces,
            turn="w",
            castling=" qK ",
            en_passant="-",
            halfmove=0,
            fullmove=1,
        )
        self.assertEqual(reordered.castling, "Kq")
        self.assertEqual(reordered.to_fen().split()[2], "Kq")
        Board(reordered.to_fen())

        ep_base = PositionState.from_fen("4k3/8/8/8/4P3/8/8/4K3 b - e3 0 1")
        normalized = PositionState(
            ep_base.pieces,
            turn="b",
            en_passant=" E3 ",
        )
        self.assertEqual(normalized.en_passant, "e3")
        self.assertEqual(normalized.to_fen().split(), [
            "4k3/8/8/8/4P3/8/8/4K3", "b", "-", "e3", "0", "1"
        ])
        self.assertEqual(normalized.validate_playable(), ())
        Board(normalized.to_fen())


if __name__ == "__main__":
    unittest.main()
