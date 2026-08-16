import unittest

from acs.game_references import (
    GameReferenceError,
    MoveRef,
    PositionRef,
    VariationRef,
    branch_context,
    child_variation,
    resolve_move,
    resolve_position,
    resolve_variation,
)
from acs.gametree import parse_games


class GameReferenceTests(unittest.TestCase):
    def setUp(self):
        self.game = parse_games(
            '[Event "Tree"]\n[Result "*"]\n\n'
            '1. e4 e5 (1... c5 2. Nf3 (2. Nc3)) 2. Nf3 Nc6 3. Bb5 *\n'
        )[0]
        self.main = VariationRef(source_index=0)

    def test_main_line_reference_resolves_without_copying_tree(self):
        line = resolve_variation(self.game, self.main)
        self.assertIs(line, self.game.line)
        self.assertEqual([move.san for move in line.moves], ['e4', 'e5', 'Nf3', 'Nc6', 'Bb5'])

    def test_child_reference_resolves_exact_attached_variation(self):
        sicilian = child_variation(self.main, move_index=1, variation_index=0)
        line = resolve_variation(self.game, sicilian)
        self.assertEqual([move.san for move in line.moves], ['c5', 'Nf3'])
        self.assertIs(line, self.game.line.moves[1].variations[0])

    def test_nested_reference_preserves_full_branch_identity(self):
        sicilian = child_variation(self.main, 1, 0)
        nested = child_variation(sicilian, 1, 0)
        self.assertEqual(len(nested.path), 2)
        self.assertEqual(resolve_move(self.game, MoveRef(nested, 0)).san, 'Nc3')

    def test_branch_context_uses_position_before_attachment_as_base(self):
        sicilian = child_variation(self.main, 1, 0)
        context = branch_context(self.game, sicilian)
        self.assertEqual(context.attached_to, MoveRef(self.main, 1))
        self.assertEqual(context.branch_base, PositionRef(self.main, 1))
        self.assertEqual(context.return_position, PositionRef(self.main, 2))
        self.assertEqual(context.resume_move, MoveRef(self.main, 2))

    def test_nested_branch_context_returns_to_exact_parent_variation(self):
        sicilian = child_variation(self.main, 1, 0)
        nested = child_variation(sicilian, 1, 0)
        context = branch_context(self.game, nested)
        self.assertEqual(context.attached_to, MoveRef(sicilian, 1))
        self.assertEqual(context.branch_base, PositionRef(sicilian, 1))
        self.assertEqual(context.return_position, PositionRef(sicilian, 2))
        self.assertIsNone(context.resume_move)

    def test_end_position_is_valid_but_past_end_is_rejected(self):
        end = PositionRef(self.main, len(self.game.line.moves))
        self.assertEqual(resolve_position(self.game, end), end)
        with self.assertRaises(GameReferenceError):
            resolve_position(self.game, PositionRef(self.main, len(self.game.line.moves) + 1))

    def test_wrong_source_index_fails_closed(self):
        with self.assertRaises(GameReferenceError):
            resolve_variation(self.game, VariationRef(source_index=1))

    def test_invalid_path_fails_closed(self):
        invalid = child_variation(self.main, move_index=0, variation_index=0)
        with self.assertRaises(GameReferenceError):
            resolve_variation(self.game, invalid)

    def test_main_line_has_no_branch_context(self):
        with self.assertRaises(GameReferenceError):
            branch_context(self.game, self.main)

    def test_negative_reference_components_are_rejected(self):
        with self.assertRaises(ValueError):
            MoveRef(self.main, -1)
        with self.assertRaises(ValueError):
            PositionRef(self.main, -1)
        with self.assertRaises(ValueError):
            child_variation(self.main, -1, 0)


if __name__ == '__main__':
    unittest.main()
