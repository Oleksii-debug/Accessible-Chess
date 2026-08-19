import unittest
from acs.gametree import (
    Comment,
    CommentStyle,
    GameTreeContractError,
    GameTreeErrorCode,
    GameTreeSerializationError,
    MoveNode,
    PgnGame,
    VariationLine,
    parse_games,
    serialize_games,
)


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
        self.assertEqual(game.line.moves[0].comments_after[0].style, CommentStyle.SEMICOLON)
        out = serialize_games([game])
        self.assertIn(';hello\n', out)
        reparsed = parse_games(out)[0].line.moves[0].comments_after[0]
        self.assertEqual(reparsed.text, 'hello')
        self.assertEqual(reparsed.style, CommentStyle.SEMICOLON)

    def test_semicolon_closing_brace_round_trips_without_token_corruption(self):
        text = '[Result "*"]\n\n1. e4 ;literal } brace\n e5 *'

        original = parse_games(text)[0]
        serialized = serialize_games([original])
        reparsed = parse_games(serialized)[0]

        comment = reparsed.line.moves[0].comments_after[0]
        self.assertEqual(comment.text, "literal } brace")
        self.assertEqual(comment.style, CommentStyle.SEMICOLON)
        self.assertEqual([move.san for move in reparsed.line.moves], ["e4", "e5"])
        self.assertNotIn("unconsumed", " ".join(reparsed.warnings))

    def test_leading_before_move_and_after_move_comment_slots_round_trip(self):
        text = (
            '[Result "*"]\n\n'
            ';intro } text\n'
            '1. ;before } e4\n'
            ' e4 ;after } e4\n'
            ' e5 *'
        )

        original = parse_games(text)[0]
        self.assertEqual(
            [(comment.text, comment.style) for comment in original.line.leading_comments],
            [("intro } text", CommentStyle.SEMICOLON)],
        )
        self.assertEqual(
            [(comment.text, comment.style) for comment in original.line.moves[0].comments_before],
            [("before } e4", CommentStyle.SEMICOLON)],
        )
        self.assertEqual(
            [(comment.text, comment.style) for comment in original.line.moves[0].comments_after],
            [("after } e4", CommentStyle.SEMICOLON)],
        )

        reparsed = parse_games(serialize_games([original]))[0]
        self.assertEqual(reparsed.line.leading_comments, original.line.leading_comments)
        self.assertEqual(
            reparsed.line.moves[0].comments_before,
            original.line.moves[0].comments_before,
        )
        self.assertEqual(
            reparsed.line.moves[0].comments_after,
            original.line.moves[0].comments_after,
        )

    def test_comment_and_tag_escape_edge_corpus_is_deterministic(self):
        semicolon_comments = (
            "",
            "}",
            "{ nested-looking } text",
            "$1 (not a variation) ; still comment",
            "  leading and trailing spaces  ",
            'quotes " and backslash \\',
            "Український коментар ♟ }",
        )
        for text in semicolon_comments:
            with self.subTest(kind="semicolon", text=text):
                source = f'[Result "*"]\n\n1. e4 ;{text}\n e5 *'
                reparsed = parse_games(serialize_games(parse_games(source)))[0]
                comment = reparsed.line.moves[0].comments_after[0]
                self.assertEqual(comment.text, text)
                self.assertEqual(comment.style, CommentStyle.SEMICOLON)

        brace_comments = (
            "",
            "{ nested-looking opener",
            "; not a semicolon comment",
            "$1 (not a variation)",
            "line one\nline two",
            'quotes " and backslash \\',
            "Український коментар ♞",
        )
        for text in brace_comments:
            with self.subTest(kind="brace", text=text):
                game = PgnGame(
                    line=VariationLine(
                        moves=[
                            MoveNode(
                                "e4",
                                move_number="1.",
                                comments_after=[Comment(text, CommentStyle.BRACE)],
                            )
                        ],
                        result="*",
                    )
                )
                reparsed = parse_games(serialize_games([game]))[0]
                comment = reparsed.line.moves[0].comments_after[0]
                self.assertEqual(comment.text, text)
                self.assertEqual(comment.style, CommentStyle.BRACE)

        tag_values = (
            "",
            'quote " value',
            "backslash \\ value",
            'combined \\" value',
            "Українська подія ♟",
        )
        for value in tag_values:
            with self.subTest(kind="tag", value=value):
                game = PgnGame(
                    tags={"Event": value},
                    line=VariationLine(result="*"),
                )
                reparsed = parse_games(serialize_games([game]))[0]
                self.assertEqual(reparsed.tags["Event"], value)

    def test_unrepresentable_or_unknown_comment_data_fails_with_stable_codes(self):
        with self.assertRaises(GameTreeContractError) as unknown_style:
            Comment("text", "future-style")
        self.assertEqual(
            unknown_style.exception.code,
            GameTreeErrorCode.UNSUPPORTED_COMMENT_STYLE,
        )

        cases = (
            (
                Comment("cannot } stay brace", CommentStyle.BRACE),
                GameTreeErrorCode.UNREPRESENTABLE_COMMENT,
            ),
            (
                Comment("two\nlines", CommentStyle.SEMICOLON),
                GameTreeErrorCode.UNREPRESENTABLE_COMMENT,
            ),
        )
        for comment, expected_code in cases:
            with self.subTest(comment=comment):
                game = PgnGame(line=VariationLine(moves=[MoveNode("e4", comments_after=[comment])]))
                with self.assertRaises(GameTreeSerializationError) as caught:
                    serialize_games([game])
                self.assertEqual(caught.exception.code, expected_code)

    def test_header_result_mismatch_is_warning_not_silent_rewrite(self):
        game = parse_games('[Result "1-0"]\n\n1. e4 0-1')[0]
        self.assertTrue(any('differs' in w for w in game.warnings))
        self.assertEqual(game.line.result, '0-1')
        self.assertEqual(game.tags['Result'], '1-0')

        serialized = serialize_games([game])
        self.assertIn('[Result "1-0"]', serialized)
        self.assertTrue(serialized.rstrip().endswith("0-1"))
        reparsed = parse_games(serialized)[0]
        self.assertEqual(reparsed.tags["Result"], "1-0")
        self.assertEqual(reparsed.line.result, "0-1")
        self.assertTrue(any("differs" in warning for warning in reparsed.warnings))

    def test_invalid_header_result_is_preserved_but_not_promoted_to_domain_result(self):
        game = parse_games('[Event "Damaged"]\n[Result "later"]\n\n1. e4')[0]

        self.assertEqual(game.tags["Result"], "later")
        self.assertEqual(game.line.result, "*")
        self.assertEqual(game.result, "*")
        self.assertIn("invalid header Result later", game.warnings)
        serialized = serialize_games([game])
        self.assertIn('[Result "later"]', serialized)
        self.assertTrue(serialized.rstrip().endswith("*"))

    def test_duplicate_tags_are_reported_instead_of_silently_disappearing(self):
        game = parse_games('[Event "First"]\n[Event "Second"]\n[Result "*"]\n\n*')[0]

        self.assertEqual(game.tags["Event"], "Second")
        self.assertIn("duplicate tag Event; last value preserved", game.warnings)

    def test_empty_collection_is_empty_and_multiple_games_have_a_blank_separator(self):
        self.assertEqual(serialize_games([]), "")
        games = parse_games(
            '[Event "One"]\n[Result "*"]\n\n1. e4 *\n\n'
            '[Event "Two"]\n[Result "*"]\n\n1. d4 *'
        )
        serialized = serialize_games(games)
        self.assertIn("*\n\n[Event \"Two\"]", serialized)


if __name__ == '__main__':
    unittest.main()
