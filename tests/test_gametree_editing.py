import unittest

from acs.game_identity import same_game_record
from acs.gametree import (
    MoveNode,
    PgnRecoveryCode,
    PgnRecoveryIssue,
    VariationLine,
    parse_games,
    serialize_game,
)
from acs.gametree_editing import (
    GameTreeEditCode,
    GameTreeEditError,
    GameTreeEditOperation,
    delete_variation,
    promote_variation,
    reorder_variation,
    variation_edit_target,
)
from acs.gametree_navigation import (
    GameTreeCursor,
    VariationStep,
    resolve_line,
    validate_cursor,
)


PGN = '''[Event "Edit tree"]
[Result "*"]

{root} 1. e4 $1 e5
(1... c5 (1... g6 2. d4) 2. Nf3 (2. Nc3 d6) 2... Nc6 {sicilian})
(1... e6 2. d4 d5)
(1... d5 2. exd5)
2. Nf3 Nc6 3. Bb5 *
'''


def first_sans(game):
    return [variation.moves[0].san for variation in game.line.moves[1].variations]


class GameTreeEditingTests(unittest.TestCase):
    def setUp(self):
        self.game = parse_games(PGN)[0]
        self.before = serialize_game(self.game)

    def target(self, variation_index=0):
        return variation_edit_target(self.game, (), 1, variation_index)

    def assert_source_unchanged(self):
        self.assertEqual(serialize_game(self.game), self.before)
        self.assertEqual(first_sans(self.game), ['c5', 'e6', 'd5'])

    def test_reorder_is_copy_on_write_and_remaps_every_source_cursor(self):
        result = reorder_variation(self.game, self.target(2), 0)

        self.assertEqual(result.operation, GameTreeEditOperation.REORDER_VARIATION)
        self.assertEqual(first_sans(result.game), ['d5', 'c5', 'e6'])
        self.assert_source_unchanged()
        self.assertTrue(result.cursor_remap)
        for entry in result.cursor_remap:
            self.assertIsNotNone(entry.after)
            validate_cursor(result.game, entry.after)

        old_nested = GameTreeCursor(
            (VariationStep(1, 0), VariationStep(1, 0)),
            1,
        )
        self.assertEqual(
            result.remap_cursor(old_nested),
            GameTreeCursor(
                (VariationStep(1, 1), VariationStep(1, 0)),
                1,
            ),
        )
        reparsed = parse_games(serialize_game(result.game))[0]
        self.assertTrue(same_game_record(result.game, reparsed))

    def test_delete_maps_only_removed_subtree_context_to_none(self):
        result = delete_variation(self.game, self.target(1))

        self.assertEqual(result.operation, GameTreeEditOperation.DELETE_VARIATION)
        self.assertEqual(first_sans(result.game), ['c5', 'd5'])
        self.assertIsNone(
            result.remap_cursor(GameTreeCursor((VariationStep(1, 1),), 1))
        )
        self.assertEqual(
            result.remap_cursor(GameTreeCursor((VariationStep(1, 2),), 1)),
            GameTreeCursor((VariationStep(1, 1),), 1),
        )
        self.assertEqual(
            result.remap_cursor(GameTreeCursor((), 3)),
            GameTreeCursor((), 3),
        )
        self.assert_source_unchanged()

    def test_promote_swaps_mainline_and_preserves_siblings_nested_lines_and_context(self):
        result = promote_variation(self.game, self.target(0))
        edited = result.game

        self.assertEqual(result.operation, GameTreeEditOperation.PROMOTE_VARIATION)
        self.assertEqual(
            [move.san for move in edited.line.moves],
            ['e4', 'c5', 'Nf3', 'Nc6'],
        )
        promoted_owner = edited.line.moves[1]
        self.assertEqual(
            [line.moves[0].san for line in promoted_owner.variations],
            ['e5', 'e6', 'd5', 'g6'],
        )
        self.assertEqual(
            [move.san for move in promoted_owner.variations[0].moves],
            ['e5', 'Nf3', 'Nc6', 'Bb5'],
        )
        self.assertEqual(
            [move.san for move in resolve_line(
                edited, (VariationStep(2, 0),)
            ).moves],
            ['Nc3', 'd6'],
        )

        self.assertEqual(
            result.remap_cursor(GameTreeCursor((VariationStep(1, 0),), 2)),
            GameTreeCursor((), 3),
        )
        self.assertEqual(
            result.remap_cursor(GameTreeCursor((), 3)),
            GameTreeCursor((VariationStep(1, 0),), 2),
        )
        self.assertEqual(
            result.remap_cursor(
                GameTreeCursor(
                    (VariationStep(1, 0), VariationStep(1, 0)),
                    1,
                )
            ),
            GameTreeCursor((VariationStep(2, 0),), 1),
        )
        self.assertEqual(
            result.remap_cursor(GameTreeCursor((VariationStep(1, 2),), 1)),
            GameTreeCursor((VariationStep(1, 2),), 1),
        )
        for entry in result.cursor_remap:
            if entry.after is not None:
                validate_cursor(edited, entry.after)
        self.assertIn('$1', serialize_game(edited))
        self.assertIn('{sicilian}', serialize_game(edited))
        self.assert_source_unchanged()
        reparsed = parse_games(serialize_game(edited))[0]
        self.assertTrue(same_game_record(edited, reparsed))

    def test_stale_revision_and_invalid_order_fail_without_partial_edit(self):
        target = self.target(0)
        self.game.tags['Event'] = 'Changed after targeting'
        changed = serialize_game(self.game)

        with self.assertRaises(GameTreeEditError) as stale:
            delete_variation(self.game, target)
        self.assertEqual(stale.exception.code, GameTreeEditCode.STALE_REVISION)
        self.assertEqual(serialize_game(self.game), changed)

        fresh = variation_edit_target(self.game, (), 1, 0)
        for index in (True, -1, 3, 1.5, '1'):
            with self.subTest(index=index):
                before = serialize_game(self.game)
                with self.assertRaises(GameTreeEditError) as blocked:
                    reorder_variation(self.game, fresh, index)
                self.assertEqual(blocked.exception.code, GameTreeEditCode.INVALID_ORDER)
                self.assertEqual(serialize_game(self.game), before)

    def test_empty_promotion_and_unknown_cursor_fail_with_stable_codes(self):
        self.game.line.moves[1].variations.append(VariationLine())
        target = variation_edit_target(self.game, (), 1, 3)

        with self.assertRaises(GameTreeEditError) as blocked:
            promote_variation(self.game, target)
        self.assertEqual(blocked.exception.code, GameTreeEditCode.EMPTY_VARIATION)

        result = delete_variation(self.game, variation_edit_target(self.game, (), 1, 0))
        with self.assertRaises(GameTreeEditError) as missing:
            result.remap_cursor(GameTreeCursor((), 999))
        self.assertEqual(
            missing.exception.code,
            GameTreeEditCode.CURSOR_NOT_IN_SOURCE,
        )

    def test_warning_and_recovery_evidence_survives_copy_on_write_edit(self):
        issue = PgnRecoveryIssue(
            PgnRecoveryCode.UNKNOWN_TOKEN,
            'preserved external recovery evidence',
        )
        self.game.warnings.append('preserved warning')
        self.game.recovery_issues.append(issue)

        result = reorder_variation(self.game, self.target(1), 0)

        self.assertEqual(result.game.warnings, ['preserved warning'])
        self.assertEqual(result.game.recovery_issues, [issue])
        self.assertIsNot(result.game.warnings, self.game.warnings)
        self.assertIsNot(result.game.recovery_issues, self.game.recovery_issues)

    def test_cycle_and_move_reuse_are_rejected_before_copying(self):
        cycle = VariationLine(moves=[MoveNode('e4')])
        cycle.moves[0].variations.append(cycle)
        self.game.line = cycle
        with self.assertRaises(GameTreeEditError) as blocked:
            variation_edit_target(self.game, (), 0, 0)
        self.assertEqual(blocked.exception.code, GameTreeEditCode.GRAPH_CYCLE)

        shared = MoveNode('d4')
        child = VariationLine(moves=[shared])
        shared.variations.append(child)
        self.game.line = VariationLine(moves=[shared])
        with self.assertRaises(GameTreeEditError) as blocked:
            variation_edit_target(self.game, (), 0, 0)
        self.assertEqual(blocked.exception.code, GameTreeEditCode.GRAPH_REUSE)

    def test_reorder_permutations_keep_cursor_remap_total_and_deterministic(self):
        for source_index in range(3):
            for destination_index in range(3):
                with self.subTest(source=source_index, destination=destination_index):
                    first = reorder_variation(
                        self.game,
                        self.target(source_index),
                        destination_index,
                    )
                    second = reorder_variation(
                        self.game,
                        self.target(source_index),
                        destination_index,
                    )
                    self.assertEqual(
                        serialize_game(first.game),
                        serialize_game(second.game),
                    )
                    self.assertEqual(first.cursor_remap, second.cursor_remap)
                    self.assertTrue(all(
                        entry.after is not None for entry in first.cursor_remap
                    ))


if __name__ == '__main__':
    unittest.main()
