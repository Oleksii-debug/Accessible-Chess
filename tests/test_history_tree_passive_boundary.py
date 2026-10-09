from __future__ import annotations

import unittest

from acs.history import (
    HISTORY_TREE_SCHEMA_VERSION,
    HistoryError,
    HistoryNodeRecord,
    HistoryTreeSnapshot,
    PositionSnapshot,
    ReviewHistory,
)


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _root_snapshot() -> PositionSnapshot:
    return PositionSnapshot(START_FEN)


def _root_record(*, child_ids: tuple[int, ...] = (), active_child: int | None = None) -> HistoryNodeRecord:
    return HistoryNodeRecord(
        node_id=0,
        parent_id=None,
        child_ids=child_ids,
        active_child=active_child,
        snapshot=_root_snapshot(),
    )


class HistoryTreePassiveBoundaryTests(unittest.TestCase):
    def test_valid_exact_export_round_trips(self) -> None:
        history = ReviewHistory(START_FEN)
        exported = history.export_tree()

        restored = ReviewHistory.from_tree(exported)

        self.assertEqual(restored.export_tree(), exported)

    def test_tree_subclass_is_rejected_before_attribute_hooks(self) -> None:
        class HostileTree(HistoryTreeSnapshot):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if type(self).armed and name in {"schema_version", "nodes", "cursor_node_id"}:
                    type(self).touched = True
                    raise AssertionError("history tree attribute hook must not execute")
                return super().__getattribute__(name)

        hostile = HostileTree(HISTORY_TREE_SCHEMA_VERSION, (_root_record(),), 0)
        HostileTree.armed = True

        with self.assertRaisesRegex(HistoryError, "snapshot type is invalid"):
            ReviewHistory.from_tree(hostile)

        self.assertFalse(HostileTree.touched)

    def test_node_record_subclass_is_rejected_before_attribute_hooks(self) -> None:
        class HostileRecord(HistoryNodeRecord):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if type(self).armed and name in {
                    "node_id",
                    "parent_id",
                    "child_ids",
                    "active_child",
                    "snapshot",
                }:
                    type(self).touched = True
                    raise AssertionError("history node attribute hook must not execute")
                return super().__getattribute__(name)

        hostile = HostileRecord(0, None, (), None, _root_snapshot())
        HostileRecord.armed = True
        tree = HistoryTreeSnapshot(HISTORY_TREE_SCHEMA_VERSION, (hostile,), 0)

        with self.assertRaisesRegex(HistoryError, "invalid node record"):
            ReviewHistory.from_tree(tree)

        self.assertFalse(HostileRecord.touched)

    def test_snapshot_subclass_is_rejected_before_snapshot_attribute_hooks(self) -> None:
        class HostileSnapshot(PositionSnapshot):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if type(self).armed and name in {
                    "fen",
                    "san",
                    "side",
                    "last_move",
                    "context",
                }:
                    type(self).touched = True
                    raise AssertionError("history snapshot attribute hook must not execute")
                return super().__getattribute__(name)

        hostile = HostileSnapshot(START_FEN)
        HostileSnapshot.armed = True
        record = HistoryNodeRecord(0, None, (), None, hostile)
        tree = HistoryTreeSnapshot(HISTORY_TREE_SCHEMA_VERSION, (record,), 0)

        with self.assertRaisesRegex(HistoryError, "invalid snapshot"):
            ReviewHistory.from_tree(tree)

        self.assertFalse(HostileSnapshot.touched)

    def test_snapshot_context_dict_subclass_is_rejected_before_mapping_hooks(self) -> None:
        class HostileDict(dict):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("history context length hook must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("history context iteration hook must not execute")

            def items(self):
                type(self).touched = True
                raise AssertionError("history context items hook must not execute")

        hostile = HostileDict({"source": "provider"})

        with self.assertRaisesRegex(HistoryError, "context must be a mapping"):
            PositionSnapshot(START_FEN, context=hostile)

        self.assertFalse(HostileDict.touched)

    def test_nested_context_dict_subclass_is_rejected_before_mapping_hooks(self) -> None:
        class HostileDict(dict):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("nested history context length hook must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("nested history context iteration hook must not execute")

            def items(self):
                type(self).touched = True
                raise AssertionError("nested history context items hook must not execute")

        hostile = HostileDict({"leaf": True})

        with self.assertRaisesRegex(HistoryError, "unsupported mutable/object value"):
            PositionSnapshot(START_FEN, context={"nested": hostile})

        self.assertFalse(HostileDict.touched)

    def test_nodes_tuple_subclass_is_rejected_before_len_or_iteration_hooks(self) -> None:
        class HostileTuple(tuple):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("history tuple length hook must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("history tuple iteration hook must not execute")

        hostile_nodes = HostileTuple((_root_record(),))
        tree = HistoryTreeSnapshot(HISTORY_TREE_SCHEMA_VERSION, hostile_nodes, 0)

        with self.assertRaisesRegex(HistoryError, "non-empty exact tuple"):
            ReviewHistory.from_tree(tree)

        self.assertFalse(HostileTuple.touched)

    def test_child_tuple_subclass_is_rejected_before_len_hash_or_iteration_hooks(self) -> None:
        class HostileTuple(tuple):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("child tuple length hook must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("child tuple iteration hook must not execute")

        hostile_children = HostileTuple((1,))
        root = HistoryNodeRecord(0, None, hostile_children, None, _root_snapshot())
        child = HistoryNodeRecord(1, 0, (), None, _root_snapshot())
        tree = HistoryTreeSnapshot(HISTORY_TREE_SCHEMA_VERSION, (root, child), 0)

        with self.assertRaisesRegex(HistoryError, "children must be an exact tuple"):
            ReviewHistory.from_tree(tree)

        self.assertFalse(HostileTuple.touched)

    def test_schema_integer_subclass_is_rejected_before_numeric_or_text_hooks(self) -> None:
        class HostileInt(int):
            touched = False

            @classmethod
            def _touch(cls):
                cls.touched = True
                raise AssertionError("history integer hook must not execute")

            def __eq__(self, other):
                type(self)._touch()

            def __ne__(self, other):
                type(self)._touch()

            def __lt__(self, other):
                type(self)._touch()

            def __ge__(self, other):
                type(self)._touch()

            def __hash__(self):
                type(self)._touch()

            def __str__(self):
                type(self)._touch()

        tree = HistoryTreeSnapshot(HostileInt(1), (_root_record(),), 0)

        with self.assertRaisesRegex(HistoryError, "unsupported history tree schema"):
            ReviewHistory.from_tree(tree)

        self.assertFalse(HostileInt.touched)

    def test_child_integer_subclass_is_rejected_before_set_hashing(self) -> None:
        class HostileInt(int):
            touched = False

            def __hash__(self):
                type(self).touched = True
                raise AssertionError("child ID hash hook must not execute")

            def __eq__(self, other):
                type(self).touched = True
                raise AssertionError("child ID equality hook must not execute")

            def __le__(self, other):
                type(self).touched = True
                raise AssertionError("child ID ordering hook must not execute")

            def __ge__(self, other):
                type(self).touched = True
                raise AssertionError("child ID ordering hook must not execute")

        root = HistoryNodeRecord(
            0,
            None,
            (HostileInt(1),),
            None,
            _root_snapshot(),
        )
        child = HistoryNodeRecord(1, 0, (), None, _root_snapshot())
        tree = HistoryTreeSnapshot(HISTORY_TREE_SCHEMA_VERSION, (root, child), 0)

        with self.assertRaisesRegex(HistoryError, "non-exact-integer child"):
            ReviewHistory.from_tree(tree)

        self.assertFalse(HostileInt.touched)

    def test_append_branch_rejects_snapshot_subclass_before_attribute_hooks_and_mutation(self) -> None:
        class HostileSnapshot(PositionSnapshot):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if (
                    type(self).armed
                    and name in {"fen", "san", "side", "last_move", "context"}
                ):
                    type(self).touched = True
                    raise AssertionError("branch snapshot attribute hook must not execute")
                return super().__getattribute__(name)

        hostile = HostileSnapshot(START_FEN)
        HostileSnapshot.armed = True
        history = ReviewHistory(START_FEN)
        before = history.export_tree()

        with self.assertRaisesRegex(HistoryError, "invalid snapshot"):
            history.append_branch(0, (hostile,))

        self.assertEqual(history.export_tree(), before)
        self.assertFalse(HostileSnapshot.touched)

    def test_cursor_parent_and_active_child_require_exact_integers(self) -> None:
        class HostileInt(int):
            touched = False

            def __hash__(self):
                type(self).touched = True
                raise AssertionError("history integer hash hook must not execute")

            def __eq__(self, other):
                type(self).touched = True
                raise AssertionError("history integer equality hook must not execute")

            def __lt__(self, other):
                type(self).touched = True
                raise AssertionError("history integer ordering hook must not execute")

            def __ge__(self, other):
                type(self).touched = True
                raise AssertionError("history integer ordering hook must not execute")

        cases = (
            HistoryTreeSnapshot(HISTORY_TREE_SCHEMA_VERSION, (_root_record(),), HostileInt(0)),
            HistoryTreeSnapshot(
                HISTORY_TREE_SCHEMA_VERSION,
                (
                    HistoryNodeRecord(0, None, (1,), 1, _root_snapshot()),
                    HistoryNodeRecord(1, HostileInt(0), (), None, _root_snapshot()),
                ),
                0,
            ),
            HistoryTreeSnapshot(
                HISTORY_TREE_SCHEMA_VERSION,
                (
                    HistoryNodeRecord(0, None, (1,), HostileInt(1), _root_snapshot()),
                    HistoryNodeRecord(1, 0, (), None, _root_snapshot()),
                ),
                0,
            ),
        )

        for index, tree in enumerate(cases):
            HostileInt.touched = False
            with self.subTest(index=index):
                with self.assertRaises(HistoryError):
                    ReviewHistory.from_tree(tree)
                self.assertFalse(HostileInt.touched)


if __name__ == "__main__":
    unittest.main()
