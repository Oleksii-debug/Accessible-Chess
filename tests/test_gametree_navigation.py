import unittest

from acs.gametree import MAX_VARIATION_DEPTH, MoveNode, VariationLine, parse_games
from acs.gametree_navigation import (
    BranchReturnContext,
    GameTreeCursor,
    GameTreeCursorError,
    GameTreeNavigationCode,
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

1. e4 e5 (1... c5 2. Nf3 (2... d6 3. d4) 2... Nc6)
2. Nf3 Nc6 (2... Nf6) 3. Bb5 *
'''


class GameTreeNavigationTests(unittest.TestCase):
    def setUp(self):
        self.game = parse_games(PGN)[0]

    def test_exact_nested_path_resolves_without_flattening(self):
        sicilian = (VariationStep(1, 0),)
        nested = sicilian + (VariationStep(1, 0),)

        self.assertEqual(
            [move.san for move in resolve_line(self.game, sicilian).moves],
            ['c5', 'Nf3', 'Nc6'],
        )
        self.assertEqual(
            [move.san for move in resolve_line(self.game, nested).moves],
            ['d6', 'd4'],
        )
        self.assertEqual(resolve_move(self.game, MoveAddress(nested, 1)).san, 'd4')

    def test_cursor_enters_nested_branch_and_restores_exact_parent_context(self):
        cursor = advance(self.game, advance(self.game, GameTreeCursor()))
        branch = enter_variation(self.game, cursor)
        self.assertEqual(current_move(self.game, branch).san, 'c5')

        branch = advance(self.game, advance(self.game, branch))
        nested = enter_variation(self.game, branch)
        nested = advance(self.game, advance(self.game, nested))
        self.assertIsNone(current_move(self.game, nested))

        resumed_branch = leave_variation(self.game, nested)
        self.assertEqual(
            resumed_branch,
            GameTreeCursor((VariationStep(1, 0),), 2),
        )
        self.assertEqual(current_move(self.game, resumed_branch).san, 'Nc6')
        resumed_root = leave_variation(self.game, resumed_branch)
        self.assertEqual(resumed_root, GameTreeCursor((), 2))
        self.assertEqual(current_move(self.game, resumed_root).san, 'Nf3')

    def test_branch_context_and_final_owner_return_are_exact(self):
        context = branch_context(self.game, (), 3, 0)
        self.assertEqual(
            context,
            BranchReturnContext((), (VariationStep(3, 0),), 3, 0, 4),
        )
        branch = enter_variation(self.game, GameTreeCursor((), 4))
        branch = advance(self.game, branch)
        resumed = leave_variation(self.game, branch)
        self.assertEqual(resumed, GameTreeCursor((), 4))
        self.assertEqual(current_move(self.game, resumed).san, 'Bb5')

    def test_preorder_addresses_are_unique_deterministic_and_complete(self):
        addresses = tuple(iter_move_addresses(self.game))
        sans = tuple(resolve_move(self.game, address).san for address in addresses)
        self.assertEqual(
            sans,
            ('e4', 'e5', 'c5', 'Nf3', 'd6', 'd4', 'Nc6', 'Nf3', 'Nc6', 'Nf6', 'Bb5'),
        )
        self.assertEqual(len(addresses), len(set(addresses)))
        self.assertEqual(addresses, tuple(iter_move_addresses(self.game)))

    def test_invalid_paths_and_transitions_have_stable_codes(self):
        cases = (
            lambda: resolve_line(self.game, (VariationStep(99, 0),)),
            lambda: resolve_line(self.game, (VariationStep(0, 99),)),
            lambda: resolve_move(self.game, MoveAddress((), 99)),
            lambda: branch_context(self.game, (), 0, 0),
        )
        for operation in cases:
            with self.subTest(operation=operation):
                with self.assertRaises(GameTreePathError) as blocked:
                    operation()
                self.assertEqual(blocked.exception.code, GameTreeNavigationCode.INVALID_PATH)

        transitions = (
            lambda: enter_variation(self.game, GameTreeCursor()),
            lambda: leave_variation(self.game, GameTreeCursor()),
            lambda: advance(self.game, GameTreeCursor((), len(self.game.line.moves))),
            lambda: validate_cursor(
                self.game, GameTreeCursor((), len(self.game.line.moves) + 1)
            ),
        )
        for operation in transitions:
            with self.subTest(operation=operation):
                with self.assertRaises(GameTreeCursorError) as blocked:
                    operation()
                self.assertEqual(blocked.exception.code, GameTreeNavigationCode.INVALID_CURSOR)

    def test_exact_scalar_and_tuple_contracts_reject_bool_or_coercion(self):
        constructors = (
            lambda: VariationStep(True, 0),
            lambda: VariationStep(0, 1.0),
            lambda: MoveAddress([], 0),
            lambda: MoveAddress((), '0'),
            lambda: GameTreeCursor((), False),
        )
        for constructor in constructors:
            with self.subTest(constructor=constructor):
                with self.assertRaises((TypeError, ValueError)):
                    constructor()
        with self.assertRaises(GameTreePathError):
            branch_context(self.game, (), True, 0)
        with self.assertRaises(GameTreeCursorError):
            enter_variation(self.game, GameTreeCursor((), 2), True)

    def test_navigation_is_non_mutating_and_round_trip_neutral(self):
        from acs.gametree import serialize_game

        before = serialize_game(self.game)
        for address in iter_move_addresses(self.game):
            resolve_move(self.game, address)
        cursor = enter_variation(
            self.game,
            advance(self.game, advance(self.game, GameTreeCursor())),
        )
        leave_variation(self.game, cursor)
        self.assertEqual(serialize_game(self.game), before)

    def test_cycle_reuse_and_depth_limits_fail_before_unbounded_traversal(self):
        cycle = VariationLine(moves=[MoveNode('e4')])
        cycle.moves[0].variations.append(cycle)
        self.game.line = cycle
        with self.assertRaises(GameTreePathError) as blocked:
            tuple(iter_move_addresses(self.game))
        self.assertEqual(blocked.exception.code, GameTreeNavigationCode.GRAPH_CYCLE)

        shared = VariationLine(moves=[MoveNode('d4')])
        self.game.line = VariationLine(
            moves=[MoveNode('e4', variations=[shared, shared])]
        )
        with self.assertRaises(GameTreePathError) as blocked:
            tuple(iter_move_addresses(self.game))
        self.assertEqual(blocked.exception.code, GameTreeNavigationCode.GRAPH_REUSE)

        root = VariationLine(moves=[MoveNode('m0')])
        line = root
        for depth in range(MAX_VARIATION_DEPTH + 1):
            child = VariationLine(moves=[MoveNode(f'm{depth + 1}')])
            line.moves[0].variations.append(child)
            line = child
        self.game.line = root
        with self.assertRaises(GameTreePathError) as blocked:
            tuple(iter_move_addresses(self.game))
        self.assertEqual(
            blocked.exception.code,
            GameTreeNavigationCode.GRAPH_DEPTH_LIMIT,
        )


if __name__ == '__main__':
    unittest.main()
