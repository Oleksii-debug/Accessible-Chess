import unittest
from dataclasses import replace

from acs.history import (
    HISTORY_TREE_SCHEMA_VERSION,
    HistoryError,
    HistoryErrorCode,
    HistoryNodeRecord,
    HistoryTreeSnapshot,
    PositionSnapshot,
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

    def test_snapshot_inputs_require_exact_types_and_invalid_append_is_atomic(self):
        for invalid_fen in (None, True, 17, b"fen", "   "):
            with self.subTest(kind="initial", value=invalid_fen):
                with self.assertRaises(HistoryError) as caught:
                    ReviewHistory(invalid_fen)
                self.assertEqual(caught.exception.code, HistoryErrorCode.INVALID_SNAPSHOT)

        history = self.make_history(2)
        before = history.export_tree()
        cases = (
            {"fen": None},
            {"fen": "fen-3", "san": 3},
            {"fen": "fen-3", "san": "  "},
            {"fen": "fen-3", "last_move": False},
            {"fen": "fen-3", "side": "white"},
            {"fen": "fen-3", "context": [("unsafe", True)]},
        )
        for kwargs in cases:
            with self.subTest(kind="append", kwargs=kwargs):
                with self.assertRaises(HistoryError) as caught:
                    history.append(**kwargs)
                self.assertEqual(caught.exception.code, HistoryErrorCode.INVALID_SNAPSHOT)
                self.assertEqual(history.export_tree(), before)

    def test_snapshot_context_is_copied_and_top_level_read_only(self):
        source = {"token": 1}
        history = ReviewHistory("root", context=source)
        source["token"] = 2

        snapshot = history.current().snapshot
        self.assertEqual(snapshot.context["token"], 1)
        with self.assertRaises(TypeError):
            snapshot.context["token"] = 3

        exported = history.export_tree().nodes[0].snapshot
        self.assertEqual(exported.context["token"], 1)
        self.assertIsNot(exported.context, snapshot.context)

    def test_versioned_tree_rejects_boolean_and_container_coercion(self):
        tree = self.make_history(2).export_tree()
        cases = (
            replace(tree, schema_version=True),
            replace(tree, cursor_node_id=True),
            replace(tree, nodes=list(tree.nodes)),
            replace(tree, nodes=(object(),) + tree.nodes[1:]),
            replace(
                tree,
                nodes=(replace(tree.nodes[0], node_id=False),) + tree.nodes[1:],
            ),
            replace(
                tree,
                nodes=(replace(tree.nodes[0], child_ids=(True,)),) + tree.nodes[1:],
            ),
            replace(
                tree,
                nodes=(replace(tree.nodes[0], active_child=True),) + tree.nodes[1:],
            ),
            replace(
                tree,
                nodes=(
                    tree.nodes[0],
                    replace(tree.nodes[1], parent_id=False),
                    *tree.nodes[2:],
                ),
            ),
            replace(
                tree,
                nodes=(replace(tree.nodes[0], child_ids=[1]),) + tree.nodes[1:],
            ),
        )
        for invalid in cases:
            with self.subTest(invalid=invalid):
                with self.assertRaises(HistoryError) as caught:
                    ReviewHistory.from_tree(invalid)
                self.assertIn(
                    caught.exception.code,
                    {
                        HistoryErrorCode.UNSUPPORTED_SCHEMA,
                        HistoryErrorCode.INVALID_TREE,
                    },
                )

    def test_disconnected_parent_cycle_is_rejected_before_restore(self):
        snapshot = PositionSnapshot("fen")
        tree = HistoryTreeSnapshot(
            schema_version=HISTORY_TREE_SCHEMA_VERSION,
            nodes=(
                HistoryNodeRecord(0, None, (), None, snapshot),
                HistoryNodeRecord(1, 2, (2,), 2, snapshot),
                HistoryNodeRecord(2, 1, (1,), 1, snapshot),
            ),
            cursor_node_id=0,
        )

        with self.assertRaises(HistoryError) as caught:
            ReviewHistory.from_tree(tree)

        self.assertEqual(caught.exception.code, HistoryErrorCode.INVALID_TREE)
        self.assertIn("unreachable", str(caught.exception))

    def test_boolean_variation_index_never_selects_a_branch(self):
        history = self.make_history(3)
        history.previous()
        history.append("branch", san="branch", side="w")
        history.previous()
        before = history.current()

        with self.assertRaises(HistoryError) as caught:
            history.select_variation(True)

        self.assertEqual(caught.exception.code, HistoryErrorCode.INVALID_COMMAND)
        self.assertEqual(history.current(), before)


if __name__ == "__main__":
    unittest.main()
