from __future__ import annotations

import unittest
from collections.abc import Iterator, Mapping

from acs.history import (
    HISTORY_TREE_SCHEMA_VERSION,
    HistoryError,
    HistoryErrorCode,
    HistoryNodeRecord,
    HistoryTreeSnapshot,
    PositionSnapshot,
    ReviewHistory,
)


class HistoryTreePassiveBoundaryCurrentTests(unittest.TestCase):
    def test_append_branch_rejects_snapshot_subclass_before_field_access(self) -> None:
        class HostileSnapshot(PositionSnapshot):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if (
                    name in {"fen", "san", "side", "last_move", "context"}
                    and type(self).armed
                ):
                    type(self).touched = True
                    raise AssertionError("hostile snapshot field hook must not execute")
                return super().__getattribute__(name)

        hostile = HostileSnapshot("branch")
        HostileSnapshot.armed = True

        history = ReviewHistory("root")
        before = history.export_tree()

        with self.assertRaises(HistoryError) as caught:
            history.append_branch(0, (hostile,))

        self.assertEqual(caught.exception.code, HistoryErrorCode.INVALID_SNAPSHOT)
        self.assertEqual(history.export_tree(), before)
        self.assertFalse(HostileSnapshot.touched)

    def test_tree_subclass_is_rejected_before_field_access(self) -> None:
        class HostileTree(HistoryTreeSnapshot):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if (
                    name in {"schema_version", "nodes", "cursor_node_id"}
                    and type(self).armed
                ):
                    type(self).touched = True
                    raise AssertionError("hostile tree field hook must not execute")
                return super().__getattribute__(name)

        valid = ReviewHistory("root").export_tree()
        hostile = HostileTree(
            valid.schema_version,
            valid.nodes,
            valid.cursor_node_id,
        )
        HostileTree.armed = True

        with self.assertRaises(HistoryError) as caught:
            ReviewHistory.from_tree(hostile)

        self.assertEqual(caught.exception.code, HistoryErrorCode.INVALID_TREE)
        self.assertFalse(HostileTree.touched)

    def test_node_record_subclass_is_rejected_before_field_access(self) -> None:
        class HostileRecord(HistoryNodeRecord):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if (
                    name in {
                        "node_id",
                        "parent_id",
                        "child_ids",
                        "active_child",
                        "snapshot",
                    }
                    and type(self).armed
                ):
                    type(self).touched = True
                    raise AssertionError("hostile record field hook must not execute")
                return super().__getattribute__(name)

        record = HostileRecord(
            0,
            None,
            (),
            None,
            PositionSnapshot("root"),
        )
        HostileRecord.armed = True
        tree = HistoryTreeSnapshot(
            HISTORY_TREE_SCHEMA_VERSION,
            (record,),
            0,
        )

        with self.assertRaises(HistoryError) as caught:
            ReviewHistory.from_tree(tree)

        self.assertEqual(caught.exception.code, HistoryErrorCode.INVALID_TREE)
        self.assertFalse(HostileRecord.touched)

    def test_mutated_schema_and_child_integer_subclasses_are_passive_rejections(self) -> None:
        class HostileInt(int):
            touched = False

            def _touch(self):
                type(self).touched = True
                raise AssertionError("hostile integer hook must not execute")

            __eq__ = lambda self, other: self._touch()
            __hash__ = lambda self: self._touch()
            __lt__ = lambda self, other: self._touch()
            __le__ = lambda self, other: self._touch()
            __gt__ = lambda self, other: self._touch()
            __ge__ = lambda self, other: self._touch()
            __str__ = lambda self: self._touch()
            __format__ = lambda self, spec: self._touch()

        schema_tree = ReviewHistory("root").export_tree()
        object.__setattr__(schema_tree, "schema_version", HostileInt(1))

        with self.assertRaises(HistoryError) as caught:
            ReviewHistory.from_tree(schema_tree)

        self.assertEqual(caught.exception.code, HistoryErrorCode.UNSUPPORTED_SCHEMA)
        self.assertFalse(HostileInt.touched)

        history = ReviewHistory("root")
        history.append("after")
        child_tree = history.export_tree()
        object.__setattr__(child_tree.nodes[0], "child_ids", (HostileInt(1),))

        with self.assertRaises(HistoryError) as caught:
            ReviewHistory.from_tree(child_tree)

        self.assertEqual(caught.exception.code, HistoryErrorCode.INVALID_TREE)
        self.assertFalse(HostileInt.touched)

    def test_mutated_snapshot_text_and_context_are_rejected_before_hooks(self) -> None:
        class HostileText(str):
            touched = False

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile snapshot text hook must not execute")

            def __eq__(self, other):
                type(self).touched = True
                raise AssertionError("hostile snapshot equality hook must not execute")

        class HostileMapping(Mapping[str, object]):
            touched = False

            def __getitem__(self, key: str) -> object:
                type(self).touched = True
                raise AssertionError("hostile mapping value hook must not execute")

            def __iter__(self) -> Iterator[str]:
                type(self).touched = True
                raise AssertionError("hostile mapping iterator hook must not execute")

            def __len__(self) -> int:
                type(self).touched = True
                raise AssertionError("hostile mapping length hook must not execute")

        text_tree = ReviewHistory("root").export_tree()
        object.__setattr__(text_tree.nodes[0].snapshot, "fen", HostileText("root"))

        with self.assertRaises(HistoryError) as caught:
            ReviewHistory.from_tree(text_tree)

        self.assertEqual(caught.exception.code, HistoryErrorCode.INVALID_SNAPSHOT)
        self.assertFalse(HostileText.touched)

        context_tree = ReviewHistory("root").export_tree()
        object.__setattr__(
            context_tree.nodes[0].snapshot,
            "context",
            HostileMapping(),
        )

        with self.assertRaises(HistoryError) as caught:
            ReviewHistory.from_tree(context_tree)

        self.assertEqual(caught.exception.code, HistoryErrorCode.INVALID_SNAPSHOT)
        self.assertFalse(HostileMapping.touched)

    def test_exact_export_roundtrip_and_branch_insert_semantics_remain_unchanged(self) -> None:
        history = ReviewHistory("root")
        history.append("after-e4", san="e4", side="w", last_move="e4")
        exported = history.export_tree()

        restored = ReviewHistory.from_tree(exported)
        self.assertEqual(restored.export_tree(), exported)

        before_cursor = restored.current()
        inserted = restored.append_branch(
            0,
            (PositionSnapshot("branch", san="d4", side="w", last_move="d4"),),
        )
        self.assertEqual(inserted.created_count, 1)
        self.assertEqual(restored.current(), before_cursor)


if __name__ == "__main__":
    unittest.main()
