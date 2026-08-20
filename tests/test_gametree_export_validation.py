import unittest
from unittest import mock

import acs.gametree as gametree
from acs.gametree import (
    GameTreeContractError,
    GameTreeErrorCode,
    GameTreeSerializationError,
    MoveNode,
    PgnRecoveryCode,
    PgnRecoveryIssue,
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
        for invalid in ('', '   ', '1-0', '2...', '2..', '2....', '$4', 'e4 e5', 'e4)', 'e4!?', 'e4$1'):
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

        for invalid_nag in ('not-a-nag', '$01', '$256', '$999999'):
            game = self.game()
            game.line.moves[0].nags.append(invalid_nag)
            with self.subTest(nag=invalid_nag):
                self.assert_serialization_code(game, GameTreeErrorCode.INVALID_NAG)

        for invalid_move_number in (1, '1..', '1....'):
            game = self.game()
            game.line.moves[0].move_number = invalid_move_number
            with self.subTest(move_number=invalid_move_number):
                self.assert_serialization_code(game, GameTreeErrorCode.INVALID_MOVE)

        game = self.game()
        game.line.moves[0].nags = ['$0', '$255', '!?']
        self.assertIn('$0 $255 !?', serialize_game(game))

        game = self.game()
        game.line.moves = tuple(game.line.moves)
        self.assert_serialization_code(game, GameTreeErrorCode.INVALID_CONTAINER)

        game = self.game()
        game.recovery_issues = (PgnRecoveryIssue(
            PgnRecoveryCode.POST_RESULT_RAV_TAIL,
            "one damaged token",
            1,
            1,
        ),)
        self.assert_serialization_code(game, GameTreeErrorCode.INVALID_RECOVERY_ISSUE)

    def test_unresolved_structured_recovery_evidence_blocks_export(self):
        game = self.game()
        game.recovery_issues.append(PgnRecoveryIssue(
            PgnRecoveryCode.POST_RESULT_RAV_TAIL,
            "three tokens quarantined inside variation",
            2,
            3,
        ))

        self.assert_serialization_code(game, GameTreeErrorCode.UNRESOLVED_RECOVERY)

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

    def test_direct_parser_resource_limits_fail_with_stable_codes(self):
        with self.assertRaises(GameTreeContractError) as invalid_type:
            parse_games(b'1. e4 *')
        self.assertEqual(invalid_type.exception.code, GameTreeErrorCode.INVALID_INPUT)

        parser_cases = (
            ('MAX_PGN_INPUT_CHARACTERS', 4, '1. e4 *', GameTreeErrorCode.INPUT_CHARACTER_LIMIT),
            ('MAX_PGN_TOKENS', 2, '1. e4 *', GameTreeErrorCode.TOKEN_LIMIT),
            ('MAX_PGN_LINES', 2, '1.\ne4\n*', GameTreeErrorCode.LINE_LIMIT),
            (
                'MAX_PGN_GAMES',
                1,
                '[Result "*"]\n\n1. e4 *\n\n[Result "*"]\n\n1. d4 *',
                GameTreeErrorCode.GAME_LIMIT,
            ),
            (
                'MAX_TAGS_PER_GAME',
                1,
                '[Event "A"]\n[Result "*"]\n\n1. e4 *',
                GameTreeErrorCode.TAG_LIMIT,
            ),
            (
                'MAX_TAG_VALUE_CHARACTERS',
                3,
                '[Event "Four"]\n[Result "*"]\n\n1. e4 *',
                GameTreeErrorCode.FIELD_LIMIT,
            ),
            ('MAX_TOKEN_CHARACTERS', 3, '1. Nf3x *', GameTreeErrorCode.FIELD_LIMIT),
            ('MAX_COMMENT_CHARACTERS', 3, '1. e4 {four} *', GameTreeErrorCode.FIELD_LIMIT),
        )
        for constant, limit, source, expected_code in parser_cases:
            with self.subTest(constant=constant):
                with mock.patch.object(gametree, constant, limit):
                    with self.assertRaises(GameTreeContractError) as caught:
                        parse_games(source)
                self.assertEqual(caught.exception.code, expected_code)

        two_games = '[Result "*"]\n\n1. e4 *\n\n[Result "*"]\n\n1. d4 *'
        with mock.patch.object(gametree, 'MAX_TREE_NODES', 3):
            with self.assertRaises(GameTreeContractError) as collection_nodes:
                parse_games(two_games)
        self.assertEqual(
            collection_nodes.exception.code,
            GameTreeErrorCode.GRAPH_NODE_LIMIT,
        )

    def test_serializer_resource_limits_precede_large_output_assembly(self):
        game = self.game()
        with mock.patch.object(gametree, 'MAX_PGN_OUTPUT_CHARACTERS', 10):
            self.assert_serialization_code(game, GameTreeErrorCode.OUTPUT_LIMIT)

        games = (self.game(), self.game())
        with mock.patch.object(gametree, 'MAX_PGN_GAMES', 1):
            with self.assertRaises(GameTreeSerializationError) as game_limit:
                serialize_games(games)
        self.assertEqual(game_limit.exception.code, GameTreeErrorCode.GAME_LIMIT)

        game = self.game()
        game.tags['Event'] = 'four'
        with mock.patch.object(gametree, 'MAX_TAG_VALUE_CHARACTERS', 3):
            self.assert_serialization_code(game, GameTreeErrorCode.FIELD_LIMIT)

        game = self.game()
        game.line.moves[0].comments_after.append(gametree.Comment('four'))
        with mock.patch.object(gametree, 'MAX_COMMENT_CHARACTERS', 3):
            self.assert_serialization_code(game, GameTreeErrorCode.FIELD_LIMIT)

    def test_normal_multi_game_fixture_remains_well_inside_resource_envelope(self):
        source = '\n\n'.join(
            f'[Event "Game {index}"]\n[Result "*"]\n\n1. e4 e5 *'
            for index in range(200)
        )
        games = parse_games(source)
        self.assertEqual(len(games), 200)
        self.assertEqual(len(parse_games(serialize_games(games))), 200)

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
