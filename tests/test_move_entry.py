import unittest

from acs.keybindings import ActionRegistry
from acs.move_entry import MoveEntryKind, parse_move_entry, parse_piece_coordinate_position


class MoveEntryTests(unittest.TestCase):
    def test_blank_input_is_explicit_empty_intent(self):
        intent = parse_move_entry("   ")
        self.assertEqual(intent.kind, MoveEntryKind.EMPTY)

    def test_default_alias_resolves_to_stable_action_id(self):
        intent = parse_move_entry("u")
        self.assertEqual(intent.kind, MoveEntryKind.ACTION)
        self.assertEqual(intent.action_id, "move.undo")

    def test_remapped_alias_is_consumed_by_router(self):
        registry = ActionRegistry()
        registry.set_alias("move.undo", "z")
        self.assertEqual(parse_move_entry("z", registry).action_id, "move.undo")
        old = parse_move_entry("u", registry)
        self.assertEqual(old.kind, MoveEntryKind.CHESS_MOVE)
        self.assertEqual(old.move_text, "u")

    def test_chess_move_text_is_not_modified(self):
        for text in ("e4", "Nf3", "O-O", "exd8=Q+"):
            with self.subTest(text=text):
                intent = parse_move_entry(text)
                self.assertEqual(intent.kind, MoveEntryKind.CHESS_MOVE)
                self.assertEqual(intent.move_text, text)

    def test_position_syntax_precedes_w_and_b_aliases(self):
        registry = ActionRegistry()
        registry.set_alias("move.white_to_move", "white")
        registry.set_alias("move.black_to_move", "black")
        intent = parse_move_entry("W: K e1 P e4 B: K e8 P e5", registry)
        self.assertEqual(intent.kind, MoveEntryKind.POSITION)
        self.assertEqual(intent.position.piece_at("e1"), "K")
        self.assertEqual(intent.position.piece_at("e4"), "P")
        self.assertEqual(intent.position.piece_at("e8"), "k")
        self.assertEqual(intent.position.piece_at("e5"), "p")

    def test_position_parser_is_case_insensitive_for_headers(self):
        state = parse_piece_coordinate_position("w: K e1 Q d1 b: K e8 q d8")
        self.assertEqual(state.piece_at("d1"), "Q")
        self.assertEqual(state.piece_at("d8"), "q")

    def test_position_parser_rejects_duplicate_square(self):
        with self.assertRaisesRegex(ValueError, "more than once"):
            parse_piece_coordinate_position("W: K e1 Q e1 B: K e8")

    def test_position_parser_requires_exactly_one_king_each(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            parse_piece_coordinate_position("W: Q d1 B: K e8")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            parse_piece_coordinate_position("W: K e1 B: K e8 K d8")

    def test_position_turn_is_explicit_and_preserved(self):
        intent = parse_move_entry("W: K e1 B: K e8", position_turn="b")
        self.assertEqual(intent.position.turn, "b")
        self.assertEqual(intent.position.to_fen(), "4k3/8/8/8/8/8/8/4K3 b - - 0 1")

    def test_incomplete_position_header_fails_as_position_not_as_command(self):
        with self.assertRaisesRegex(ValueError, "W: and B:"):
            parse_move_entry("W: K e1")


if __name__ == "__main__":
    unittest.main()
