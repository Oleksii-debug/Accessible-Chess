from __future__ import annotations

import unittest

from acs.chesscore import Board
from acs.history import PositionSnapshot, ReviewHistory
from acs.squares import normalize_square, parse_square, square_name

MATRIX_CASE_COUNT = 264


def _make_history(plies: int = 32) -> ReviewHistory:
    history = ReviewHistory("fen-0")
    for ply in range(1, plies + 1):
        side = "w" if ply % 2 else "b"
        history.append(
            f"fen-{ply}", san=f"m{ply}", side=side,
            last_move=f"{(ply + 1) // 2}{side}", context={"ply": ply},
        )
    return history


def _placement_fen(pieces: dict[str, str], turn: str, ep: str = "-") -> str:
    board = [None] * 64
    for square, piece in pieces.items():
        board[parse_square(square)] = piece
    rows: list[str] = []
    for rank in range(7, -1, -1):
        row = ""
        empty = 0
        for file_index in range(8):
            piece = board[rank * 8 + file_index]
            if piece is None:
                empty += 1
            else:
                if empty:
                    row += str(empty)
                    empty = 0
                row += piece
        if empty:
            row += str(empty)
        rows.append(row)
    return "/".join(rows) + f" {turn} - {ep} 0 1"


class Dev2Stage1Candidate264Matrix(unittest.TestCase):
    pass


def _make_square_roundtrip_case(index: int):
    def test(self: Dev2Stage1Candidate264Matrix) -> None:
        name = square_name(index)
        self.assertEqual(parse_square(name), index)
        self.assertEqual(parse_square(index), index)
        self.assertEqual(square_name(parse_square(name)), name)
    return test


for _index in range(64):
    setattr(Dev2Stage1Candidate264Matrix, f"test_001_064_square_roundtrip_{_index:02d}", _make_square_roundtrip_case(_index))


def _make_square_normalization_case(index: int):
    def test(self: Dev2Stage1Candidate264Matrix) -> None:
        name = square_name(index)
        decorated = f"  {name.upper()}  "
        self.assertEqual(normalize_square(decorated), name)
        self.assertEqual(parse_square(decorated), index)
    return test


for _index in range(64):
    setattr(Dev2Stage1Candidate264Matrix, f"test_065_128_square_normalization_{_index:02d}", _make_square_normalization_case(_index))


def _make_history_jump_case(move_number: int, side: str):
    def test(self: Dev2Stage1Candidate264Matrix) -> None:
        history = _make_history(32)
        target = f"{move_number}{side}"
        expected_ply = 2 * move_number - 1 if side == "w" else 2 * move_number
        selected = history.jump(target)
        self.assertEqual(selected.ply, expected_ply)
        self.assertEqual(selected.node_id, expected_ply)
        self.assertEqual(selected.snapshot.fen, f"fen-{expected_ply}")
        self.assertEqual(history.node_count, 33)
    return test


_case = 129
for _move_number in range(1, 17):
    for _side in ("w", "b"):
        setattr(Dev2Stage1Candidate264Matrix, f"test_{_case:03d}_history_jump_{_move_number:02d}{_side}", _make_history_jump_case(_move_number, _side))
        _case += 1


def _make_history_node_case(node_id: int):
    def test(self: Dev2Stage1Candidate264Matrix) -> None:
        history = _make_history(24)
        before_count = history.node_count
        selected = history.select_node(node_id)
        self.assertEqual(selected.node_id, node_id)
        self.assertEqual(selected.ply, node_id)
        self.assertEqual(selected.snapshot.fen, f"fen-{node_id}")
        self.assertEqual(history.cursor_node_id, node_id)
        self.assertEqual(history.node_count, before_count)
        self.assertEqual(history.current(), selected)
    return test


for _node_id in range(1, 25):
    setattr(Dev2Stage1Candidate264Matrix, f"test_{160 + _node_id:03d}_history_select_node_{_node_id:02d}", _make_history_node_case(_node_id))


def _make_fen_counter_case(index: int):
    def test(self: Dev2Stage1Candidate264Matrix) -> None:
        turn = "w" if index % 2 == 0 else "b"
        halfmove = index
        fullmove = index + 1
        fen = f"7k/8/8/8/8/8/8/K7 {turn} - - {halfmove} {fullmove}"
        board = Board(fen)
        self.assertEqual(board.fen(), fen)
        self.assertEqual(board.turn, turn)
        self.assertEqual(board.halfmove, halfmove)
        self.assertEqual(board.fullmove, fullmove)
    return test


for _index in range(16):
    setattr(Dev2Stage1Candidate264Matrix, f"test_{185 + _index:03d}_fen_counter_roundtrip_{_index:02d}", _make_fen_counter_case(_index))


_INVALID_FENS = (
    "7k/8/8/8/8/8/8/K7 w - - +0 1", "7k/8/8/8/8/8/8/K7 w - - 0 +1",
    "7k/8/8/8/8/8/8/K7 w - - -1 1", "7k/8/8/8/8/8/8/K7 w - - 0 -1",
    "7k/8/8/8/8/8/8/K7 w - - 1.0 1", "7k/8/8/8/8/8/8/K7 w - - 0 1.0",
    "7k/8/8/8/8/8/8/K7 w - - 1e3 1", "7k/8/8/8/8/8/8/K7 w - - 0 1e3",
    "7k/8/8/8/8/8/8/K7 w - - ٠ 1", "7k/8/8/8/8/8/8/K7 w - - 0 ١",
    "7k/8/8/8/8/8/8/K7 w - - NaN 1", "7k/8/8/8/8/8/8/K7 w - - 0 NaN",
    "7k/8/8/8/8/8/8/K7 w - - 0x10 1", "7k/8/8/8/8/8/8/K7 w - - 0 0x10",
    "7k/8/8/8/8/8/8/K7 w - - 0 0", "7k/8/8/8/8/8/8/K7 w - - 0 1 extra",
)


def _make_invalid_fen_atomicity_case(index: int):
    def test(self: Dev2Stage1Candidate264Matrix) -> None:
        board = Board()
        board.push_text("e4")
        board.push_text("e5")
        board.undo()
        before = (board.fen(), tuple(board.undo_stack), tuple(board.redo_stack), board.last_move)
        with self.assertRaises(ValueError):
            board.set_fen(_INVALID_FENS[index])
        after = (board.fen(), tuple(board.undo_stack), tuple(board.redo_stack), board.last_move)
        self.assertEqual(after, before)
    return test


for _index in range(16):
    setattr(Dev2Stage1Candidate264Matrix, f"test_{201 + _index:03d}_invalid_fen_atomicity_{_index:02d}", _make_invalid_fen_atomicity_case(_index))


def _make_undo_redo_case(cycles: int):
    def test(self: Dev2Stage1Candidate264Matrix) -> None:
        board = Board()
        for move in ("e4", "e5", "Nf3", "Nc6"):
            board.push_text(move)
        expected_fen = board.fen()
        expected_undo = tuple(board.undo_stack)
        for _ in range(cycles):
            self.assertEqual(board.undo(), "Nc6")
            self.assertEqual(board.redo(), "Nc6")
            self.assertEqual(board.fen(), expected_fen)
            self.assertEqual(tuple(board.undo_stack), expected_undo)
            self.assertEqual(tuple(board.redo_stack), ())
    return test


for _cycles in range(1, 17):
    setattr(Dev2Stage1Candidate264Matrix, f"test_{216 + _cycles:03d}_undo_redo_cycles_{_cycles:02d}", _make_undo_redo_case(_cycles))


def _make_branch_case(case_index: int):
    def test(self: Dev2Stage1Candidate264Matrix) -> None:
        history = _make_history(6)
        history.select_node(2)
        origin = history.current()
        baseline_line = history.active_line()
        baseline_tree = history.export_tree()
        branch = (
            PositionSnapshot(f"branch-{case_index}-3", san=f"x{case_index}a", side="w"),
            PositionSnapshot(f"branch-{case_index}-4", san=f"x{case_index}b", side="b"),
        )
        inserted = history.append_branch(origin.node_id, branch)
        self.assertEqual(inserted.created_count, 2)
        self.assertEqual(history.current(), origin)
        self.assertEqual(history.active_line(), baseline_line)
        self.assertEqual(history.node_count, len(baseline_tree.nodes) + 2)
        repeated = history.append_branch(origin.node_id, branch)
        self.assertEqual(repeated.created_count, 0)
        self.assertEqual(repeated.node_ids, inserted.node_ids)
        self.assertEqual(history.current(), origin)
        self.assertEqual(history.active_line(), baseline_line)
        node = history.tree_nodes()[origin.node_id]
        self.assertIn(3, node.child_ids)
        self.assertIn(inserted.node_ids[0], node.child_ids)
        self.assertEqual(node.active_child, 3)
    return test


for _index in range(16):
    setattr(Dev2Stage1Candidate264Matrix, f"test_{233 + _index:03d}_history_branch_preservation_{_index:02d}", _make_branch_case(_index))


def _make_valid_ep_case(file_index: int):
    def test(self: Dev2Stage1Candidate264Matrix) -> None:
        file_name = "abcdefgh"[file_index]
        pieces = {"a1": "K", "h8": "k", f"{file_name}5": "p"}
        ep = f"{file_name}6"
        fen = _placement_fen(pieces, "w", ep)
        board = Board(fen)
        self.assertEqual(board.fen(), fen)
        self.assertEqual(square_name(board.ep), ep)
    return test


for _file_index in range(8):
    setattr(Dev2Stage1Candidate264Matrix, f"test_{249 + _file_index:03d}_valid_en_passant_provenance_{_file_index}", _make_valid_ep_case(_file_index))


def _make_invalid_ep_origin_case(file_index: int):
    def test(self: Dev2Stage1Candidate264Matrix) -> None:
        file_name = "abcdefgh"[file_index]
        pieces = {"a1": "K", "h8": "k", f"{file_name}5": "p", f"{file_name}7": "p"}
        ep = f"{file_name}6"
        fen = _placement_fen(pieces, "w", ep)
        baseline = Board()
        before = baseline.fen()
        with self.assertRaises(ValueError):
            baseline.set_fen(fen)
        self.assertEqual(baseline.fen(), before)
        self.assertEqual(baseline.undo_stack, [])
        self.assertEqual(baseline.redo_stack, [])
    return test


for _file_index in range(8):
    setattr(Dev2Stage1Candidate264Matrix, f"test_{257 + _file_index:03d}_invalid_en_passant_origin_{_file_index}", _make_invalid_ep_origin_case(_file_index))


def _assert_matrix_shape() -> None:
    discovered = [name for name in dir(Dev2Stage1Candidate264Matrix) if name.startswith("test_")]
    if len(discovered) != MATRIX_CASE_COUNT:
        raise RuntimeError(f"DEV2 candidate matrix shape drift: expected {MATRIX_CASE_COUNT}, got {len(discovered)}")


_assert_matrix_shape()


if __name__ == "__main__":
    unittest.main()
