from __future__ import annotations

"""Export-specific Library presentation state over the existing DEV1 surface.

The ordinary single current selection remains owned by ``LibraryPresenter`` and
continues to drive Open/keyboard listbox behavior. Multi-game export checkboxes
are transient presentation state only; the canonical D07 export service later
revalidates every id and enforces deterministic Library order.
"""

from collections.abc import Mapping

from .full_product_ui_shell import UILanguage
from .library_export_service import LibraryExportRequest
from .library_webview_projection import LibraryWebViewEvent, LibraryWebViewProjection
from .search_service import GameSearchQuery


_EXPORT_LABELS = {
    UILanguage.UA: {
        "heading": "Партії для експорту",
        "include": "Додати до експорту: {game}",
        "selected": "Експортувати вибрані партії ({count})",
        "filtered": "Експортувати всі результати фільтра",
        "clear": "Очистити вибір для експорту",
        "selected_on": "Додано до експорту.",
        "selected_off": "Вилучено з експорту.",
        "cleared": "Вибір для експорту очищено.",
    },
    UILanguage.EN: {
        "heading": "Games to export",
        "include": "Include in export: {game}",
        "selected": "Export selected games ({count})",
        "filtered": "Export all filtered results",
        "clear": "Clear export selection",
        "selected_on": "Added to export.",
        "selected_off": "Removed from export.",
        "cleared": "Export selection cleared.",
    },
}


class LibraryExportWebViewProjection(LibraryWebViewProjection):
    """Keyboard-first export enrichment of the canonical Library presenter."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._export_game_ids: set[int] = set()

    @property
    def export_game_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self._export_game_ids))

    def _row(self, row: object, *, position: int) -> dict[str, object]:
        projected = super()._row(row, position=position)
        game_id = projected["game_id"]
        if type(game_id) is not int:
            raise ValueError("Library export row has invalid game id")
        label = str(projected["label"])
        projected["export_selected"] = game_id in self._export_game_ids
        projected["export_dom_id"] = f"{projected['dom_id']}-export"
        projected["export_label"] = _EXPORT_LABELS[self.language]["include"].format(
            game=label
        )
        return projected

    def _snapshot_from_view(self, view) -> dict[str, object]:
        snapshot = super()._snapshot_from_view(view)
        labels = _EXPORT_LABELS[self.language]
        count = len(self._export_game_ids)
        existing = tuple(snapshot.get("actions", ()))
        export_actions = (
            {
                "action": "library.export_selected",
                "label": labels["selected"].format(count=count),
                "enabled": count > 0,
            },
            {
                "action": "library.export_filtered",
                "label": labels["filtered"],
                "enabled": bool(snapshot.get("rows")),
            },
            {
                "action": "library.clear_export_selection",
                "label": labels["clear"],
                "enabled": count > 0,
            },
        )
        snapshot["actions"] = existing + export_actions
        snapshot["export_selection_heading"] = labels["heading"]
        snapshot["export_selection_count"] = count
        return snapshot

    def _current_visible_ids(self) -> set[int]:
        view = self._presenter.view()
        result: set[int] = set()
        for row in view.rows:
            game_id = getattr(row, "game_id", None)
            if type(game_id) is not int or game_id <= 0:
                raise ValueError("Library view contains invalid game identity")
            result.add(game_id)
        return result

    @staticmethod
    def _export_focus_target(event: LibraryWebViewEvent, game_id: int) -> str:
        snapshot = event.payload.get("snapshot")
        if not isinstance(snapshot, Mapping):
            raise ValueError("Library export render is missing its snapshot")
        rows = snapshot.get("rows")
        if not isinstance(rows, (tuple, list)):
            raise ValueError("Library export render has invalid rows")
        for row in rows:
            if isinstance(row, Mapping) and row.get("game_id") == game_id:
                target = row.get("export_dom_id")
                if type(target) is str and target:
                    return target
        raise ValueError("Library export render lost the toggled game")

    def toggle_export_selection(self, game_id: int) -> LibraryWebViewEvent:
        if type(game_id) is not int or game_id <= 0:
            raise ValueError("game_id must be a positive integer")
        if game_id not in self._current_visible_ids():
            raise LookupError("Library export game is not on the current page")
        labels = _EXPORT_LABELS[self.language]
        if game_id in self._export_game_ids:
            self._export_game_ids.remove(game_id)
            announcement = labels["selected_off"]
        else:
            self._export_game_ids.add(game_id)
            announcement = labels["selected_on"]
        event = self._render_event(self._presenter.view(), announce=False)
        payload = dict(event.payload)
        payload["announcement"] = announcement
        payload["focus_target"] = self._export_focus_target(event, game_id)
        return LibraryWebViewEvent(event.kind, payload)

    def clear_export_selection(self) -> LibraryWebViewEvent:
        self._export_game_ids.clear()
        event = self._render_event(self._presenter.view(), announce=False)
        payload = dict(event.payload)
        payload["announcement"] = _EXPORT_LABELS[self.language]["cleared"]
        return LibraryWebViewEvent(event.kind, payload)

    def search(self, query: GameSearchQuery) -> LibraryWebViewEvent:
        # A changed result identity clears old export checks atomically. If the
        # canonical search fails, restore the prior presentation selection.
        previous = set(self._export_game_ids)
        self._export_game_ids.clear()
        try:
            return super().search(query)
        except Exception:
            self._export_game_ids = previous
            raise

    def request_export_selected(self) -> LibraryWebViewEvent:
        request = LibraryExportRequest.selected(self.export_game_ids)
        self._dispatch("library.export", request.browser_payload())
        return LibraryWebViewEvent(
            "delegated",
            {"action": "library.export", "scope": "selected"},
        )

    def request_export_filtered(self) -> LibraryWebViewEvent:
        # The query's UI page limit/cursor do not define the filtered result set;
        # LibraryExportRequest.filtered strips that paging authority.
        request = LibraryExportRequest.filtered(self.query)
        self._dispatch("library.export", request.browser_payload())
        return LibraryWebViewEvent(
            "delegated",
            {"action": "library.export", "scope": "filtered"},
        )


__all__ = ["LibraryExportWebViewProjection"]
