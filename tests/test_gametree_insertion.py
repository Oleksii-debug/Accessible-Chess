import unittest

from acs.game_identity import same_game_record
from acs.gametree import MoveNode, VariationLine, parse_games, serialize_game
from acs.gametree_insertion import (
    VariationInsertCode,
    VariationInsertError,
    add_variation,
    variation_insert_target,
)
from acs.gametree_navigation import GameTreeCursor, VariationStep, resolve_line, validate_cursor


PGN = '''[Event "Insert tree"]
[Result "*"]

1. e4 e5
(1... c5 (1... g6 2. d4) 2. Nf3)
(1... e6 2. d4 d5)
2. Nf3 Nc6 *
'''


class GameTreeInsertionTests(unittest.TestCase):
    def setUp(self):
        self.game = parse_games(PGN)[0]
        self.before = serialize_game(self.game)

    def test_append_is_copy_on_write_and_round_trip_stable(self):
        proposed = VariationLine(
            moves=[MoveNode('d5'), MoveNode('exd5')],
            result='*',
        )
        target = variation_insert_target(self.game, (), 1)
        result = add_variation(self.game, target, proposed)

        self.assertEqual(result.inserted_path, (VariationStep(1, 2),))
        self.assertEqual(
            [v.moves[0].san for v in result.game.line.moves[1].variations],
            ['c5', 'e6', 'd5'],
        )
        self.assertEqual(serialize_game(self.game), self.before)
        self.assertIsNot(result.game, self.game)
        self.assertIsNot(resolve_line(result.game, result.inserted_path), proposed)
        proposed.moves[0].san = 'h5'
        self.assertEqual(resolve_line(result.game, result.inserted_path).moves[0].san, 'd5')
        self.assertTrue(same_game_record(result.game, parse_games(serialize_game(result.game))[0]))

    def test_middle_insert_shifts_only_affected_sibling_paths(self):
        target = variation_insert_target(self.game, (), 1, 1)
        result = add_variation(
            self.game,
            target,
            VariationLine(moves=[MoveNode('d5'), MoveNode('exd5')]),
        )
        self.assertEqual(
            [v.moves[0].san for v in result.game.line.moves[1].variations],
            ['c5', 'd5', 'e6'],
        )
        nested_before = GameTreeCursor(
            (VariationStep(1, 0), VariationStep(0, 0)),
            1,
        )
        self.assertEqual(result.remap_cursor(nested_before), nested_before)
        shifted = GameTreeCursor((VariationStep(1, 1),), 2)
        self.assertEqual(
            result.remap_cursor(shifted),
            GameTreeCursor((VariationStep(1, 2),), 2),
        )
        self.assertEqual(
            result.remap_cursor(GameTreeCursor((), 3)),
            GameTreeCursor((), 3),
        )
        for entry in result.cursor_remap:
            validate_cursor(result.game, entry.after)

    def test_stale_target_fails_without_partial_mutation(self):
        target = variation_insert_target(self.game, (), 1)
        self.game.tags['Event'] = 'changed'
        changed = serialize_game(self.game)
        with self.assertRaises(VariationInsertError) as blocked:
            add_variation(
                self.game,
                target,
                VariationLine(moves=[MoveNode('d5')]),
            )
        self.assertEqual(blocked.exception.code, VariationInsertCode.STALE_REVISION)
        self.assertEqual(serialize_game(self.game), changed)

    def test_invalid_target_order_and_empty_variation_fail_closed(self):
        for insert_index in (True, -1, 3, 1.5, '1'):
            with self.subTest(insert_index=insert_index):
                with self.assertRaises(VariationInsertError):
                    variation_insert_target(self.game, (), 1, insert_index)
                self.assertEqual(serialize_game(self.game), self.before)
        target = variation_insert_target(self.game, (), 1)
        with self.assertRaises(VariationInsertError) as blocked:
            add_variation(self.game, target, VariationLine())
        self.assertEqual(blocked.exception.code, VariationInsertCode.EMPTY_VARIATION)
        self.assertEqual(serialize_game(self.game), self.before)

    def test_proposed_cycle_and_move_reuse_are_rejected(self):
        cycle = VariationLine(moves=[MoveNode('d5')])
        cycle.moves[0].variations.append(cycle)
        target = variation_insert_target(self.game, (), 1)
        with self.assertRaises(VariationInsertError) as blocked:
            add_variation(self.game, target, cycle)
        self.assertEqual(blocked.exception.code, VariationInsertCode.GRAPH_REUSE)
        self.assertEqual(serialize_game(self.game), self.before)

        shared_move = MoveNode('d5')
        reused = VariationLine(moves=[shared_move, shared_move])
        with self.assertRaises(VariationInsertError) as blocked:
            add_variation(self.game, target, reused)
        self.assertEqual(blocked.exception.code, VariationInsertCode.GRAPH_REUSE)
        self.assertEqual(serialize_game(self.game), self.before)

    def test_source_subtree_alias_is_rejected_instead_of_silently_duplicated(self):
        existing = self.game.line.moves[1].variations[0]
        target = variation_insert_target(self.game, (), 1)
        with self.assertRaises(VariationInsertError) as blocked:
            add_variation(self.game, target, existing)
        self.assertEqual(blocked.exception.code, VariationInsertCode.GRAPH_REUSE)
        self.assertEqual(serialize_game(self.game), self.before)


if __name__ == '__main__':
    unittest.main()
