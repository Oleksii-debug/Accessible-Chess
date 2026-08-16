import unittest

from acs.gametree import parse_games
from acs.gametree_navigation import (
    GameTreeCursor,
    GameTreeCursorError,
    GameTreePathError,
    MoveAddress,
    VariationStep,
    advance,
    branch_context,
    current_move,
    enter_variation,
    iter_move_addresses,
    leave_variation,
    resolve_line,
    resolve_move,
    validate_cursor,
)


PGN = '''[Event "Branches"]
[Result "*"]

1. e4 e5 (1... c5 2. Nf3 (2... d6 3. d4) 2... Nc6) 2. Nf3 Nc6 (2... Nf6) 3. Bb5 *
'''


class GameTreeNavigationTests(unittest.TestCase):
    def setUp(self):
        self.game = parse_games(PGN)[0]

    def test_exact_nested_path_resolves_without_flattening(self):
        sicilian = (VariationStep(1, 0),)
        nested = sicilian + (VariationStep(1, 0),)

        self.assertEqual([m.san for m in resolve_line(self.game, sicilian).moves], ['c5', 'Nf3', 'Nc6'])
        self.assertEqual([m.san for m in resolve_line(self.game, nested).moves], ['d6', 'd4'])
        self.assertEqual(resolve_move(self.game, MoveAddress(nested, 1)).san, 'd4')

    def test_branch_context_records_exact_parent_and_resume_point(self):
        root_context = branch_context(self.game, (), 1, 0)
        self.assertEqual(root_context.parent_path, ())
        self.assertEqual(root_context.child_path, (VariationStep(1, 0),))
        self.assertEqual(root_context.branch_from_move_index, 1)
        self.assertEqual(root_context.resume_parent_move_index, 2)

        nested_context = branch_context(self.game, root_context.child_path, 1, 0)
        self.assertEqual(nested_context.parent_path, root_context.child_path)
        self.assertEqual(nested_context.resume_parent_move_index, 2)

    def test_cursor_enters_and_returns_to_exact_parent_context(self):
        cursor = GameTreeCursor()
        self.assertEqual(current_move(self.game, cursor).san, 'e4')

        cursor = advance(self.game, cursor)
        cursor = advance(self.game, cursor)
        self.assertEqual(cursor.next_move_index, 2)

        branch = enter_variation(self.game, cursor, 0)
        self.assertEqual(branch.line_path, (VariationStep(1, 0),))
        self.assertEqual(current_move(self.game, branch).san, 'c5')

        branch = advance(self.game, branch)
        branch = advance(self.game, branch)
        nested = enter_variation(self.game, branch, 0)
        self.assertEqual(current_move(self.game, nested).san, 'd6')

        nested = advance(self.game, nested)
        nested = advance(self.game, nested)
        self.assertIsNone(current_move(self.game, nested))

        resumed_branch = leave_variation(self.game, nested)
        self.assertEqual(resumed_branch.line_path, (VariationStep(1, 0),))
        self.assertEqual(resumed_branch.next_move_index, 2)
        self.assertEqual(current_move(self.game, resumed_branch).san, 'Nc6')

        resumed_root = leave_variation(self.game, resumed_branch)
        self.assertEqual(resumed_root.line_path, ())
        self.assertEqual(resumed_root.next_move_index, 2)
        self.assertEqual(current_move(self.game, resumed_root).san, 'Nf3')

    def test_return_after_final_parent_move_can_land_at_line_end(self):
        line = self.game.line
        variation_owner = 3
        self.assertEqual(line.moves[variation_owner].san, 'Nc6')
        cursor = GameTreeCursor((), variation_owner + 1)
        branch = enter_variation(self.game, cursor)
        self.assertEqual(current_move(self.game, branch).san, 'Nf6')
        branch = advance(self.game, branch)
        resumed = leave_variation(self.game, branch)
        self.assertEqual(resumed.next_move_index, variation_owner + 1)
        self.assertEqual(current_move(self.game, resumed).san, 'Bb5')

    def test_deterministic_preorder_addresses_cover_each_move_once(self):
        addresses = list(iter_move_addresses(self.game))
        sans = [resolve_move(self.game, address).san for address in addresses]
        self.assertEqual(
            sans,
            ['e4', 'e5', 'c5', 'Nf3', 'd6', 'd4', 'Nc6', 'Nf3', 'Nc6', 'Nf6', 'Bb5'],
        )
        self.assertEqual(len(addresses), len(set(addresses)))
        self.assertEqual(addresses, list(iter_move_addresses(self.game)))

    def test_invalid_paths_fail_explicitly(self):
        with self.assertRaises(GameTreePathError):
            resolve_line(self.game, (VariationStep(99, 0),))
        with self.assertRaises(GameTreePathError):
            resolve_line(self.game, (VariationStep(0, 99),))
        with self.assertRaises(GameTreePathError):
            resolve_move(self.game, MoveAddress((), 99))
        with self.assertRaises(GameTreePathError):
            branch_context(self.game, (), 0, 0)

    def test_invalid_cursor_transitions_fail_instead_of_guessing(self):
        with self.assertRaises(GameTreeCursorError):
            enter_variation(self.game, GameTreeCursor(), 0)
        with self.assertRaises(GameTreeCursorError):
            leave_variation(self.game, GameTreeCursor())
        with self.assertRaises(GameTreeCursorError):
            advance(self.game, GameTreeCursor((), len(self.game.line.moves)))
        with self.assertRaises(GameTreeCursorError):
            validate_cursor(self.game, GameTreeCursor((), len(self.game.line.moves) + 1))

    def test_navigation_never_mutates_parsed_tree_or_round_trip_content(self):
        before = [(m.san, len(m.variations)) for m in self.game.line.moves]
        addresses = list(iter_move_addresses(self.game))
        for address in addresses:
            resolve_move(self.game, address)
        cursor = GameTreeCursor()
        cursor = advance(self.game, cursor)
        cursor = advance(self.game, cursor)
        cursor = enter_variation(self.game, cursor)
        cursor = leave_variation(self.game, cursor)
        after = [(m.san, len(m.variations)) for m in self.game.line.moves]
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
