from __future__ import annotations

from copy import deepcopy
import unittest

from acs.gametree import Comment, CommentStyle, MoveNode, VariationLine
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
from acs.gametree_insertion import (
    VariationInsertCode,
    VariationInsertError,
    add_variation,
    variation_insert_target,
)
from acs.gametree_navigation import GameTreeCursor, VariationStep, resolve_line, validate_cursor
from acs.pgn_roundtrip import parse_pgn_text, serialize_pgn_text


EDIT_CORPUS = '''[Event "D06 annotation insertion persistence"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

{root lead} 1. e4 $1 {root e4} e5
(1... c5 $2 {sicilian} 2. Nf3 (2... d6 $3 {nested}) 2... Nc6 {sic tail})
(1... e6 {french} 2. d4 d5)
2. Nf3 {main knight} Nc6 {root tail} *

[Event "D06 untouched sibling game"]
[White "Gamma"]
[Black "Delta"]
[Result "1/2-1/2"]

1. d4 d5 2. c4 e6 1/2-1/2
'''


class D06AnnotationInsertionPersistenceVerticalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.games = parse_pgn_text(EDIT_CORPUS)
        self.game = self.games[0]

    def assert_strict_roundtrip_equal(self, games):
        serialized = serialize_pgn_text(games)
        reparsed = parse_pgn_text(serialized)
        self.assertEqual(reparsed, tuple(games))
        return serialized, reparsed

    def test_nested_move_annotation_edit_survives_strict_write_reparse(self):
        original = deepcopy(self.game)
        nested_path = (VariationStep(1, 0), VariationStep(1, 0))
        target = move_annotation_target(self.game, nested_path, 0)
        result = edit_move_annotations(
            self.game,
            target,
            MoveAnnotationPatch(
                comments_before=(Comment("teacher cue"),),
                comments_after=(Comment("student response", CommentStyle.SEMICOLON),),
                nags=("$5", "!?"),
            ),
        )

        self.assertEqual(self.game, original)
        edited_move = resolve_line(result.game, nested_path).moves[0]
        self.assertEqual([comment.text for comment in edited_move.comments_before], ["teacher cue"])
        self.assertEqual([comment.text for comment in edited_move.comments_after], ["student response"])
        self.assertEqual(edited_move.comments_after[0].style, CommentStyle.SEMICOLON)
        self.assertEqual(edited_move.nags, ["$5", "!?"])

        _, reparsed = self.assert_strict_roundtrip_equal((result.game,))
        restored_move = resolve_line(reparsed[0], nested_path).moves[0]
        self.assertEqual(restored_move, edited_move)

    def test_nested_line_annotation_edit_survives_strict_write_reparse(self):
        original = deepcopy(self.game)
        sicilian_path = (VariationStep(1, 0),)
        result = edit_line_annotations(
            self.game,
            line_annotation_target(self.game, sicilian_path),
            LineAnnotationPatch(
                leading_comments=(Comment("new line lead"),),
                trailing_comments=(Comment("new line tail"),),
            ),
        )

        self.assertEqual(self.game, original)
        edited_line = resolve_line(result.game, sicilian_path)
        self.assertEqual([comment.text for comment in edited_line.leading_comments], ["new line lead"])
        self.assertEqual([comment.text for comment in edited_line.trailing_comments], ["new line tail"])

        _, reparsed = self.assert_strict_roundtrip_equal((result.game,))
        restored_line = resolve_line(reparsed[0], sicilian_path)
        self.assertEqual(restored_line, edited_line)

    def test_annotated_nested_insertion_persists_and_remaps_existing_cursors(self):
        original = deepcopy(self.game)
        proposed = VariationLine(
            moves=[MoveNode("d5"), MoveNode("exd5")],
            leading_comments=[Comment("inserted line")],
            trailing_comments=[Comment("insert tail")],
        )
        proposed.moves[0].nags = ["!?"]
        proposed.moves[0].comments_after = [Comment("Benoni idea")]
        proposed.moves[0].variations = [
            VariationLine(
                moves=[MoveNode("Nf6")],
                leading_comments=[Comment("nested insertion")],
            )
        ]

        old_french_cursor = GameTreeCursor((VariationStep(1, 1),), 2)
        result = add_variation(
            self.game,
            variation_insert_target(self.game, (), 1, 1),
            proposed,
        )
        self.assertEqual(self.game, original)
        self.assertEqual(result.inserted_path, (VariationStep(1, 1),))
        self.assertEqual(
            result.remap_cursor(old_french_cursor),
            GameTreeCursor((VariationStep(1, 2),), 2),
        )

        proposed.moves[0].san = "h5"
        inserted = resolve_line(result.game, result.inserted_path)
        self.assertEqual(inserted.moves[0].san, "d5")
        self.assertEqual(inserted.moves[0].nags, ["!?"])
        self.assertEqual(inserted.moves[0].comments_after[0].text, "Benoni idea")
        self.assertEqual(inserted.moves[0].variations[0].moves[0].san, "Nf6")

        _, reparsed = self.assert_strict_roundtrip_equal((result.game,))
        restored = reparsed[0]
        validate_cursor(restored, result.remap_cursor(old_french_cursor))
        restored_inserted = resolve_line(restored, result.inserted_path)
        self.assertEqual(restored_inserted, inserted)

    def test_annotation_revision_invalidates_prepared_insertion_atomically(self):
        stale_insert = variation_insert_target(self.game, (), 1, 0)
        annotated = edit_move_annotations(
            self.game,
            move_annotation_target(self.game, (), 0),
            MoveAnnotationPatch(comments_after=(Comment("changed revision"),)),
        ).game
        before = deepcopy(annotated)

        with self.assertRaises(VariationInsertError) as caught:
            add_variation(
                annotated,
                stale_insert,
                VariationLine(moves=[MoveNode("d5")]),
            )
        self.assertEqual(caught.exception.code, VariationInsertCode.STALE_REVISION)
        self.assertEqual(annotated, before)

    def test_insertion_revision_invalidates_prepared_annotation_atomically(self):
        stale_annotation = move_annotation_target(self.game, (), 0)
        inserted = add_variation(
            self.game,
            variation_insert_target(self.game, (), 1),
            VariationLine(moves=[MoveNode("d5")]),
        ).game
        before = deepcopy(inserted)

        with self.assertRaises(AnnotationEditError) as caught:
            edit_move_annotations(
                inserted,
                stale_annotation,
                MoveAnnotationPatch(nags=("!!",)),
            )
        self.assertEqual(caught.exception.code, AnnotationEditCode.STALE_REVISION)
        self.assertEqual(inserted, before)

    def test_fresh_annotation_target_on_inserted_line_can_be_persisted(self):
        insertion = add_variation(
            self.game,
            variation_insert_target(self.game, (), 1, 1),
            VariationLine(moves=[MoveNode("d5"), MoveNode("exd5")]),
        )
        target = move_annotation_target(insertion.game, insertion.inserted_path, 1)
        annotated = edit_move_annotations(
            insertion.game,
            target,
            MoveAnnotationPatch(
                comments_after=(Comment("follow-up annotation"),),
                nags=("$7",),
            ),
        ).game

        _, reparsed = self.assert_strict_roundtrip_equal((annotated,))
        restored = resolve_line(reparsed[0], insertion.inserted_path).moves[1]
        self.assertEqual(restored.comments_after[0].text, "follow-up annotation")
        self.assertEqual(restored.nags, ["$7"])

    def test_multigame_annotation_and_insertion_isolation_survives_reparse(self):
        untouched_before = deepcopy(self.games[1])
        annotated_first = edit_line_annotations(
            self.games[0],
            line_annotation_target(self.games[0], ()),
            LineAnnotationPatch(leading_comments=(Comment("session note"),)),
        ).game
        edited_first = add_variation(
            annotated_first,
            variation_insert_target(annotated_first, (), 1),
            VariationLine(moves=[MoveNode("d5")], trailing_comments=[Comment("new branch")]),
        ).game

        serialized, reparsed = self.assert_strict_roundtrip_equal((edited_first, self.games[1]))
        self.assertIn('[Event "D06 untouched sibling game"]', serialized)
        self.assertEqual(self.games[1], untouched_before)
        self.assertEqual(reparsed[1], untouched_before)
        self.assertEqual(reparsed[0].source_index, 0)
        self.assertEqual(reparsed[1].source_index, 1)


if __name__ == "__main__":
    unittest.main()
