import unittest
from unittest import mock

import acs.gametree as gametree
from acs.gametree import (
    GameTreeContractError,
    GameTreeErrorCode,
    GameTreeSerializationError,
    MoveNode,
    VariationLine,
    parse_games,
    serialize_game,
    serialize_games,
)


BASE = '[Event "Bounded"]\n[Result "*"]\n\n1. e4 e5 2. Nf3 *\n'


class GameTreeExportValidationTests(unittest.TestCase):
    def game(self):
        return parse_games(BASE)[0]

    def assert_serialization_code(self, game, code):
        with self.assertRaises(GameTreeSerializationError) as caught:
            serialize_game(game)
        self.assertEqual(caught.exception.code, code)

    def test_mutated_empty_or_structural_san_fails_instead_of_disappearing(self):
        for invalid in ('', '   ', '1-0', '2...', '$4', 'e4 e5', 'e4)'):
            game = self.game()
            game.line.moves[0].san = invalid
            with self.subTest(san=invalid):
                self.assert_serialization_code(game, GameTreeErrorCode.INVALID_MOVE)

    def test_mutated_tag_nag_move_number_and_containers_fail_with_stable_codes(self):
        game = self.game()
        game.tags['Bad Tag'] = 'value'
        self.assert_serialization_code(game, GameTreeErrorCode.INVALID_TAG)

        game = self.game()
        game.tags['Event'] = 'line1\nline2'
        self.assert_serialization_code(game, GameTreeErrorCode.INVALID_TAG)

        game = self.game()
        game.line.moves[0].nags.append('not-a-nag')
        self.assert_serialization_code(game, GameTreeErrorCode.INVALID_NAG)

        game = self.game()
        game.line.moves[0].move_number = 1
        self.assert_serialization_code(game, GameTreeErrorCode.INVALID_MOVE)

        game = self.game()
        game.line.moves = tuple(game.line.moves)
        self.assert_serialization_code(game, GameTreeErrorCode.INVALID_CONTAINER)

    def test_cycle_and_shared_graph_references_are_rejected(self):
        game = self.game()
        game.line.moves[0].variations.append(game.line)
        self.assert_serialization_code(game, GameTreeErrorCode.GRAPH_CYCLE)

        game = self.game()
        shared = VariationLine(moves=[MoveNode('c5')])
        game.line.moves[0].variations.append(shared)
        game.line.moves[1].variations.append(shared)
        self.assert_serialization_code(game, GameTreeErrorCode.GRAPH_REUSE)

    def test_export_depth_and_node_limits_are_explicit(self):
        game = self.game()
        child = VariationLine(moves=[MoveNode('c5')])
        grandchild = VariationLine(moves=[MoveNode('Nf3')])
        child.moves[0].variations.append(grandchild)
        game.line.moves[0].variations.append(child)
        with mock.patch.object(gametree, 'MAX_VARIATION_DEPTH', 1):
            self.assert_serialization_code(game, GameTreeErrorCode.GRAPH_DEPTH_LIMIT)

        game = self.game()
        with mock.patch.object(gametree, 'MAX_TREE_NODES', 3):
            self.assert_serialization_code(game, GameTreeErrorCode.GRAPH_NODE_LIMIT)

    def test_parser_has_matching_depth_and_node_safety_bounds(self):
        deep = '1. e4 (1... c5 (2. Nf3 (2... d6))) *'
        with mock.patch.object(gametree, 'MAX_VARIATION_DEPTH', 1):
            with self.assertRaises(GameTreeContractError) as caught:
                parse_games(deep)
        self.assertEqual(caught.exception.code, GameTreeErrorCode.GRAPH_DEPTH_LIMIT)

        with mock.patch.object(gametree, 'MAX_TREE_NODES', 2):
            with self.assertRaises(GameTreeContractError) as caught:
                parse_games('1. e4 e5 *')
        self.assertEqual(caught.exception.code, GameTreeErrorCode.GRAPH_NODE_LIMIT)

    def test_valid_loss_aware_structure_still_round_trips(self):
        source = (
            '[Event "Rich"]\n[Result "1-0"]\n\n'
            '{lead} 1. e4 $1 {after} (1... c5 $5 {Sicilian}) '
            'e5 2. Nf3 1-0 {tail}\n'
        )
        game = parse_games(source)[0]
        serialized = serialize_game(game)
        reparsed = parse_games(serialized)[0]
        self.assertEqual(reparsed.tags, game.tags)
        self.assertEqual(reparsed.result, '1-0')
        self.assertEqual(reparsed.line.moves[0].san, 'e4')
        self.assertEqual(reparsed.line.moves[0].variations[0].moves[0].san, 'c5')
        self.assertEqual(reparsed.line.trailing_comments[0].text, 'tail')

    def test_serialize_games_preflights_all_games_before_output(self):
        first = self.game()
        second = self.game()
        second.line.moves[0].san = ''
        with self.assertRaises(GameTreeSerializationError) as caught:
            serialize_games((first, second))
        self.assertEqual(caught.exception.code, GameTreeErrorCode.INVALID_MOVE)


if __name__ == '__main__':
    unittest.main()
