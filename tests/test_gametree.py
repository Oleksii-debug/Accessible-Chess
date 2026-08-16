import unittest

from acs.gametree import (
    PgnGame,
    canonicalize_games,
    iter_variations,
    parse_game,
    parse_games,
    serialize_game,
    serialize_games,
    structural_signature,
    tokenize_movetext,
)


class GameTreeTests(unittest.TestCase):
    def test_nested_rav_comments_and_nags_are_preserved(self):
        text = '''[Event "Nested"]
[White "A"]
[Black "B"]
[Result "*"]

1. e4 {main} e5 (1... c5 $1 {Sicilian} 2. Nf3 (2. Nc3!? Nc6)) 2. Nf3 Nc6 *
'''
        game = parse_games(text)[0]
        self.assertEqual([m.san for m in game.line.moves], ['e4', 'e5', 'Nf3', 'Nc6'])
        self.assertEqual(game.line.moves[0].comments_after[0].text, 'main')
        variation = game.line.moves[1].variations[0]
        self.assertEqual([m.san for m in variation.moves], ['c5', 'Nf3'])
        self.assertIn('$1', variation.moves[0].nags)
        nested = variation.moves[1].variations[0]
        self.assertEqual([m.san for m in nested.moves], ['Nc3', 'Nc6'])
        self.assertEqual(nested.moves[0].nags, ['!?'])

        reparsed = parse_games(serialize_games([game]))[0]
        self.assertEqual(structural_signature(game), structural_signature(reparsed))

    def test_attached_symbolic_nags_are_structural_not_part_of_san(self):
        game = parse_game('[Result "*"]\n\n1.e4! e5?! 2.Nf3?? Nc6!! 3.Bb5!? a6? *')
        self.assertEqual(
            [(m.san, m.nags) for m in game.line.moves],
            [('e4', ['!']), ('e5', ['?!']), ('Nf3', ['??']), ('Nc6', ['!!']), ('Bb5', ['!?']), ('a6', ['?'])],
        )

    def test_numeric_nag_range_and_invalid_nag_recovery(self):
        game = parse_game('[Result "*"]\n\n1. e4 $1 e5 $255 2. Nf3 $x Nc6 *')
        self.assertEqual(game.line.moves[0].nags, ['$1'])
        self.assertEqual(game.line.moves[1].nags, ['$255'])
        self.assertIn('$x', game.line.unsupported_tokens)
        self.assertTrue(any(d.code == 'unsupported-token' for d in game.diagnostics))
        self.assertTrue(any('invalid NAG token' in w for w in game.warnings))

    def test_multi_game_collection_stays_separate(self):
        text = '''[Event "G1"]
[Result "1-0"]

1. e4 e5 1-0

[Event "G2"]
[Result "0-1"]

1. d4 d5 0-1
'''
        games = parse_games(text)
        self.assertEqual([g.tags['Event'] for g in games], ['G1', 'G2'])
        self.assertEqual([[m.san for m in g.line.moves] for g in games], [['e4', 'e5'], ['d4', 'd5']])
        self.assertEqual([g.source_index for g in games], [0, 1])

    def test_header_looking_text_inside_multiline_comment_does_not_split_game(self):
        text = '''[Event "Real 1"]
[Result "*"]

1. e4 {comment begins
[Event "not a game"]
[Result "0-1"]
still the same comment} e5 *

[Event "Real 2"]
[Result "*"]

1. d4 d5 *
'''
        games = parse_games(text)
        self.assertEqual(len(games), 2)
        self.assertEqual([g.tags['Event'] for g in games], ['Real 1', 'Real 2'])
        self.assertIn('[Event "not a game"]', games[0].line.moves[0].comments_after[0].text)

    def test_semicolon_comment_survives_semantically(self):
        game = parse_game('[Result "*"]\n\n1. e4 ;hello\n e5 *')
        self.assertEqual(game.line.moves[0].comments_after[0].text, 'hello')
        self.assertEqual(game.line.moves[0].comments_after[0].style, 'semicolon')
        out = serialize_games([game])
        self.assertIn('{hello}', out)
        self.assertEqual(parse_games(out)[0].line.moves[0].comments_after[0].text, 'hello')

    def test_common_tags_setup_fen_and_escaped_values_round_trip(self):
        text = '''[Event "Quoted \\"event\\""]
[Site "Kyiv\\\\Lab"]
[Date "2026.08.16"]
[Round "7"]
[White "A"]
[Black "B"]
[Result "1/2-1/2"]
[SetUp "1"]
[FEN "8/8/8/8/8/8/4K3/7k w - - 0 1"]
[WhiteElo "2000"]
[BlackElo "1999"]
[ECO "A00"]

1. Kf3 Kg1 1/2-1/2
'''
        game = parse_game(text)
        self.assertEqual(game.tags['Event'], 'Quoted "event"')
        self.assertEqual(game.tags['Site'], 'Kyiv\\Lab')
        self.assertEqual(game.tags['SetUp'], '1')
        self.assertTrue(game.tags['FEN'].startswith('8/8/8'))
        reparsed = parse_game(serialize_game(game))
        self.assertEqual(game.tags, reparsed.tags)
        self.assertEqual([m.san for m in reparsed.line.moves], ['Kf3', 'Kg1'])

    def test_canonical_tag_order_is_deterministic(self):
        game = parse_game('''[Zed "z"]
[Black "B"]
[Event "E"]
[Result "*"]
[Alpha "a"]
[White "W"]
[SetUp "1"]
[FEN "8/8/8/8/8/8/4K3/7k w - - 0 1"]

*''')
        out = serialize_game(game)
        expected = ['[Event ', '[White ', '[Black ', '[Result ', '[SetUp ', '[FEN ', '[Alpha ', '[Zed ']
        positions = [out.index(marker) for marker in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(canonicalize_games(out), out)

    def test_header_result_mismatch_is_warning_and_typed_diagnostic(self):
        game = parse_game('[Result "1-0"]\n\n1. e4 0-1')
        self.assertTrue(any('differs' in w for w in game.warnings))
        self.assertTrue(any(d.code == 'result-mismatch' for d in game.diagnostics))
        self.assertEqual(game.line.result, '0-1')
        self.assertEqual(game.tags['Result'], '1-0')

    def test_duplicate_tag_is_diagnosed_last_value_preserved(self):
        game = parse_game('[Event "A"]\n[Event "B"]\n[Result "*"]\n\n*')
        self.assertEqual(game.tags['Event'], 'B')
        self.assertTrue(any(d.code == 'duplicate-tag' for d in game.diagnostics))

    def test_unterminated_comment_and_variation_are_recoverable(self):
        comment_game = parse_game('[Result "*"]\n\n1. e4 {never closes')
        self.assertEqual(comment_game.line.moves[0].comments_after[0].text, 'never closes')
        self.assertTrue(any('unterminated brace comment' in w for w in comment_game.warnings))

        rav_game = parse_game('[Result "*"]\n\n1. e4 e5 (1... c5 2. Nf3')
        self.assertEqual([m.san for m in rav_game.line.moves[1].variations[0].moves], ['c5', 'Nf3'])
        self.assertTrue(any(d.code == 'unterminated-rav' for d in rav_game.diagnostics))

    def test_unmatched_closing_parenthesis_is_preserved_as_unsupported(self):
        game = parse_game('[Result "*"]\n\n1. e4 ) e5 *')
        self.assertIn(')', game.line.unsupported_tokens)
        self.assertTrue(any(d.code == 'unmatched-rparen' for d in game.diagnostics))

    def test_special_san_tokens_are_preserved_without_reimplementing_legality(self):
        text = '''[Event "Special SAN"]
[Result "*"]

1. O-O O-O-O 2. exd6 e.p. Kf7 3. e8=Q+ Rxe8 4. Qh8# -- *'''
        game = parse_game(text)
        self.assertEqual(
            [m.san for m in game.line.moves],
            ['O-O', 'O-O-O', 'exd6', 'e.p.', 'Kf7', 'e8=Q+', 'Rxe8', 'Qh8#', '--'],
        )
        reparsed = parse_game(serialize_game(game))
        self.assertEqual([m.san for m in reparsed.line.moves], [m.san for m in game.line.moves])

    def test_comments_before_first_move_and_at_end_have_stable_placement(self):
        game = parse_game('[Result "*"]\n\n{intro} 1. e4 e5 {after e5} {tail} *')
        self.assertEqual(game.line.moves[0].comments_before[0].text, 'intro')
        self.assertEqual([c.text for c in game.line.moves[1].comments_after], ['after e5', 'tail'])
        reparsed = parse_game(serialize_game(game))
        self.assertEqual(reparsed.line.moves[0].comments_before[0].text, 'intro')

    def test_recursive_iterators_cover_nested_variations(self):
        game = parse_game('[Result "*"]\n\n1. e4 e5 (1... c5 2. Nf3 (2. Nc3 Nc6)) 2. Nf3 *')
        self.assertEqual([m.san for m in game.iter_moves()], ['e4', 'e5', 'Nf3'])
        self.assertEqual(
            [m.san for m in game.iter_moves(recursive=True)],
            ['e4', 'e5', 'c5', 'Nf3', 'Nc3', 'Nc6', 'Nf3'],
        )
        self.assertEqual(len(list(iter_variations(game.line))), 2)
        self.assertEqual(game.ply_count, 3)

    def test_escape_lines_are_preserved(self):
        game = parse_game('%producer command\n[Event "E"]\n[Result "*"]\n\n1. e4\n%midgame extension\ne5 *')
        self.assertIn('%producer command', game.escape_lines)
        self.assertIn('%midgame extension', game.escape_lines)
        out = serialize_game(game)
        self.assertIn('%producer command', out)
        self.assertIn('%midgame extension', out)

    def test_orphan_annotations_and_move_numbers_are_diagnosed(self):
        game = parse_game('[Result "*"]\n\n$1 ! 1. *')
        codes = {d.code for d in game.diagnostics}
        self.assertIn('orphan-nag', codes)
        self.assertIn('orphan-move-number', codes)
        self.assertIn('$1', game.line.unsupported_tokens)

    def test_movetext_after_result_is_not_silently_dropped(self):
        game = parse_game('[Result "1-0"]\n\n1. e4 1-0 junk')
        self.assertEqual([m.san for m in game.line.moves], ['e4', 'junk'])
        self.assertTrue(any(d.code == 'movetext-after-result' for d in game.diagnostics))

    def test_parse_game_requires_exactly_one_record(self):
        with self.assertRaises(ValueError):
            parse_game('')
        with self.assertRaises(ValueError):
            parse_game('[Result "*"]\n\n*\n[Event "B"]\n[Result "*"]\n\n*')

    def test_tokenizer_handles_compact_move_numbers_and_rav(self):
        tokens = tokenize_movetext('1.e4 e5 2...Nc6 (2...Nf6!?) *')
        compact = [(t.kind, t.value) for t in tokens]
        self.assertIn(('MOVE_NUMBER', '1.'), compact)
        self.assertIn(('SAN', 'e4'), compact)
        self.assertIn(('MOVE_NUMBER', '2...'), compact)
        self.assertIn(('SAN', 'Nf6'), compact)
        self.assertIn(('NAG_SYMBOL', '!?'), compact)

    def test_empty_collection_serializes_to_empty_string(self):
        self.assertEqual(parse_games(''), [])
        self.assertEqual(serialize_games([]), '')

    def test_large_thousand_game_collection_round_trips(self):
        template = '''[Event "Synthetic {index}"]
[Site "Corpus"]
[Date "2026.08.16"]
[Round "{index}"]
[White "White {index}"]
[Black "Black {index}"]
[Result "*"]
[ECO "C50"]

1. e4 e5 2. Nf3 Nc6 (2... Nf6 $5 3. d4 (3. Bc4!?)) 3. Bc4 Bc5 4. O-O Nf6 *
'''
        source = '\n'.join(template.format(index=i) for i in range(1000))
        games = parse_games(source)
        self.assertEqual(len(games), 1000)
        self.assertEqual(games[0].tags['Event'], 'Synthetic 0')
        self.assertEqual(games[-1].tags['Event'], 'Synthetic 999')
        self.assertEqual(sum(g.ply_count for g in games), 8000)

        exported = serialize_games(games)
        reparsed = parse_games(exported)
        self.assertEqual(len(reparsed), 1000)
        self.assertEqual(
            [structural_signature(g) for g in games[:25]],
            [structural_signature(g) for g in reparsed[:25]],
        )
        self.assertEqual(canonicalize_games(exported), exported)


if __name__ == '__main__':
    unittest.main()
