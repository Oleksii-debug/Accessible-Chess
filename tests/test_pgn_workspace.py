from __future__ import annotations

from copy import deepcopy
import unittest

from acs.gametree import Comment, MoveNode, VariationLine
from acs.gametree_annotations import (
    AnnotationEditCode,
    AnnotationEditError,
    MoveAnnotationPatch,
    move_annotation_target,
)
from acs.gametree_editing import variation_edit_target
from acs.gametree_insertion import variation_insert_target
from acs.gametree_navigation import GameTreeCursor, VariationStep, resolve_line
from acs.pgn_workspace import PgnWorkspace, PgnWorkspaceError, PgnWorkspaceErrorCode


DOCUMENT = '''[Event "Workspace One"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 e5 (1... c5 {Sicilian} 2. Nf3 (2... d6) 2... Nc6) (1... c6 2. d4) 2. Nf3 Nc6 1-0

[Event "Workspace Two"]
[White "Gamma"]
[Black "Delta"]
[Result "1/2-1/2"]

1. d4 d5 2. c4 e6 1/2-1/2
'''


class ProfessionalPgnWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = PgnWorkspace.from_text(DOCUMENT)

    def test_open_builds_strict_multigame_workspace_and_summaries(self):
        self.assertEqual(self.workspace.game_count, 2)
        summaries = self.workspace.summaries()
        self.assertEqual([item.event for item in summaries], ["Workspace One", "Workspace Two"])
        self.assertEqual(summaries[0].white, "Alpha")
        self.assertEqual(summaries[1].result, "1/2-1/2")
        self.assertFalse(self.workspace.dirty)
        self.assertEqual(self.workspace.content_revision, 0)

    def test_bytes_roundtrip_uses_same_canonical_document(self):
        reopened = PgnWorkspace.from_bytes(DOCUMENT.encode("utf-8"))
        self.assertEqual(reopened.to_text(), self.workspace.to_text())
        self.assertEqual(reopened.to_bytes(), self.workspace.to_bytes())

    def test_external_game_copy_cannot_mutate_workspace(self):
        before = self.workspace.to_text()
        detached = self.workspace.current_game()
        detached.tags["Event"] = "MUTATED OUTSIDE"
        detached.line.moves[0].san = "a4"
        self.assertEqual(self.workspace.to_text(), before)
        self.assertEqual(self.workspace.summaries()[0].event, "Workspace One")

    def test_game_navigation_resets_cursor_without_dirtying_content(self):
        self.workspace.next_move()
        self.workspace.next_move()
        self.assertEqual(self.workspace.cursor.next_move_index, 2)
        self.workspace.next_game()
        self.assertEqual(self.workspace.selected_game_index, 1)
        self.assertEqual(self.workspace.cursor, GameTreeCursor())
        self.workspace.previous_game()
        self.assertEqual(self.workspace.selected_game_index, 0)
        self.assertFalse(self.workspace.dirty)
        self.assertEqual(self.workspace.content_revision, 0)

    def test_game_navigation_boundaries_fail_explicitly(self):
        with self.assertRaises(PgnWorkspaceError) as caught:
            self.workspace.previous_game()
        self.assertEqual(caught.exception.code, PgnWorkspaceErrorCode.NO_PREVIOUS_GAME)
        self.workspace.select_game(1)
        with self.assertRaises(PgnWorkspaceError) as caught:
            self.workspace.next_game()
        self.assertEqual(caught.exception.code, PgnWorkspaceErrorCode.NO_NEXT_GAME)
        with self.assertRaises(PgnWorkspaceError) as caught:
            self.workspace.select_game(2)
        self.assertEqual(caught.exception.code, PgnWorkspaceErrorCode.GAME_INDEX)

    def test_move_navigation_has_explicit_start_and_end_boundaries(self):
        self.assertEqual(self.workspace.current_move().san, "e4")
        with self.assertRaises(PgnWorkspaceError) as caught:
            self.workspace.previous_move()
        self.assertEqual(caught.exception.code, PgnWorkspaceErrorCode.NO_PREVIOUS_MOVE)

        self.workspace.line_end()
        self.assertIsNone(self.workspace.current_move())
        with self.assertRaises(PgnWorkspaceError) as caught:
            self.workspace.next_move()
        self.assertEqual(caught.exception.code, PgnWorkspaceErrorCode.NO_NEXT_MOVE)

        self.workspace.line_start()
        self.assertEqual(self.workspace.current_move().san, "e4")

    def test_enter_leave_and_sibling_variation_navigation_is_exact(self):
        self.workspace.set_cursor(GameTreeCursor((), 2))
        self.workspace.enter_variation(0)
        first_path = (VariationStep(1, 0),)
        self.assertEqual(self.workspace.cursor, GameTreeCursor(first_path, 0))
        self.assertEqual(self.workspace.current_move().san, "c5")

        self.workspace.sibling_variation(1)
        second_path = (VariationStep(1, 1),)
        self.assertEqual(self.workspace.cursor, GameTreeCursor(second_path, 0))
        self.assertEqual(self.workspace.current_move().san, "c6")

        self.workspace.leave_variation()
        self.assertEqual(self.workspace.cursor, GameTreeCursor((), 2))

    def test_nested_variation_navigation_preserves_return_context(self):
        first_path = (VariationStep(1, 0),)
        self.workspace.set_cursor(GameTreeCursor(first_path, 2))
        self.workspace.enter_variation(0)
        nested_path = first_path + (VariationStep(1, 0),)
        self.assertEqual(self.workspace.cursor, GameTreeCursor(nested_path, 0))
        self.assertEqual(self.workspace.current_move().san, "d6")
        self.workspace.leave_variation()
        self.assertEqual(self.workspace.cursor, GameTreeCursor(first_path, 2))

    def test_sibling_variation_boundary_fails_without_cursor_mutation(self):
        self.workspace.set_cursor(GameTreeCursor((), 2))
        self.workspace.enter_variation(0)
        before = self.workspace.view()
        with self.assertRaises(PgnWorkspaceError) as caught:
            self.workspace.sibling_variation(-1)
        self.assertEqual(caught.exception.code, PgnWorkspaceErrorCode.NO_VARIATION)
        self.assertEqual(self.workspace.view(), before)

    def test_annotation_edit_marks_dirty_increments_revision_and_preserves_other_game(self):
        other_before = deepcopy(self.workspace.games()[1])
        game = self.workspace.current_game()
        target = move_annotation_target(game, (), 0)
        self.workspace.edit_move_annotations(
            target,
            MoveAnnotationPatch(comments_after=(Comment("workspace note"),), nags=("!",)),
        )
        self.assertTrue(self.workspace.dirty)
        self.assertEqual(self.workspace.content_revision, 1)
        edited = self.workspace.current_game().line.moves[0]
        self.assertEqual([c.text for c in edited.comments_after], ["workspace note"])
        self.assertEqual(edited.nags, ["!"])
        self.assertEqual(self.workspace.games()[1], other_before)

        self.workspace.mark_saved()
        self.assertFalse(self.workspace.dirty)
        self.assertEqual(self.workspace.content_revision, 1)

    def test_stale_annotation_target_fails_without_partial_workspace_mutation(self):
        game = self.workspace.current_game()
        stale = move_annotation_target(game, (), 0)
        fresh = move_annotation_target(game, (), 1)
        self.workspace.edit_move_annotations(
            fresh,
            MoveAnnotationPatch(comments_after=(Comment("first edit"),)),
        )
        before = self.workspace.to_text()
        revision = self.workspace.content_revision

        with self.assertRaises(AnnotationEditError) as caught:
            self.workspace.edit_move_annotations(
                stale,
                MoveAnnotationPatch(comments_after=(Comment("stale edit"),)),
            )
        self.assertEqual(caught.exception.code, AnnotationEditCode.STALE_REVISION)
        self.assertEqual(self.workspace.to_text(), before)
        self.assertEqual(self.workspace.content_revision, revision)

    def test_inserting_before_active_sibling_remaps_workspace_cursor(self):
        sibling_path = (VariationStep(1, 1),)
        self.workspace.set_cursor(GameTreeCursor(sibling_path, 1))
        game = self.workspace.current_game()
        target = variation_insert_target(game, (), 1, 0)
        result = self.workspace.add_variation(
            target,
            VariationLine(moves=[MoveNode("d5"), MoveNode("exd5")]),
        )
        self.assertEqual(result.inserted_path, (VariationStep(1, 0),))
        self.assertEqual(self.workspace.cursor, GameTreeCursor((VariationStep(1, 2),), 1))
        self.assertEqual(self.workspace.current_move().san, "d4")
        self.assertTrue(self.workspace.dirty)

    def test_delete_active_variation_falls_back_after_owning_move(self):
        active_path = (VariationStep(1, 0),)
        self.workspace.set_cursor(GameTreeCursor(active_path, 1))
        target = variation_edit_target(self.workspace.current_game(), (), 1, 0)
        self.workspace.delete_variation(target)
        self.assertEqual(self.workspace.cursor, GameTreeCursor((), 2))
        self.assertEqual(self.workspace.current_move().san, "Nf3")
        self.assertEqual(len(self.workspace.current_game().line.moves[1].variations), 1)

    def test_reorder_variation_preserves_cursor_on_same_semantic_line(self):
        active_path = (VariationStep(1, 1),)
        self.workspace.set_cursor(GameTreeCursor(active_path, 1))
        target = variation_edit_target(self.workspace.current_game(), (), 1, 1)
        self.workspace.reorder_variation(target, 0)
        self.assertEqual(self.workspace.cursor, GameTreeCursor((VariationStep(1, 0),), 1))
        self.assertEqual(resolve_line(self.workspace.current_game(), (VariationStep(1, 0),)).moves[0].san, "c6")

    def test_promote_variation_remaps_cursor_into_promoted_mainline(self):
        active_path = (VariationStep(1, 0),)
        self.workspace.set_cursor(GameTreeCursor(active_path, 1))
        target = variation_edit_target(self.workspace.current_game(), (), 1, 0)
        self.workspace.promote_variation(target)
        self.assertEqual(self.workspace.cursor, GameTreeCursor((), 2))
        root = self.workspace.current_game().line
        self.assertEqual([move.san for move in root.moves[:4]], ["e4", "c5", "Nf3", "Nc6"])

    def test_document_start_end_are_cross_game_session_navigation_only(self):
        self.workspace.document_end()
        self.assertEqual(self.workspace.selected_game_index, 1)
        self.assertIsNone(self.workspace.current_move())
        self.workspace.document_start()
        self.assertEqual(self.workspace.selected_game_index, 0)
        self.assertEqual(self.workspace.cursor, GameTreeCursor())
        self.assertFalse(self.workspace.dirty)

    def test_invalid_recovery_document_is_rejected_at_workspace_boundary(self):
        malformed = '[Event "bad"]\n\n1. e4 (1... c5 2. Nf3 *\n'
        with self.assertRaises(PgnWorkspaceError) as caught:
            PgnWorkspace.from_text(malformed)
        self.assertEqual(caught.exception.code, PgnWorkspaceErrorCode.INVALID_DOCUMENT)


if __name__ == "__main__":
    unittest.main()
