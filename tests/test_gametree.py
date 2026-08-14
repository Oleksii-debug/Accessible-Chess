import unittest
from acs.gametree import parse_games, serialize_games


class GameTreeTests(unittest.TestCase):
    def test_nested_rav_comments_and_nags_are_preserved(self):
        text = '''[Event "Nested"]
[White "A"]
[Black "B"]
[Result "*"]

1. e4 {main} e5 (1... c5 $1 {Sicilian} 2. Nf3 (2. Nc3!? Nc6)) 2. Nf3 Nc6 *
'''
        games = parse_games(text)
        self.assertEqual(len(games), 1)
        game = games[0]
        self.assertEqual([m.san for m in game.line.moves], ['e4', 'e5', 'Nf3', 'Nc6'])
        self.assertEqual(game.line.moves[0].comments_after[0].text, 'main')
        variation = game.line.moves[1].variations[0]
        self.assertEqual([m.san for m in variation.moves], ['c5', 'Nf3'])
        self.assertIn('$1', variation.moves[0].nags)
        nested = variation.moves[1].variations[0]
        self.assertEqual([m.san for m in nested.moves], ['Nc3!?', 'Nc6'])

        reparsed = parse_games(serialize_games(games))[0]
        self.assertEqual([m.san for m in reparsed.line.moves], ['e4', 'e5', 'Nf3', 'Nc6'])
        self.assertEqual([m.san for m in reparsed.line.moves[1].variations[0].moves], ['c5', 'Nf3'])

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

    def test_semicolon_comment_survives_semantically(self):
        game = parse_games('[Result "*"]\n\n1. e4 ;hello\n e5 *')[0]
        self.assertEqual(game.line.moves[0].comments_after[0].text, 'hello')
        out = serialize_games([game])
        self.assertIn('{hello}', out)
        self.assertEqual(parse_games(out)[0].line.moves[0].comments_after[0].text, 'hello')

    def test_header_result_mismatch_is_warning_not_silent_rewrite(self):
        game = parse_games('[Result "1-0"]\n\n1. e4 0-1')[0]
        self.assertTrue(any('differs' in w for w in game.warnings))
        self.assertEqual(game.line.result, '0-1')
        self.assertEqual(game.tags['Result'], '1-0')


if __name__ == '__main__':
    unittest.main()
