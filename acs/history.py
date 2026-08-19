from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping


class HistoryErrorCode(str, Enum):
    INVALID_COMMAND = "invalid_command"
    OUT_OF_RANGE = "out_of_range"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    INVALID_SNAPSHOT = "invalid_snapshot"
    INVALID_TREE = "invalid_tree"


class HistoryError(ValueError):
    """Raised when a requested review position cannot be selected."""

    def __init__(
        self,
        message: str,
        *,
        code: HistoryErrorCode = HistoryErrorCode.INVALID_COMMAND,
    ) -> None:
        super().__init__(message)
        self.code = HistoryErrorCode(code)


HISTORY_TREE_SCHEMA_VERSION = 1


def _freeze_context_value(value: Any, *, path: str = "context") -> Any:
    """Detach and recursively freeze context data accepted by review snapshots."""

    if value is None or type(value) in {str, int, float, bool, bytes}:
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise HistoryError(
                    f"{path} keys must be exact text",
                    code=HistoryErrorCode.INVALID_SNAPSHOT,
                )
            frozen[key] = _freeze_context_value(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if type(value) in {list, tuple}:
        return tuple(
            _freeze_context_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    if type(value) in {set, frozenset}:
        return frozenset(_freeze_context_value(item, path=path) for item in value)
    raise HistoryError(
        f"{path} contains unsupported mutable/object value {type(value).__name__}",
        code=HistoryErrorCode.INVALID_SNAPSHOT,
    )


@dataclass(frozen=True)
class PositionSnapshot:
    """Presentation-neutral state for one historical chess position."""

    fen: str
    san: str | None = None
    side: str | None = None
    last_move: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.fen, str) or not self.fen.strip():
            raise HistoryError(
                "snapshot FEN must be non-empty text",
                code=HistoryErrorCode.INVALID_SNAPSHOT,
            )
        object.__setattr__(self, "fen", self.fen.strip())
        for field_name in ("san", "last_move"):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise HistoryError(
                    f"snapshot {field_name} must be non-empty text or None",
                    code=HistoryErrorCode.INVALID_SNAPSHOT,
                )
        if self.side not in (None, "w", "b"):
            raise HistoryError(
                "snapshot side must be 'w', 'b', or None",
                code=HistoryErrorCode.INVALID_SNAPSHOT,
            )
        if not isinstance(self.context, Mapping):
            raise HistoryError(
                "snapshot context must be a mapping",
                code=HistoryErrorCode.INVALID_SNAPSHOT,
            )
        object.__setattr__(self, "context", _freeze_context_value(self.context))


@dataclass(frozen=True)
class HistoryNodeRecord:
    """Stable read-only node DTO for PGN/data adapters."""

    node_id: int
    parent_id: int | None
    child_ids: tuple[int, ...]
    active_child: int | None
    snapshot: PositionSnapshot


@dataclass(frozen=True)
class HistoryTreeSnapshot:
    """Versioned presentation-neutral exchange format for the review tree."""

    schema_version: int
    nodes: tuple[HistoryNodeRecord, ...]
    cursor_node_id: int


@dataclass
class _Node:
    snapshot: PositionSnapshot
    parent: int | None
    children: list[int] = field(default_factory=list)
    active_child: int | None = None


@dataclass(frozen=True)
class ReviewSelection:
    snapshot: PositionSnapshot
    ply: int
    at_start: bool
    at_end: bool
    node_id: int


class ReviewHistory:
    """Non-destructive game-history cursor with branch preservation.

    Review movement never removes nodes. Appending while reviewing an older
    position creates a sibling variation and makes that new variation active.
    ReviewHistory remains the single mutable owner of branch/tree identity;
    PGN and persistence layers exchange versioned immutable snapshots instead
    of maintaining a second game tree.
    """

    _MOVE_RE = re.compile(r"^(?P<num>[1-9]\d*)(?P<side>w|b|\.\.\.)?$", re.I)

    def __init__(self, initial_fen: str, *, context: Mapping[str, Any] | None = None):
        root = PositionSnapshot(
            initial_fen,
            context={} if context is None else context,
        )
        self._nodes: list[_Node] = [_Node(root, None)]
        self._cursor = 0

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def cursor_node_id(self) -> int:
        return self._cursor

    def current(self) -> ReviewSelection:
        path = self._active_path()
        try:
            ply = path.index(self._cursor)
        except ValueError:
            self._activate_lineage(self._cursor)
            path = self._active_path()
            ply = path.index(self._cursor)
        return self._selection(self._cursor, ply, path)

    def append(
        self,
        fen: str,
        *,
        san: str | None = None,
        side: str | None = None,
        last_move: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> ReviewSelection:
        snapshot = PositionSnapshot(
            fen,
            san=san,
            side=side,
            last_move=last_move,
            context={} if context is None else context,
        )
        parent_id = self._cursor
        node_id = len(self._nodes)
        self._nodes.append(_Node(snapshot, parent_id))
        parent = self._nodes[parent_id]
        parent.children.append(node_id)
        parent.active_child = node_id
        self._cursor = node_id
        self._activate_lineage(node_id)
        return self.current()

    def previous(self) -> ReviewSelection:
        parent = self._nodes[self._cursor].parent
        if parent is None:
            raise HistoryError(
                "already at the initial position",
                code=HistoryErrorCode.OUT_OF_RANGE,
            )
        self._cursor = parent
        return self.current()

    def next(self) -> ReviewSelection:
        child = self._nodes[self._cursor].active_child
        if child is None:
            raise HistoryError(
                "already at the end of the active line",
                code=HistoryErrorCode.OUT_OF_RANGE,
            )
        self._cursor = child
        return self.current()

    def jump(self, target: str | int) -> ReviewSelection:
        ply = self.parse_target(target)
        path = self._active_path()
        if ply >= len(path):
            raise HistoryError(
                f"requested ply {ply} does not exist; active line has {len(path)-1} plies",
                code=HistoryErrorCode.OUT_OF_RANGE,
            )
        self._cursor = path[ply]
        return self._selection(self._cursor, ply, path)

    def select_node(self, node_id: int) -> ReviewSelection:
        """Select any existing branch node by stable ID and activate its lineage."""
        if type(node_id) is not int:
            raise HistoryError("node_id must be an exact integer")
        if node_id < 0 or node_id >= len(self._nodes):
            raise HistoryError(
                "node_id does not exist",
                code=HistoryErrorCode.OUT_OF_RANGE,
            )
        self._cursor = node_id
        self._activate_lineage(node_id)
        return self.current()

    def select_variation(self, child_index: int) -> ReviewSelection:
        if type(child_index) is not int:
            raise HistoryError("variation index must be an exact integer")
        children = self._nodes[self._cursor].children
        if not children:
            raise HistoryError(
                "current position has no variations",
                code=HistoryErrorCode.OUT_OF_RANGE,
            )
        if child_index < 0 or child_index >= len(children):
            raise HistoryError(
                "variation index out of range",
                code=HistoryErrorCode.OUT_OF_RANGE,
            )
        chosen = children[child_index]
        self._nodes[self._cursor].active_child = chosen
        self._cursor = chosen
        self._activate_lineage(chosen)
        return self.current()

    def variations(self) -> tuple[PositionSnapshot, ...]:
        return tuple(self._nodes[node_id].snapshot for node_id in self._nodes[self._cursor].children)

    def active_line(self) -> tuple[PositionSnapshot, ...]:
        return tuple(self._nodes[node_id].snapshot for node_id in self._active_path())

    def tree_nodes(self) -> tuple[HistoryNodeRecord, ...]:
        """Return immutable node records without transferring tree ownership."""
        return tuple(
            HistoryNodeRecord(
                node_id=node_id,
                parent_id=node.parent,
                child_ids=tuple(node.children),
                active_child=node.active_child,
                snapshot=self._copy_snapshot(node.snapshot),
            )
            for node_id, node in enumerate(self._nodes)
        )

    def export_tree(self) -> HistoryTreeSnapshot:
        """Export exact branch identity/cursor for PGN or persistence adapters."""
        return HistoryTreeSnapshot(
            schema_version=HISTORY_TREE_SCHEMA_VERSION,
            nodes=self.tree_nodes(),
            cursor_node_id=self._cursor,
        )

    @classmethod
    def from_tree(cls, tree: HistoryTreeSnapshot) -> "ReviewHistory":
        """Restore an exact validated tree snapshot without filesystem concerns."""
        cls._validate_tree_snapshot(tree)
        root = tree.nodes[0].snapshot
        history = cls(root.fen, context=root.context)
        history._nodes = [
            _Node(
                snapshot=cls._copy_snapshot(record.snapshot),
                parent=record.parent_id,
                children=list(record.child_ids),
                active_child=record.active_child,
            )
            for record in tree.nodes
        ]
        history._cursor = tree.cursor_node_id
        return history

    def parse_target(self, target: str | int) -> int:
        if type(target) is int:
            if target < 0:
                raise HistoryError(
                    "move target must not be negative",
                    code=HistoryErrorCode.OUT_OF_RANGE,
                )
            text = str(target)
        elif type(target) is str:
            text = target.strip().lower()
        else:
            raise HistoryError("move target must be exact text or integer")

        if text in {"0", "start"}:
            return 0
        if text == "end":
            return len(self._active_path()) - 1

        match = self._MOVE_RE.fullmatch(text)
        if not match:
            raise HistoryError(
                "invalid move target; use 17, 17w, 17b, 17..., 0/start, or end"
            )

        move_no = int(match.group("num"))
        side = (match.group("side") or "").lower()
        if side == "w":
            return 2 * move_no - 1
        return 2 * move_no

    def _active_path(self) -> list[int]:
        path = [0]
        node_id = 0
        seen = {0}
        while True:
            child = self._nodes[node_id].active_child
            if child is None:
                break
            if child in seen:
                raise HistoryError(
                    "history tree contains a cycle",
                    code=HistoryErrorCode.INVALID_TREE,
                )
            path.append(child)
            seen.add(child)
            node_id = child
        return path

    def _activate_lineage(self, node_id: int) -> None:
        lineage: list[int] = []
        cur: int | None = node_id
        seen: set[int] = set()
        while cur is not None:
            if cur in seen:
                raise HistoryError(
                    "history tree contains a parent cycle",
                    code=HistoryErrorCode.INVALID_TREE,
                )
            if cur < 0 or cur >= len(self._nodes):
                raise HistoryError(
                    "history tree contains an invalid parent",
                    code=HistoryErrorCode.INVALID_TREE,
                )
            seen.add(cur)
            lineage.append(cur)
            cur = self._nodes[cur].parent
        lineage.reverse()
        for parent_id, child_id in zip(lineage, lineage[1:]):
            self._nodes[parent_id].active_child = child_id

    def _selection(self, node_id: int, ply: int, path: list[int]) -> ReviewSelection:
        return ReviewSelection(
            snapshot=self._nodes[node_id].snapshot,
            ply=ply,
            at_start=ply == 0,
            at_end=ply == len(path) - 1,
            node_id=node_id,
        )

    @staticmethod
    def _copy_snapshot(snapshot: PositionSnapshot) -> PositionSnapshot:
        return PositionSnapshot(
            fen=snapshot.fen,
            san=snapshot.san,
            side=snapshot.side,
            last_move=snapshot.last_move,
            context=snapshot.context,
        )

    @classmethod
    def _validate_tree_snapshot(cls, tree: HistoryTreeSnapshot) -> None:
        if not isinstance(tree, HistoryTreeSnapshot):
            raise HistoryError(
                "history tree snapshot type is invalid",
                code=HistoryErrorCode.INVALID_TREE,
            )
        if (
            not isinstance(tree.schema_version, int)
            or isinstance(tree.schema_version, bool)
            or tree.schema_version != HISTORY_TREE_SCHEMA_VERSION
        ):
            raise HistoryError(
                f"unsupported history tree schema {tree.schema_version}; "
                f"expected {HISTORY_TREE_SCHEMA_VERSION}",
                code=HistoryErrorCode.UNSUPPORTED_SCHEMA,
            )
        if not isinstance(tree.nodes, tuple) or not tree.nodes:
            raise HistoryError(
                "history tree nodes must be a non-empty tuple",
                code=HistoryErrorCode.INVALID_TREE,
            )
        if any(not isinstance(record, HistoryNodeRecord) for record in tree.nodes):
            raise HistoryError(
                "history tree contains an invalid node record",
                code=HistoryErrorCode.INVALID_TREE,
            )
        if (
            not isinstance(tree.cursor_node_id, int)
            or isinstance(tree.cursor_node_id, bool)
        ):
            raise HistoryError(
                "history cursor node ID must be an integer",
                code=HistoryErrorCode.INVALID_TREE,
            )
        for record in tree.nodes:
            if not isinstance(record.node_id, int) or isinstance(record.node_id, bool):
                raise HistoryError(
                    "history node ID must be an integer",
                    code=HistoryErrorCode.INVALID_TREE,
                )
        expected_ids = tuple(range(len(tree.nodes)))
        actual_ids = tuple(record.node_id for record in tree.nodes)
        if actual_ids != expected_ids:
            raise HistoryError(
                "history node IDs must be contiguous and ordered from zero",
                code=HistoryErrorCode.INVALID_TREE,
            )
        if tree.nodes[0].parent_id is not None:
            raise HistoryError(
                "history root must not have a parent",
                code=HistoryErrorCode.INVALID_TREE,
            )
        if tree.cursor_node_id < 0 or tree.cursor_node_id >= len(tree.nodes):
            raise HistoryError(
                "history cursor node does not exist",
                code=HistoryErrorCode.INVALID_TREE,
            )

        child_owners: dict[int, int] = {}
        for record in tree.nodes:
            snapshot = record.snapshot
            if (
                not isinstance(snapshot, PositionSnapshot)
                or not isinstance(snapshot.fen, str)
                or not snapshot.fen.strip()
                or not isinstance(snapshot.context, Mapping)
            ):
                raise HistoryError(
                    f"history node {record.node_id} has an invalid snapshot",
                    code=HistoryErrorCode.INVALID_SNAPSHOT,
                )
            if snapshot.side not in (None, "w", "b"):
                raise HistoryError(
                    f"history node {record.node_id} has an invalid side",
                    code=HistoryErrorCode.INVALID_SNAPSHOT,
                )
            if not isinstance(record.child_ids, tuple):
                raise HistoryError(
                    f"history node {record.node_id} children must be a tuple",
                    code=HistoryErrorCode.INVALID_TREE,
                )
            if len(set(record.child_ids)) != len(record.child_ids):
                raise HistoryError(
                    f"history node {record.node_id} has duplicate children",
                    code=HistoryErrorCode.INVALID_TREE,
                )
            for child_id in record.child_ids:
                if not isinstance(child_id, int) or isinstance(child_id, bool):
                    raise HistoryError(
                        f"history node {record.node_id} has a non-integer child",
                        code=HistoryErrorCode.INVALID_TREE,
                    )
                if child_id <= 0 or child_id >= len(tree.nodes):
                    raise HistoryError(
                        f"history node {record.node_id} references an invalid child",
                        code=HistoryErrorCode.INVALID_TREE,
                    )
                if child_id == record.node_id:
                    raise HistoryError(
                        "history node cannot be its own child",
                        code=HistoryErrorCode.INVALID_TREE,
                    )
                if child_id in child_owners:
                    raise HistoryError(
                        "history node has more than one parent",
                        code=HistoryErrorCode.INVALID_TREE,
                    )
                child_owners[child_id] = record.node_id
            if (
                record.active_child is not None
                and (
                    not isinstance(record.active_child, int)
                    or isinstance(record.active_child, bool)
                )
            ):
                raise HistoryError(
                    f"history node {record.node_id} active child must be an integer",
                    code=HistoryErrorCode.INVALID_TREE,
                )
            if record.active_child is not None and record.active_child not in record.child_ids:
                raise HistoryError(
                    f"history node {record.node_id} active child is not one of its children",
                    code=HistoryErrorCode.INVALID_TREE,
                )

        for node_id, record in enumerate(tree.nodes[1:], start=1):
            parent_id = record.parent_id
            if (
                not isinstance(parent_id, int)
                or isinstance(parent_id, bool)
                or parent_id < 0
                or parent_id >= len(tree.nodes)
            ):
                raise HistoryError(
                    f"history node {node_id} has an invalid parent",
                    code=HistoryErrorCode.INVALID_TREE,
                )
            if child_owners.get(node_id) != parent_id:
                raise HistoryError(
                    f"history node {node_id} parent/child links disagree",
                    code=HistoryErrorCode.INVALID_TREE,
                )

        if len(child_owners) != len(tree.nodes) - 1:
            raise HistoryError(
                "history tree contains unreachable nodes",
                code=HistoryErrorCode.INVALID_TREE,
            )

        reachable: set[int] = set()
        pending = [0]
        while pending:
            node_id = pending.pop()
            if node_id in reachable:
                raise HistoryError(
                    "history tree contains a cycle",
                    code=HistoryErrorCode.INVALID_TREE,
                )
            reachable.add(node_id)
            pending.extend(tree.nodes[node_id].child_ids)
        if len(reachable) != len(tree.nodes):
            raise HistoryError(
                "history tree contains nodes unreachable from the root",
                code=HistoryErrorCode.INVALID_TREE,
            )

        lineage: list[int] = []
        cur = tree.cursor_node_id
        seen: set[int] = set()
        while True:
            if cur in seen:
                raise HistoryError(
                    "history tree contains a cycle",
                    code=HistoryErrorCode.INVALID_TREE,
                )
            seen.add(cur)
            lineage.append(cur)
            parent_id = tree.nodes[cur].parent_id
            if parent_id is None:
                break
            cur = parent_id
        if lineage[-1] != 0:
            raise HistoryError(
                "history cursor is not connected to the root",
                code=HistoryErrorCode.INVALID_TREE,
            )
        lineage.reverse()
        for parent_id, child_id in zip(lineage, lineage[1:]):
            if tree.nodes[parent_id].active_child != child_id:
                raise HistoryError(
                    "history cursor is not on the exported active line",
                    code=HistoryErrorCode.INVALID_TREE,
                )
