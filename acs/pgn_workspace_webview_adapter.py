from __future__ import annotations

"""D01 adapter that binds the proven PGN WebView to canonical D06 workspace state.

The browser/presenter never becomes a second GameTree authority.  Every tree
selection is converted back to a canonical ``GameTreeCursor`` and every edit
intent is enriched from trusted workspace state before it reaches the host
application command dispatcher.
"""

from collections.abc import Callable, Mapping
from typing import Any, Protocol, runtime_checkable

from .full_product_actions import FullProductActionRouter
from .full_product_presenters import PgnTreePresenter
from .full_product_ui_shell import UILanguage
from .gametree_navigation import GameTreeCursor, VariationStep
from .pgn_webview_projection import PgnWebViewEvent, PgnWebViewProjection

@runtime_checkable
class PgnWorkspacePort(Protocol):
    def games(self) -> tuple[object, ...]: ...
    def view(self) -> object: ...


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
    """Old proven WebView contract, synchronized to one canonical workspace."""

    def __init__(
        self,
        workspace: PgnWorkspacePort,
        router: FullProductActionRouter,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not isinstance(workspace, PgnWorkspacePort):
            raise TypeError("workspace does not satisfy the PGN workspace port")
        if not isinstance(router, FullProductActionRouter):
            raise TypeError("PGN workspace router must be FullProductActionRouter")
        self._workspace = workspace
        self._router = router
        presenter, view = self._capture_presenter(language)
        self._workspace_view = view
        super().__init__(
            presenter,
            self._trusted_dispatch,
            lambda: int(getattr(self._workspace_view, "game_count")),
            language=language,
        )

    @staticmethod
    def _view_identity(view: object) -> tuple[object, ...]:
        game_count = getattr(view, "game_count", None)
        game_index = getattr(view, "selected_game_index", None)
        cursor = getattr(view, "cursor", None)
        dirty = getattr(view, "dirty", None)
        revision = getattr(view, "content_revision", None)
        content_digest = getattr(view, "content_digest", None)
        record_digest = getattr(view, "current_record_digest", None)
        if type(game_count) is not int or game_count <= 0 or game_count > 1_000_000_000:
            raise ValueError("PGN workspace view has invalid game count")
        if type(game_index) is not int or not 0 <= game_index < game_count:
            raise ValueError("PGN workspace view has invalid game selection")
        if not isinstance(cursor, GameTreeCursor):
            raise ValueError("PGN workspace view has invalid cursor")
        if type(dirty) is not bool:
            raise ValueError("PGN workspace view has invalid dirty state")
        if type(revision) is not int or revision < 0:
            raise ValueError("PGN workspace view has invalid content revision")
        if (
            type(content_digest) is not str
            or len(content_digest) != 64
            or any(character not in "0123456789abcdef" for character in content_digest)
        ):
            raise ValueError("PGN workspace view has invalid content digest")
        if (
            type(record_digest) is not str
            or len(record_digest) != 64
            or any(character not in "0123456789abcdef" for character in record_digest)
        ):
            raise ValueError("PGN workspace view has invalid record digest")
        return (
            game_count,
            game_index,
            cursor,
            dirty,
            revision,
            content_digest,
            record_digest,
        )

    def _capture_presenter(self, language: UILanguage) -> tuple[PgnTreePresenter, object]:
        before = self._workspace.view()
        before_identity = self._view_identity(before)
        games = self._workspace.games()
        after = self._workspace.view()
        if self._view_identity(after) != before_identity:
            raise ValueError("PGN workspace changed while creating a presentation snapshot")
        if len(games) != before_identity[0]:
            raise ValueError("PGN workspace games disagree with its canonical view")
        game_index = int(before_identity[1])
        cursor = before_identity[2]
        assert isinstance(cursor, GameTreeCursor)
        presenter = PgnTreePresenter(games, language=language)
        presenter.select_game(game_index)
        node_id = _cursor_node_id(game_index, cursor)
        if node_id is not None:
            try:
                presenter.select(node_id)
            except LookupError:
                # Cursor-at-boundary is valid; presenter keeps a safe nearby item.
                pass
        return presenter, before

    def _refresh(self) -> None:
        self._presenter, self._workspace_view = self._capture_presenter(self._language)

    def _snapshot_current(self) -> dict[str, object]:
        snapshot = PgnWebViewProjection.snapshot(self)
        snapshot["workspace"] = {
            "dirty": bool(getattr(self._workspace_view, "dirty", False)),
        }
        return snapshot

    def snapshot(self) -> dict[str, object]:
        self._refresh()
        return self._snapshot_current()

    def _render_event(self, *, announce: str = "") -> PgnWebViewEvent:
        snapshot = self._snapshot_current()
        return PgnWebViewEvent(
            "selection",
            {
                "snapshot": snapshot,
                "focus_target": snapshot.get("focus_target", ""),
                "announcement": announce,
            },
        )

    def _trusted_target(
        self,
        node_id: str,
        *,
        require_current: bool,
        extra: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        cursor = _node_cursor(node_id)
        view = self._workspace.view()
        identity = self._view_identity(view)
        game_index = int(identity[1])
        current_cursor = identity[2]
        if require_current and cursor != current_cursor:
            raise ValueError("PGN presentation selection is stale")
        line_path = tuple(
            (step.parent_move_index, step.variation_index) for step in cursor.line_path
        )
        trusted: dict[str, object] = {
            "game_index": game_index,
            "line_path": line_path,
            "move_index": cursor.next_move_index - 1 if cursor.next_move_index else None,
            "expected_record_digest": identity[6],
            "content_revision": identity[4],
        }
        if extra:
            unknown = set(extra).difference({"text"})
            if unknown:
                raise ValueError("PGN action contains untrusted authority fields")
            if "text" in extra:
                trusted["text"] = extra["text"]
        return trusted

    def _dispatch_registered(self, action_id: str, payload: Mapping[str, object]) -> Any:
        result = self._router.dispatch(action_id, payload)
        if result.handled_by_shell:
            raise ValueError("PGN domain action was handled as a shell route")
        return result.value

    def _trusted_dispatch(self, action_id: str, payload: Mapping[str, object]) -> Any:
        node_id = payload.get("node_id")
        if type(node_id) is not str:
            raise ValueError("PGN action lacks a presentation node")
        cursor = _node_cursor(node_id)
        trusted = self._trusted_target(
            node_id,
            require_current=True,
            extra={key: value for key, value in payload.items() if key not in {"game_index", "node_id"}},
        )
        if action_id in {"pgn.variation_delete", "pgn.variation_promote"}:
            if not cursor.line_path:
                raise ValueError("main line is not a variation target")
            step = cursor.line_path[-1]
            trusted.update(
                {
                    "parent_path": tuple(
                        (item.parent_move_index, item.variation_index)
                        for item in cursor.line_path[:-1]
                    ),
                    "parent_move_index": step.parent_move_index,
                    "variation_index": step.variation_index,
                }
            )
        return self._dispatch_registered(action_id, trusted)

    def _navigate_to(self, action_id: str, node_id: str) -> PgnWebViewEvent:
        payload = self._trusted_target(node_id, require_current=False)
        try:
            self._dispatch_registered(action_id, payload)
        finally:
            self._refresh()
        return self._render_event()

    def select(self, node_id: str) -> PgnWebViewEvent:
        self._refresh()
        selected = self._presenter.select(node_id)
        return self._navigate_to("pgn.select_item", selected.node_id)

    def move_selection(self, delta: int) -> PgnWebViewEvent:
        self._refresh()
        selected = self._presenter.move_selection(delta)
        action_id = "pgn.previous_item" if delta < 0 else "pgn.next_item"
        return self._navigate_to(action_id, selected.node_id)

    def select_parent(self) -> PgnWebViewEvent:
        self._refresh()
        selected = self._presenter.select_parent()
        return self._navigate_to("pgn.parent_variation", selected.node_id)

    def previous_game(self) -> PgnWebViewEvent:
        try:
            self._dispatch_registered("pgn.previous_game", {})
        finally:
            self._refresh()
        return self._render_event()

    def next_game(self) -> PgnWebViewEvent:
        try:
            self._dispatch_registered("pgn.next_game", {})
        finally:
            self._refresh()
        return self._render_event()

    def _mutate_and_render(self, operation: Callable[[], PgnWebViewEvent]) -> PgnWebViewEvent:
        operation()
        self._refresh()
        return self._render_event()

    def edit_comment(self, text: str) -> PgnWebViewEvent:
        return self._mutate_and_render(lambda: PgnWebViewProjection.edit_comment(self, text))

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
