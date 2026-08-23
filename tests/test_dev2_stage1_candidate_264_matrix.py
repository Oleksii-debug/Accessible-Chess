from __future__ import annotations

import unittest

from acs.chesscore import Board
from acs.history import PositionSnapshot, ReviewHistory
from acs.squares import normalize_square, parse_square, square_name

MATRIX_CASE_COUNT = 264


def history(plies: int = 32) -> ReviewHistory:
    result = ReviewHistory("fen-0")
    for ply in range(1, plies + 1):
        side = "w" if ply % 2 else "b"
        result.append(f"fen-{ply}", san=f"m{ply}", side=side,
                      last_move=f"{(ply + 1) // 2}{side}", context={"ply": ply})
    return result


def placement_fen(pieces: dict[str, str], turn: str, ep: str = "-") -> str:
    cells = [None] * 64
    for square, piece in pieces.items():
        cells[parse_square(square)] = piece
    ranks = []
    for rank in range(7, -1, -1):
        row, empty = "", 0
        for file_index in range(8):
            piece = cells[rank * 8 + file_index]
            if piece is None:
                empty += 1
            else:
                if empty:
                    row += str(empty)
                    empty = 0
                row += piece
        if empty:
            row += str(empty)
        ranks.append(row)
    return "/".join(ranks) + f" {turn} - {ep} 0 1"


class CandidateCore264(unittest.TestCase):
    pass


def square_roundtrip(index: int):
    def test(self):
        name = square_name(index)
        self.assertEqual(parse_square(name), index)
        self.assertEqual(parse_square(index), index)
        self.assertEqual(square_name(parse_square(name)), name)
    return test


def square_normalize(index: int):
    def test(self):
        name = square_name(index)
        decorated = f"  {name.upper()}  "
        self.assertEqual(normalize_square(decorated), name)
        self.assertEqual(parse_square(decorated), index)
    return test


for i in range(64):
    setattr(CandidateCore264, f"test_{1+i:03d}_square_roundtrip_{i:02d}", square_roundtrip(i))
    setattr(CandidateCore264, f"test_{65+i:03d}_square_normalize_{i:02d}", square_normalize(i))


def jump_case(move_number: int, side: str):
    def test(self):
        h = history(32)
        expected = 2 * move_number - 1 if side == "w" else 2 * move_number
        item = h.jump(f"{move_number}{side}")
        self.assertEqual((item.ply, item.node_id, item.snapshot.fen),
                         (expected, expected, f"fen-{expected}"))
        self.assertEqual(h.node_count, 33)
    return test


case = 129
for move_number in range(1, 17):
    for side in ("w", "b"):
        setattr(CandidateCore264, f"test_{case:03d}_history_jump_{move_number:02d}{side}", jump_case(move_number, side))
        case += 1


def node_case(node_id: int):
    def test(self):
        h = history(24)
        count = h.node_count
        item = h.select_node(node_id)
        self.assertEqual((item.node_id, item.ply, item.snapshot.fen),
                         (node_id, node_id, f"fen-{node_id}"))
        self.assertEqual(h.cursor_node_id, node_id)
        self.assertEqual(h.node_count, count)
        self.assertEqual(h.current(), item)
    return test


for node_id in range(1, 25):
    setattr(CandidateCore264, f"test_{160+node_id:03d}_history_node_{node_id:02d}", node_case(node_id))


def fen_counter_case(index: int):
    def test(self):
        turn = "w" if index % 2 == 0 else "b"
        fen = f"7k/8/8/8/8/8/8/K7 {turn} - - {index} {index+1}"
        board = Board(fen)
        self.assertEqual(board.fen(), fen)
        self.assertEqual((board.turn, board.halfmove, board.fullmove), (turn, index, index + 1))
    return test


for i in range(16):
    setattr(CandidateCore264, f"test_{185+i:03d}_fen_counter_{i:02d}", fen_counter_case(i))


INVALID_FENS = (
    "7k/8/8/8/8/8/8/K7 w - - +0 1", "7k/8/8/8/8/8/8/K7 w - - 0 +1",
    "7k/8/8/8/8/8/8/K7 w - - -1 1", "7k/8/8/8/8/8/8/K7 w - - 0 -1",
    "7k/8/8/8/8/8/8/K7 w - - 1.0 1", "7k/8/8/8/8/8/8/K7 w - - 0 1.0",
    "7k/8/8/8/8/8/8/K7 w - - 1e3 1", "7k/8/8/8/8/8/8/K7 w - - 0 1e3",
    "7k/8/8/8/8/8/8/K7 w - - ٠ 1", "7k/8/8/8/8/8/8/K7 w - - 0 ١",
    "7k/8/8/8/8/8/8/K7 w - - NaN 1", "7k/8/8/8/8/8/8/K7 w - - 0 NaN",
    "7k/8/8/8/8/8/8/K7 w - - 0x10 1", "7k/8/8/8/8/8/8/K7 w - - 0 0x10",
    "7k/8/8/8/8/8/8/K7 w - - 0 0", "7k/8/8/8/8/8/8/K7 w - - 0 1 extra",
)


def invalid_fen_case(index: int):
    def test(self):
        board = Board(); board.push_text("e4"); board.push_text("e5"); board.undo()
        before = (board.fen(), tuple(board.undo_stack), tuple(board.redo_stack), board.last_move)
        with self.assertRaises(ValueError):
            board.set_fen(INVALID_FENS[index])
        self.assertEqual((board.fen(), tuple(board.undo_stack), tuple(board.redo_stack), board.last_move), before)
    return test


for i in range(16):
    setattr(CandidateCore264, f"test_{201+i:03d}_invalid_fen_atomicity_{i:02d}", invalid_fen_case(i))


def undo_redo_case(cycles: int):
    def test(self):
        board = Board()
        for move in ("e4", "e5", "Nf3", "Nc6"):
            board.push_text(move)
        expected = (board.fen(), tuple(board.undo_stack))
        for _ in range(cycles):
            self.assertEqual(board.undo(), "Nc6")
            self.assertEqual(board.redo(), "Nc6")
            self.assertEqual((board.fen(), tuple(board.undo_stack)), expected)
            self.assertEqual(tuple(board.redo_stack), ())
    return test


for cycles in range(1, 17):
    setattr(CandidateCore264, f"test_{216+cycles:03d}_undo_redo_{cycles:02d}", undo_redo_case(cycles))


def branch_case(index: int):
    def test(self):
        h = history(6); h.select_node(2)
        origin, line, tree = h.current(), h.active_line(), h.export_tree()
        branch = (PositionSnapshot(f"branch-{index}-3", san=f"x{index}a", side="w"),
                  PositionSnapshot(f"branch-{index}-4", san=f"x{index}b", side="b"))
        inserted = h.append_branch(origin.node_id, branch)
        self.assertEqual(inserted.created_count, 2)
        self.assertEqual((h.current(), h.active_line(), h.node_count), (origin, line, len(tree.nodes) + 2))
        repeated = h.append_branch(origin.node_id, branch)
        self.assertEqual((repeated.created_count, repeated.node_ids), (0, inserted.node_ids))
        self.assertEqual((h.current(), h.active_line()), (origin, line))
        node = h.tree_nodes()[origin.node_id]
        self.assertIn(3, node.child_ids); self.assertIn(inserted.node_ids[0], node.child_ids)
        self.assertEqual(node.active_child, 3)
    return test


for i in range(16):
    setattr(CandidateCore264, f"test_{233+i:03d}_branch_preservation_{i:02d}", branch_case(i))


def valid_ep_case(file_index: int):
    def test(self):
        file_name = "abcdefgh"[file_index]; ep = f"{file_name}6"
        fen = placement_fen({"a1": "K", "h8": "k", f"{file_name}5": "p"}, "w", ep)
        board = Board(fen)
        self.assertEqual(board.fen(), fen); self.assertEqual(square_name(board.ep), ep)
    return test


def invalid_ep_case(file_index: int):
    def test(self):
        file_name = "abcdefgh"[file_index]; ep = f"{file_name}6"
        fen = placement_fen({"a1": "K", "h8": "k", f"{file_name}5": "p", f"{file_name}7": "p"}, "w", ep)
        board = Board(); before = board.fen()
        with self.assertRaises(ValueError):
            board.set_fen(fen)
        self.assertEqual(board.fen(), before); self.assertEqual(board.undo_stack, []); self.assertEqual(board.redo_stack, [])
    return test


for i in range(8):
    setattr(CandidateCore264, f"test_{249+i:03d}_valid_ep_{i}", valid_ep_case(i))
    setattr(CandidateCore264, f"test_{257+i:03d}_invalid_ep_{i}", invalid_ep_case(i))


discovered = [name for name in dir(CandidateCore264) if name.startswith("test_")]
if len(discovered) != MATRIX_CASE_COUNT:
    raise RuntimeError(f"DEV2 candidate matrix shape drift: expected {MATRIX_CASE_COUNT}, got {len(discovered)}")
