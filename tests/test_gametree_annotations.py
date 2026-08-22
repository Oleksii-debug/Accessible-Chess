import unittest

from acs.gametree import Comment, CommentStyle, parse_games, serialize_game
from acs.gametree_annotations import (
    AnnotationEditCode,
    AnnotationEditError,
    LineAnnotationPatch,
    MoveAnnotationPatch,
    edit_line_annotations,
    edit_move_annotations,
    line_annotation_target,
    move_annotation_target,
)
from acs.gametree_navigation import VariationStep, resolve_line


PGN = '''[Event "Annotation tree"]
[Result "*"]

{lead} 1. e4 $1 {main} e5
(1... c5 $2 {sicilian} 2. Nf3)
2. Nf3 Nc6 {tail} *
'''


class GameTreeAnnotationEditingTests(unittest.TestCase):
    def setUp(self):
        self.game = parse_games(PGN)[0]
        self.before = serialize_game(self.game)

    def test_move_annotations_are_copy_on_write_and_detached(self):
        target = move_annotation_target(self.game, (), 0)
        before = Comment('before replacement', CommentStyle.BRACE)
        after = Comment('after replacement', CommentStyle.SEMICOLON)
        result = edit_move_annotations(
            self.game,
            target,
            MoveAnnotationPatch(
                comments_before=(before,),
                comments_after=(after,),
                nags=('$3', '!?'),
            ),
        )
        move = result.game.line.moves[0]
        self.assertEqual([c.text for c in move.comments_before], ['before replacement'])
        self.assertEqual([c.text for c in move.comments_after], ['after replacement'])
        self.assertEqual(move.nags, ['$3', '!?'])
        self.assertEqual(serialize_game(self.game), self.before)
        self.assertIsNot(result.game, self.game)
        before.text = 'caller changed'
        after.text = 'caller changed'
        self.assertEqual(move.comments_before[0].text, 'before replacement')
        self.assertEqual(move.comments_after[0].text, 'after replacement')
        self.assertNotEqual(result.before_record_digest, result.after_record_digest)

    def test_nested_variation_move_target_is_exact(self):
        path = (VariationStep(1, 0),)
        target = move_annotation_target(self.game, path, 0)
        result = edit_move_annotations(
            self.game,
            target,
            MoveAnnotationPatch(nags=('!!',)),
        )
        self.assertEqual(resolve_line(result.game, path).moves[0].nags, ['!!'])
        self.assertEqual(self.game.line.moves[1].variations[0].moves[0].nags, ['$2'])

    def test_line_comments_are_copy_on_write_and_round_trip_stable(self):
        target = line_annotation_target(self.game, ())
        result = edit_line_annotations(
            self.game,
            target,
            LineAnnotationPatch(
                leading_comments=(Comment('new lead'),),
                trailing_comments=(Comment('new tail'),),
            ),
        )
        self.assertEqual([c.text for c in result.game.line.leading_comments], ['new lead'])
        self.assertEqual([c.text for c in result.game.line.trailing_comments], ['new tail'])
        reparsed = parse_games(serialize_game(result.game))[0]
        self.assertEqual([c.text for c in reparsed.line.leading_comments], ['new lead'])
        self.assertEqual([c.text for c in reparsed.line.trailing_comments], ['new tail'])
        self.assertEqual(serialize_game(self.game), self.before)

    def test_stale_move_target_rejects_without_partial_mutation(self):
        target = move_annotation_target(self.game, (), 0)
        self.game.tags['Event'] = 'changed'
        changed = serialize_game(self.game)
        with self.assertRaises(AnnotationEditError) as blocked:
            edit_move_annotations(self.game, target, MoveAnnotationPatch(nags=('$4',)))
        self.assertEqual(blocked.exception.code, AnnotationEditCode.STALE_REVISION)
        self.assertEqual(serialize_game(self.game), changed)

    def test_stale_line_target_rejects_without_partial_mutation(self):
        target = line_annotation_target(self.game, ())
        self.game.line.moves[0].san = 'd4'
        changed = serialize_game(self.game)
        with self.assertRaises(AnnotationEditError) as blocked:
            edit_line_annotations(
                self.game,
                target,
                LineAnnotationPatch(leading_comments=(Comment('x'),)),
            )
        self.assertEqual(blocked.exception.code, AnnotationEditCode.STALE_REVISION)
        self.assertEqual(serialize_game(self.game), changed)

    def test_invalid_move_target_scalars_fail_closed(self):
        for move_index in (True, -1, 1.5, '0', 99):
            with self.subTest(move_index=move_index):
                with self.assertRaises(AnnotationEditError):
                    move_annotation_target(self.game, (), move_index)
                self.assertEqual(serialize_game(self.game), self.before)

    def test_invalid_nags_and_comment_containers_are_rejected(self):
        for nags in ((1,), ('good',), (True,), ['$1']):
            with self.subTest(nags=nags):
                with self.assertRaises((TypeError, ValueError)):
                    MoveAnnotationPatch(nags=nags)
        with self.assertRaises(TypeError):
            MoveAnnotationPatch(comments_before=[Comment('x')])
        with self.assertRaises(ValueError):
            MoveAnnotationPatch()
        self.assertEqual(serialize_game(self.game), self.before)

    def test_unrepresentable_comment_fails_atomically(self):
        target = move_annotation_target(self.game, (), 0)
        with self.assertRaises(AnnotationEditError) as blocked:
            edit_move_annotations(
                self.game,
                target,
                MoveAnnotationPatch(comments_after=(Comment('bad } brace'),)),
            )
        self.assertEqual(blocked.exception.code, AnnotationEditCode.UNREPRESENTABLE)
        self.assertEqual(serialize_game(self.game), self.before)


if __name__ == '__main__':
    unittest.main()
