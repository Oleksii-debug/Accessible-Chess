import unittest
from unittest.mock import patch

from acs.game_identity import same_game_record
from acs.gametree import (
    GameTreeContractError,
    GameTreeErrorCode,
    parse_games,
    serialize_game,
)
from acs.gametree_editing import (
    delete_variation,
    promote_variation,
    reorder_variation,
    variation_edit_target,
)
from acs.gametree_navigation import (
    VariationStep,
    branch_context,
    iter_move_addresses,
    resolve_line,
    validate_cursor,
)


def _generated_line(seed: int, depth: int, *, branch: int = 0) -> str:
    move_count = 2 + ((seed + depth + branch) % 3)
    branch_move = (seed + branch) % move_count
    tokens: list[str] = []
    for move_index in range(move_count):
        token = f'M{seed}d{depth}b{branch}i{move_index}'
        tokens.append(token)
        if (seed + move_index + depth) % 3 == 0:
            tokens.append(f'${(seed + move_index + depth) % 256}')
        if (seed + move_index) % 4 == 0:
            tokens.append(f'{{c{seed}-{depth}-{branch}-{move_index}}}')
        if depth and move_index == branch_move:
            sibling_count = 1 + ((seed + depth) % 3)
            for sibling in range(sibling_count):
                child_seed = seed * 5 + sibling + 1
                child = _generated_line(child_seed, depth - 1, branch=sibling)
                tokens.append(f'({child})')
    return ' '.join(tokens)


def _generated_pgn(seed: int) -> str:
    depth = seed % 6
    return (
        f'[Event "Generated {seed}"]\n'
        f'[Site "Corpus"]\n'
        f'[Result "*"]\n\n'
        f'{_generated_line(seed + 1, depth)} *\n'
    )


def _line_paths(game):
    paths = [()]
    seen = {()}
    for address in iter_move_addresses(game):
        move = resolve_line(game, address.line_path).moves[address.move_index]
        for variation_index in range(len(move.variations)):
            child = address.line_path + (
                VariationStep(address.move_index, variation_index),
            )
            if child not in seen:
                seen.add(child)
                paths.append(child)
    return tuple(paths)


class Dev2GameTreeAdversarialCorpusTests(unittest.TestCase):
    def test_generated_nested_sibling_corpus_round_trips_with_stable_addresses(self):
        for seed in range(64):
            with self.subTest(seed=seed):
                game = parse_games(_generated_pgn(seed))[0]
                self.assertEqual(game.warnings, [])
                addresses = tuple(iter_move_addresses(game))
                self.assertEqual(len(addresses), len(set(addresses)))
                serialized = serialize_game(game)
                reparsed = parse_games(serialized)[0]
                self.assertTrue(same_game_record(game, reparsed))
                self.assertEqual(addresses, tuple(iter_move_addresses(reparsed)))
                self.assertEqual(_line_paths(game), _line_paths(reparsed))
                for path in _line_paths(game):
                    if not path:
                        continue
                    step = path[-1]
                    context = branch_context(
                        game,
                        path[:-1],
                        step.parent_move_index,
                        step.variation_index,
                    )
                    self.assertEqual(context.child_path, path)
                    self.assertEqual(context.resume_parent_move_index, step.parent_move_index + 1)

    def test_generated_edit_compositions_are_deterministic_and_source_neutral(self):
        for seed in range(24):
            with self.subTest(seed=seed):
                source = parse_games(
                    '[Event "Edit corpus"]\n[Result "*"]\n\n'
                    f'Root{seed} (A{seed} A{seed}x (A{seed}n)) '
                    f'(B{seed} B{seed}x) (C{seed} C{seed}x) Tail{seed} *\n'
                )[0]
                source_wire = serialize_game(source)
                source_cursor_count = sum(
                    len(resolve_line(source, path).moves) + 1
                    for path in _line_paths(source)
                )
                operation = seed % 3
                target_index = (seed // 3) % 3
                target = variation_edit_target(source, (), 0, target_index)
                if operation == 0:
                    result = reorder_variation(source, target, (target_index + 1) % 3)
                elif operation == 1:
                    result = delete_variation(source, target)
                else:
                    result = promote_variation(source, target)
                self.assertEqual(len(result.cursor_remap), source_cursor_count)
                self.assertEqual(len({entry.before for entry in result.cursor_remap}), source_cursor_count)
                for entry in result.cursor_remap:
                    if entry.after is not None:
                        validate_cursor(result.game, entry.after)
                edited_wire = serialize_game(result.game)
                self.assertTrue(same_game_record(result.game, parse_games(edited_wire)[0]))
                self.assertEqual(serialize_game(source), source_wire)

    def test_cursor_remaps_compose_across_reorder_promote_and_delete(self):
        for seed in range(12):
            source = parse_games(
                '[Result "*"]\n\n'
                f'Root{seed} (A{seed} Ax{seed}) '
                f'(B{seed} Bx{seed}) (C{seed} Cx{seed}) Tail{seed} *\n'
            )[0]
            first = reorder_variation(source, variation_edit_target(source, (), 0, 2), 0)
            second = promote_variation(first.game, variation_edit_target(first.game, (), 0, 0))
            third = delete_variation(second.game, variation_edit_target(second.game, (), 0, 2))
            for entry in first.cursor_remap:
                cursor = entry.after
                if cursor is not None:
                    cursor = second.remap_cursor(cursor)
                if cursor is not None:
                    cursor = third.remap_cursor(cursor)
                if cursor is not None:
                    validate_cursor(third.game, cursor)
            final_wire = serialize_game(third.game)
            self.assertTrue(same_game_record(third.game, parse_games(final_wire)[0]))

    def test_malformed_delimiter_corpus_is_explicit_and_non_mutating(self):
        corpus = (
            ('1. e4 (1... c5 *', 'unterminated variation'),
            ('1. e4 ) *', 'unmatched closing parenthesis'),
            ('$1 1. e4 *', 'orphan annotation $1'),
            ('1. e4 {unterminated', 'unterminated brace comment'),
            ('1. e4 * e5', '1 unconsumed token(s)'),
        )
        for movetext, expected_warning in corpus:
            with self.subTest(movetext=movetext):
                game = parse_games('[Result "*"]\n\n' + movetext)[0]
                self.assertIn(expected_warning, game.warnings)
                before_warnings = list(game.warnings)
                before_tags = dict(game.tags)
                before_source_index = game.source_index
                serialized = serialize_game(game)
                self.assertIsInstance(serialized, str)
                self.assertEqual(game.warnings, before_warnings)
                self.assertEqual(game.tags, before_tags)
                self.assertEqual(game.source_index, before_source_index)

    def test_small_fixed_resource_envelopes_raise_domain_errors_not_recursion(self):
        with patch('acs.gametree.MAX_TREE_NODES', 3):
            with self.assertRaises(GameTreeContractError) as blocked:
                parse_games('[Result "*"]\n\nA B C D *')
            self.assertEqual(blocked.exception.code, GameTreeErrorCode.GRAPH_NODE_LIMIT)
        with patch('acs.gametree.MAX_VARIATION_DEPTH', 1):
            with self.assertRaises(GameTreeContractError) as blocked:
                parse_games('[Result "*"]\n\nA (B (C)) *')
            self.assertEqual(blocked.exception.code, GameTreeErrorCode.GRAPH_DEPTH_LIMIT)


if __name__ == '__main__':
    unittest.main()
