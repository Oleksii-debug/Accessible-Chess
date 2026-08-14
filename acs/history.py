from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping


class HistoryError(ValueError):
    """Raised when a requested review position cannot be selected."""


@dataclass(frozen=True)
class PositionSnapshot:
    """Presentation-neutral state for one historical chess position."""

    fen: str
    san: str | None = None
    side: str | None = None
    last_move: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)


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
    """Non-destructive game-history cursor with branch preservation."""

    _MOVE_RE = re.compile(r"^(?P<num>[1-9]\d*)(?P<side>w|b|\.\.\.)?$", re.I)

    def __init__(self, initial_fen: str, *, context: Mapping[str, Any] | None = None):
        if not str(initial_fen).strip():
            raise ValueError("initial_fen must not be empty")
        root = PositionSnapshot(str(initial_fen).strip(), context=dict(context or {}))
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

    def append(self, fen: str, *, san: str | None = None, side: str | None = None, last_move: str | None = None, context: Mapping[str, Any] | None = None) -> ReviewSelection:
        if not str(fen).strip():
            raise ValueError("fen must not be empty")
        if side not in (None, "w", "b"):
            raise ValueError("side must be 'w', 'b', or None")
        parent_id = self._cursor
        node_id = len(self._nodes)
        snapshot = PositionSnapshot(str(fen).strip(), san=san, side=side, last_move=last_move, context=dict(context or {}))
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
            raise HistoryError("already at the initial position")
        self._cursor = parent
        return self.current()

    def next(self) -> ReviewSelection:
        child = self._nodes[self._cursor].active_child
        if child is None:
            raise HistoryError("already at the end of the active line")
        self._cursor = child
        return self.current()

    def jump(self, target: str | int) -> ReviewSelection:
        ply = self.parse_target(target)
        path = self._active_path()
        if ply >= len(path):
            raise HistoryError(f"requested ply {ply} does not exist; active line has {len(path)-1} plies")
        self._cursor = path[ply]
        return self._selection(self._cursor, ply, path)

    def select_variation(self, child_index: int) -> ReviewSelection:
        children = self._nodes[self._cursor].children
        if not children:
            raise HistoryError("current position has no variations")
        if child_index < 0 or child_index >= len(children):
            raise HistoryError("variation index out of range")
        chosen = children[child_index]
        self._nodes[self._cursor].active_child = chosen
        self._cursor = chosen
        self._activate_lineage(chosen)
        return self.current()

    def variations(self) -> tuple[PositionSnapshot, ...]:
        return tuple(self._nodes[node_id].snapshot for node_id in self._nodes[self._cursor].children)

    def active_line(self) -> tuple[PositionSnapshot, ...]:
        return tuple(self._nodes[node_id].snapshot for node_id in self._active_path())

    def parse_target(self, target: str | int) -> int:
        if isinstance(target, int):
            if target < 0:
                raise HistoryError("move target must not be negative")
            target = str(target)
        text = str(target).strip().lower()
        if text in {"0", "start"}:
            return 0
        if text == "end":
            return len(self._active_path()) - 1
        match = self._MOVE_RE.fullmatch(text)
        if not match:
            raise HistoryError("invalid move target; use 17, 17w, 17b, 17..., 0/start, or end")
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
                raise RuntimeError("history tree contains a cycle")
            path.append(child)
            seen.add(child)
            node_id = child
        return path

    def _activate_lineage(self, node_id: int) -> None:
        lineage: list[int] = []
        cur: int | None = node_id
        while cur is not None:
            lineage.append(cur)
            cur = self._nodes[cur].parent
        lineage.reverse()
        for parent_id, child_id in zip(lineage, lineage[1:]):
            self._nodes[parent_id].active_child = child_id

    def _selection(self, node_id: int, ply: int, path: list[int]) -> ReviewSelection:
        return ReviewSelection(snapshot=self._nodes[node_id].snapshot, ply=ply, at_start=ply == 0, at_end=ply == len(path) - 1, node_id=node_id)
