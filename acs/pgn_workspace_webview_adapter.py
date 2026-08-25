from __future__ import annotations

"""D01 adapter that binds the proven PGN WebView to canonical D06 workspace state.

The browser/presenter never becomes a second GameTree authority. Every tree
selection is converted back to a canonical ``GameTreeCursor`` and every edit
intent is enriched from trusted workspace state before it reaches the host
application command dispatcher.
"""

from collections.abc import Callable, Mapping
from typing import Any, Protocol, runtime_checkable

from .full_product_presenters import PgnTreePresenter
from .full_product_ui_shell import UILanguage
from .gametree_navigation import GameTreeCursor, VariationStep
from .pgn_webview_projection import PgnWebViewEvent, PgnWebViewProjection

CommandDispatch = Callable[[str, Mapping[str, object]], Any]


@runtime_checkable
class PgnWorkspacePort(Protocol):
    @property
    def game_count(self) -> int: ...
    @property
    def selected_game_index(self) -> int: ...
    @property
    def cursor(self) -> GameTreeCursor: ...
    @property
    def content_revision(self) -> int: ...
    def games(self) -> tuple[object, ...]: ...
    def view(self) -> object: ...
    def set_cursor(self, cursor: GameTreeCursor) -> object: ...
    def previous_game(self) -> object: ...
    def next_game(self) -> object: ...


def _line_id(game_index: int, path: tuple[VariationStep, ...]) -> str:
    token = f"g{game_index}:main"
    for step in path:
        token += f"/m{step.parent_move_index}/v{step.variation_index}"
    return token


def _cursor_node_id(game_index: int, cursor: GameTreeCursor) -> str | None:
    base = _line_id(game_index, cursor.line_path)
    if cursor.next_move_index > 0:
        return f"{base}/m{cursor.next_move_index - 1}"
    if cursor.line_path:
        return base
    return None


def _node_cursor(node_id: str) -> GameTreeCursor:
    if type(node_id) is not str or ":main" not in node_id:
        raise ValueError("invalid PGN presentation node")
    tail = node_id.split(":main", 1)[1]
    parts = [part for part in tail.split("/") if part]
    path: list[VariationStep] = []
    move_index: int | None = None
    index = 0
    while index < len(parts):
        move = parts[index]
        if not move.startswith("m") or not move[1:].isdigit():
            raise ValueError("invalid PGN presentation node")
        parent_move = int(move[1:])
        if index + 1 < len(parts) and parts[index + 1].startswith("v"):
            variation = parts[index + 1]
            if not variation[1:].isdigit():
                raise ValueError("invalid PGN presentation node")
            path.append(VariationStep(parent_move, int(variation[1:])))
            index += 2
            if index == len(parts):
                return GameTreeCursor(tuple(path), 0)
            continue
        move_index = parent_move
        index += 1
        if index != len(parts):
            raise ValueError("invalid PGN presentation node")
    return GameTreeCursor(tuple(path), 0 if move_index is None else move_index + 1)


class PgnWorkspaceWebViewProjection(PgnWebViewProjection):
    """Proven WebView contract synchronized to one canonical workspace."""

    def __init__(
        self,
        workspace: PgnWorkspacePort,
        dispatch: CommandDispatch,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not isinstance(workspace, PgnWorkspacePort):
            raise TypeError("workspace does not satisfy the PGN workspace port")
        if not callable(dispatch):
            raise TypeError("PGN workspace dispatcher must be callable")
        self._workspace = workspace
        self._host_dispatch = dispatch
        presenter = self._build_presenter(language)
        super().__init__(presenter, self._trusted_dispatch, lambda: self._workspace.game_count, language=language)

    def _build_presenter(self, language: UILanguage) -> PgnTreePresenter:
        presenter = PgnTreePresenter(self._workspace.games(), language=language)
        presenter.select_game(self._workspace.selected_game_index)
        node_id = _cursor_node_id(self._workspace.selected_game_index, self._workspace.cursor)
        if node_id is not None:
            try:
                presenter.select(node_id)
            except LookupError:
                pass
        return presenter

    def _refresh(self) -> None:
        self._presenter = self._build_presenter(self._language)

    def snapshot(self) -> dict[str, object]:
        self._refresh()
        snapshot = super().snapshot()
        view = self._workspace.view()
        snapshot["workspace"] = {
            "dirty": bool(getattr(view, "dirty", False)),
            "content_revision": self._workspace.content_revision,
        }
        return snapshot

    def _trusted_dispatch(self, action_id: str, payload: Mapping[str, object]) -> Any:
        node_id = payload.get("node_id")
        if type(node_id) is not str:
            raise ValueError("PGN action lacks a presentation node")
        cursor = _node_cursor(node_id)
        view = self._workspace.view()
        digest = getattr(view, "current_record_digest", None)
        if type(digest) is not str or len(digest) != 64:
            raise ValueError("PGN workspace record digest is invalid")
        trusted: dict[str, object] = {
            "game_index": self._workspace.selected_game_index,
            "line_path": tuple((step.parent_move_index, step.variation_index) for step in cursor.line_path),
            "move_index": cursor.next_move_index - 1 if cursor.next_move_index else None,
            "expected_record_digest": digest,
            "content_revision": self._workspace.content_revision,
        }
        if action_id in {"pgn.variation_delete", "pgn.variation_promote"}:
            if not cursor.line_path:
                raise ValueError("main line is not a variation target")
            step = cursor.line_path[-1]
            trusted.update({
                "parent_path": tuple((item.parent_move_index, item.variation_index) for item in cursor.line_path[:-1]),
                "parent_move_index": step.parent_move_index,
                "variation_index": step.variation_index,
            })
        for key, value in payload.items():
            if key not in {"game_index", "node_id"}:
                trusted[key] = value
        return self._host_dispatch(action_id, trusted)

    def select(self, node_id: str) -> PgnWebViewEvent:
        self._refresh()
        self._presenter.select(node_id)
        self._workspace.set_cursor(_node_cursor(node_id))
        self._refresh()
        return self._render_event()

    def move_selection(self, delta: int) -> PgnWebViewEvent:
        self._refresh()
        selected = self._presenter.move_selection(delta)
        self._workspace.set_cursor(_node_cursor(selected.node_id))
        self._refresh()
        return self._render_event()

    def select_parent(self) -> PgnWebViewEvent:
        self._refresh()
        selected = self._presenter.select_parent()
        self._workspace.set_cursor(_node_cursor(selected.node_id))
        self._refresh()
        return self._render_event()

    def previous_game(self) -> PgnWebViewEvent:
        self._workspace.previous_game()
        self._refresh()
        return self._render_event()

    def next_game(self) -> PgnWebViewEvent:
        self._workspace.next_game()
        self._refresh()
        return self._render_event()

    def _mutate_and_render(self, operation: Callable[[], PgnWebViewEvent]) -> PgnWebViewEvent:
        operation()
        self._refresh()
        return self._render_event()

    def edit_comment(self, text: str) -> PgnWebViewEvent:
        return self._mutate_and_render(lambda: super().edit_comment(text))

    def delete_comment(self) -> PgnWebViewEvent:
        return self._mutate_and_render(super().delete_comment)

    def delete_variation(self) -> PgnWebViewEvent:
        return self._mutate_and_render(super().delete_variation)

    def promote_variation(self) -> PgnWebViewEvent:
        return self._mutate_and_render(super().promote_variation)

    def copy_selection(self) -> PgnWebViewEvent:
        return self._mutate_and_render(super().copy_selection)

    def export_selection(self) -> PgnWebViewEvent:
        return self._mutate_and_render(super().export_selection)
