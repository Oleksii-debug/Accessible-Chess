from __future__ import annotations

from copy import deepcopy
import unittest

from acs.game_identity import identity_for_game
from acs.gametree_editing import (
    GameTreeEditCode,
    GameTreeEditError,
    delete_variation,
    promote_variation,
    reorder_variation,
    variation_edit_target,
)
from acs.gametree_navigation import (
    GameTreeCursor,
    VariationStep,
    enter_variation,
    leave_variation,
    resolve_line,
    validate_cursor,
)
from acs.pgn_roundtrip import parse_pgn_text, serialize_pgn_text


EDIT_CORPUS = '''[Event "D06 editing persistence"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 {root e4} e5 $1
(1... c5!? {Sicilian} 2. Nf3 (2... d6?! {nested}) 2... Nc6)
(1... e6 {French} 2. d4 d5)
2. Nf3 {main knight} Nc6 *

[Event "Untouched sibling game"]
[White "Gamma"]
[Black "Delta"]
[Result "1/2-1/2"]

1. d4 d5 2. c4 e6 1/2-1/2
'''


class D06GameTreePersistenceVerticalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.games = parse_pgn_text(EDIT_CORPUS)
        self.game = self.games[0]

    def assert_strict_roundtrip_equal(self, games):
        serialized = serialize_pgn_text(games)
        reparsed = parse_pgn_text(serialized)
        self.assertEqual(reparsed, tuple(games))
        return serialized, reparsed

    def test_promote_nested_rav_persists_and_remapped_cursors_resolve_after_reparse(self):
        original = deepcopy(self.game)
        target = variation_edit_target(self.game, (), 1, 0)
        selected_path = target.child_path
        selected_cursor = GameTreeCursor(selected_path, 1)
        old_mainline_cursor = GameTreeCursor((), 3)

        result = promote_variation(self.game, target)
        edited = result.game

        # Copy-on-write: persistence editing never mutates the caller's source.
        self.assertEqual(self.game, original)
        self.assertNotEqual(identity_for_game(edited), identity_for_game(self.game))
        self.assertEqual([move.san for move in edited.line.moves], ["e4", "c5", "Nf3"])

        promoted_first = edited.line.moves[1]
        self.assertEqual(promoted_first.nags, ["!?"])
        self.assertEqual(promoted_first.comments_after[0].text, "Sicilian")
        self.assertGreaterEqual(len(promoted_first.variations), 2)

        mapped_selected = result.remap_cursor(selected_cursor)
        mapped_old_mainline = result.remap_cursor(old_mainline_cursor)
        self.assertEqual(mapped_selected, GameTreeCursor((), 2))
        self.assertIsNotNone(mapped_old_mainline)

        _, reparsed = self.assert_strict_roundtrip_equal((edited,))
        restored = reparsed[0]
        self.assertEqual(validate_cursor(restored, mapped_selected), mapped_selected)
        self.assertEqual(validate_cursor(restored, mapped_old_mainline), mapped_old_mainline)

        # The nested RAV under the promoted Sicilian line remains nested after
        # structural promotion, serialization and reparsing.
        nested_lines = [
            variation
            for move in restored.line.moves
            for variation in move.variations
            for child_move in variation.moves
            for variation in child_move.variations
        ]
        self.assertTrue(
            any(
                any(move.san == "d6" and "?!" in move.nags for move in line.moves)
                for line in nested_lines
            )
        )

    def test_reorder_then_delete_sibling_rav_persist_without_touching_source(self):
        original = deepcopy(self.game)
        first = resolve_line(self.game, (VariationStep(1, 0),))
        second = resolve_line(self.game, (VariationStep(1, 1),))
        self.assertEqual(first.moves[0].san, "c5")
        self.assertEqual(second.moves[0].san, "e6")

        reorder_target = variation_edit_target(self.game, (), 1, 1)
        reordered = reorder_variation(self.game, reorder_target, 0).game
        self.assertEqual(self.game, original)
        self.assertEqual(
            [line.moves[0].san for line in reordered.line.moves[1].variations],
            ["e6", "c5"],
        )
        _, reparsed_reordered = self.assert_strict_roundtrip_equal((reordered,))

        delete_target = variation_edit_target(reparsed_reordered[0], (), 1, 1)
        deleted = delete_variation(reparsed_reordered[0], delete_target).game
        self.assertEqual(
            [line.moves[0].san for line in deleted.line.moves[1].variations],
            ["e6"],
        )
        _, reparsed_deleted = self.assert_strict_roundtrip_equal((deleted,))
        self.assertEqual(
            reparsed_deleted[0].line.moves[1].variations[0].moves[0].comments_after[0].text,
            "French",
        )

    def test_stale_edit_target_fails_atomically_after_prior_edit(self):
        stale = variation_edit_target(self.game, (), 1, 0)
        reordered = reorder_variation(
            self.game,
            variation_edit_target(self.game, (), 1, 1),
            0,
        ).game
        before = deepcopy(reordered)

        with self.assertRaises(GameTreeEditError) as caught:
            delete_variation(reordered, stale)
        self.assertEqual(caught.exception.code, GameTreeEditCode.STALE_REVISION)
        self.assertEqual(reordered, before)

    def test_multigame_edit_isolation_survives_write_and_reparse(self):
        untouched_before = deepcopy(self.games[1])
        edited_first = reorder_variation(
            self.games[0],
            variation_edit_target(self.games[0], (), 1, 1),
            0,
        ).game

        serialized, reparsed = self.assert_strict_roundtrip_equal(
            (edited_first, self.games[1])
        )
        self.assertIn('[Event "Untouched sibling game"]', serialized)
        self.assertEqual(self.games[1], untouched_before)
        self.assertEqual(reparsed[1], untouched_before)
        self.assertEqual(reparsed[0].source_index, 0)
        self.assertEqual(reparsed[1].source_index, 1)

    def test_branch_enter_leave_navigation_contract_survives_serialization(self):
        root_after_owner = GameTreeCursor((), 2)
        child_start = enter_variation(self.game, root_after_owner, 0)
        self.assertEqual(child_start.line_path, (VariationStep(1, 0),))
        self.assertEqual(leave_variation(self.game, child_start), root_after_owner)

        _, reparsed = self.assert_strict_roundtrip_equal((self.game,))
        restored = reparsed[0]
        restored_child = enter_variation(restored, root_after_owner, 0)
        self.assertEqual(restored_child, child_start)
        self.assertEqual(leave_variation(restored, restored_child), root_after_owner)

    def test_promote_then_roundtrip_preserves_all_comment_and_nag_payloads(self):
        promoted = promote_variation(
            self.game,
            variation_edit_target(self.game, (), 1, 0),
        ).game
        _, reparsed = self.assert_strict_roundtrip_equal((promoted,))
        text = serialize_pgn_text(reparsed)

        for payload in ("root e4", "Sicilian", "nested", "main knight", "French"):
            self.assertIn(payload, text)
        for nag in ("$1", "!?", "?!"):
            self.assertIn(nag, text)


if __name__ == "__main__":
    unittest.main()
