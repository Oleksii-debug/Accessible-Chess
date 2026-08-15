import unittest
from dataclasses import replace

from acs.history import (
    HISTORY_TREE_SCHEMA_VERSION,
    HistoryError,
    ReviewHistory,
)


class ReviewHistoryTests(unittest.TestCase):
    def make_history(self, plies=8):
        h = ReviewHistory("fen-0")
        for ply in range(1, plies + 1):
            side = "w" if ply % 2 else "b"
            move_no = (ply + 1) // 2
            h.append(
                f"fen-{ply}",
                san=f"m{ply}",
                side=side,
                last_move=f"{move_no}{side}",
                context={"token": ply},
            )
        return h

    def test_previous_next_are_reversible_and_non_destructive(self):
        h = self.make_history(8)
        original_count = h.node_count
        original_line = [s.fen for s in h.active_line()]

        back = h.previous()
        self.assertEqual(back.ply, 7)
        self.assertEqual(back.snapshot.fen, "fen-7")
        back = h.previous()
        self.assertEqual(back.snapshot.fen, "fen-6")
        forward = h.next()
        self.assertEqual(forward.snapshot.fen, "fen-7")
        forward = h.next()
        self.assertEqual(forward.snapshot.fen, "fen-8")

        self.assertEqual(h.node_count, original_count)
        self.assertEqual([s.fen for s in h.active_line()], original_line)

    def test_boundaries_are_explicit(self):
        h = self.make_history(2)
        h.jump("start")
        with self.assertRaisesRegex(HistoryError, "initial"):
            h.previous()
        h.jump("end")
        with self.assertRaisesRegex(HistoryError, "end"):
            h.next()

    def test_direct_jump_parser(self):
        h = self.make_history(40)
        self.assertEqual(h.jump("start").ply, 0)
        self.assertEqual(h.jump("0").ply, 0)
        self.assertEqual(h.jump("17w").ply, 33)
        self.assertEqual(h.jump("17b").ply, 34)
        self.assertEqual(h.jump("17...").ply, 34)
        self.assertEqual(h.jump("17").ply, 34)
        self.assertEqual(h.jump("end").ply, 40)

    def test_nonexistent_jump_does_not_corrupt_cursor(self):
        h = self.make_history(7)
        before = h.current()
        count = h.node_count
        with self.assertRaisesRegex(HistoryError, "does not exist"):
            h.jump("17")
        after = h.current()
        self.assertEqual(after.node_id, before.node_id)
        self.assertEqual(after.snapshot, before.snapshot)
        self.assertEqual(h.node_count, count)

    def test_invalid_target_does_not_change_state(self):
        h = self.make_history(4)
        before = h.current()
        with self.assertRaisesRegex(HistoryError, "invalid move target"):
            h.jump("seventeen")
        self.assertEqual(h.current(), before)

    def test_appending_from_review_position_creates_variation_not_truncation(self):
        h = self.make_history(6)
        original_count = h.node_count
        h.jump("2")
        old_future = h.variations()
        self.assertEqual(len(old_future), 1)
        self.assertEqual(old_future[0].fen, "fen-5")

        new = h.append("branch-fen-5", san="branch", side="w", last_move="3w")
        self.assertEqual(new.snapshot.fen, "branch-fen-5")
        self.assertEqual(h.node_count, original_count + 1)

        h.previous()
        variations = h.variations()
        self.assertEqual({s.fen for s in variations}, {"fen-5", "branch-fen-5"})

        self.assertEqual(h.next().snapshot.fen, "branch-fen-5")
        h.previous()
        old = h.select_variation(0)
        self.assertEqual(old.snapshot.fen, "fen-5")
        self.assertEqual(h.next().snapshot.fen, "fen-6")

    def test_context_and_last_move_follow_selected_history_position(self):
        h = self.make_history(5)
        selected = h.jump("2w")
        self.assertEqual(selected.snapshot.fen, "fen-3")
        self.assertEqual(selected.snapshot.last_move, "2w")
        self.assertEqual(selected.snapshot.context["token"], 3)

    def test_review_navigation_is_independent_from_external_undo_redo_state(self):
        h = self.make_history(5)
        external_undo_stack = ["a", "b", "c"]
        external_redo_stack = ["d"]
        h.previous()
        h.previous()
        h.next()
        self.assertEqual(external_undo_stack, ["a", "b", "c"])
        self.assertEqual(external_redo_stack, ["d"])

    def test_tree_snapshot_round_trip_preserves_exact_branch_identity_and_cursor(self):
        h = self.make_history(6)
        h.jump("2")
        h.append(
            "branch-fen-5",
            san="branch",
            side="w",
            last_move="3w",
            context={"token": "branch"},
        )
        branch_node = h.cursor_node_id
        h.previous()
        h.select_variation(0)
        h.next()
        old_line_end = h.cursor_node_id
        h.select_node(branch_node)

        exported = h.export_tree()
        restored = ReviewHistory.from_tree(exported)

        self.assertEqual(exported.schema_version, HISTORY_TREE_SCHEMA_VERSION)
        self.assertEqual(restored.export_tree(), exported)
        self.assertEqual(restored.cursor_node_id, branch_node)
        restored.select_node(old_line_end)
        self.assertEqual(restored.current().snapshot.fen, "fen-6")

    def test_tree_nodes_are_detached_from_mutable_tree_ownership(self):
        h = self.make_history(2)
        records = h.tree_nodes()
        self.assertEqual(records[1].parent_id, 0)
        self.assertEqual(records[0].child_ids, (1,))
        self.assertEqual(records[1].snapshot.context["token"], 1)
        self.assertIsNot(records[1].snapshot.context, h.tree_nodes()[1].snapshot.context)

    def test_select_node_activates_existing_branch_without_creating_nodes(self):
        h = self.make_history(4)
        h.jump("1")
        old_child = h.tree_nodes()[2].child_ids[0]
        h.append("branch-3", san="b3", side="w")
        count = h.node_count
        selected = h.select_node(old_child)
        self.assertEqual(selected.node_id, old_child)
        self.assertEqual(h.node_count, count)
        self.assertEqual(h.next().snapshot.fen, "fen-4")

    def test_tree_import_rejects_unsupported_schema_without_partial_state(self):
        tree = self.make_history(2).export_tree()
        bad = replace(tree, schema_version=999)
        with self.assertRaisesRegex(HistoryError, "unsupported history tree schema"):
            ReviewHistory.from_tree(bad)

    def test_tree_import_rejects_parent_child_disagreement(self):
        tree = self.make_history(2).export_tree()
        records = list(tree.nodes)
        records[1] = replace(records[1], parent_id=2)
        bad = replace(tree, nodes=tuple(records))
        with self.assertRaisesRegex(HistoryError, "parent/child links disagree"):
            ReviewHistory.from_tree(bad)

    def test_tree_import_rejects_active_child_outside_children(self):
        tree = self.make_history(2).export_tree()
        records = list(tree.nodes)
        records[0] = replace(records[0], active_child=2)
        bad = replace(tree, nodes=tuple(records))
        with self.assertRaisesRegex(HistoryError, "active child"):
            ReviewHistory.from_tree(bad)

    def test_tree_import_rejects_cursor_off_exported_active_line(self):
        h = self.make_history(4)
        h.jump("1")
        old_child = h.tree_nodes()[2].child_ids[0]
        h.append("branch-3", san="b3", side="w")
        tree = h.export_tree()
        bad = replace(tree, cursor_node_id=old_child)
        with self.assertRaisesRegex(HistoryError, "active line"):
            ReviewHistory.from_tree(bad)


if __name__ == "__main__":
    unittest.main()
