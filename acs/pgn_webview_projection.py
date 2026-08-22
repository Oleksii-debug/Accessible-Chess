"""Accessible WebView projection over the existing canonical PGN/GameTree presenter.

DEV1 owns only presentation here. ``PgnTreePresenter`` remains the sole tree
projection used by the UI and every mutation is delegated as an existing
canonical application command intent. No GameTree/chess mutation logic lives in
this module.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Any

from .full_product_presenters import PgnGameView, PgnTreeItem, PgnTreePresenter
from .full_product_ui_shell import UILanguage, concise_user_error

CommandDispatch = Callable[[str, Mapping[str, object]], Any]
GameCountProvider = Callable[[], int]

_WINDOWS_LOCAL_PATH = re.compile(r"(?i)(?<![\w])([a-z]:[\\/][^\r\n\t]*)")
_POSIX_LOCAL_PATH = re.compile(
    r"(?i)(?<![\w])(/(?:home|users|tmp|mnt|var/tmp|private/tmp)/[^\r\n\t ]*)"
)

_LABELS = {
    UILanguage.UA: {
        "game": "Партія",
        "of": "з",
        "result": "Результат",
        "tags": "Теги PGN",
        "warnings": "Попередження PGN",
        "tree": "Дерево партії",
        "empty": "У PGN немає партій.",
        "previous_game": "Попередня партія",
        "next_game": "Наступна партія",
        "parent": "До батьківського варіанта",
        "comment_edit": "Додати або змінити коментар",
        "comment_delete": "Видалити коментар",
        "variation_delete": "Видалити варіант",
        "variation_promote": "Підняти варіант",
        "copy": "Копіювати вибране",
        "export": "Експортувати вибране",
        "comment_title": "Коментар PGN",
        "comment_label": "Текст коментаря",
        "save": "Зберегти",
        "cancel": "Скасувати",
        "multiple_comments": "На цьому вузлі кілька коментарів. Редагування вимкнено, доки канонічний API не надасть однозначний вибір коментаря.",
        "local_path": "[локальний шлях приховано]",
    },
    UILanguage.EN: {
        "game": "Game",
        "of": "of",
        "result": "Result",
        "tags": "PGN tags",
        "warnings": "PGN warnings",
        "tree": "Game tree",
        "empty": "The PGN contains no games.",
        "previous_game": "Previous game",
        "next_game": "Next game",
        "parent": "Return to parent variation",
        "comment_edit": "Add or edit comment",
        "comment_delete": "Delete comment",
        "variation_delete": "Delete variation",
        "variation_promote": "Promote variation",
        "copy": "Copy selection",
        "export": "Export selection",
        "comment_title": "PGN comment",
        "comment_label": "Comment text",
        "save": "Save",
        "cancel": "Cancel",
        "multiple_comments": "This node has multiple comments. Editing is disabled until the canonical API exposes an unambiguous comment selection.",
        "local_path": "[local path hidden]",
    },
}


def _scrub_local_paths(text: str, language: UILanguage) -> str:
    replacement = _LABELS[language]["local_path"]
    text = _WINDOWS_LOCAL_PATH.sub(replacement, text)
    return _POSIX_LOCAL_PATH.sub(replacement, text)


def _bounded_text(
    value: object,
    *,
    language: UILanguage,
    limit: int,
) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("PGN presentation text must be text")
    text = value.replace("\x00", "").strip()
    return _scrub_local_paths(text, language)[:limit]


def _dom_token(node_id: str) -> str:
    return "pgn-node-" + sha256(node_id.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True, slots=True)
class PgnWebViewEvent:
    kind: str
    payload: Mapping[str, object]


class PgnWebViewProjection:
    """JSON-ready PGN/GameTree surface backed by ``PgnTreePresenter`` only."""

    def __init__(
        self,
        presenter: PgnTreePresenter,
        dispatch: CommandDispatch,
        game_count: GameCountProvider,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not isinstance(presenter, PgnTreePresenter):
            raise TypeError("presenter must be PgnTreePresenter")
        if not callable(dispatch):
            raise TypeError("PGN dispatcher must be callable")
        if not callable(game_count):
            raise TypeError("game_count provider must be callable")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._presenter = presenter
        self._dispatch = dispatch
        self._game_count = game_count
        self._language = language
        self._presenter.set_language(language)

    @property
    def language(self) -> UILanguage:
        return self._language

    def _count(self) -> int:
        value = self._game_count()
        if type(value) is not int or value < 0 or value > 1_000_000_000:
            raise ValueError("PGN game count provider returned invalid count")
        view = self._presenter.view()
        if value == 0 and view.game_index != -1:
            raise ValueError("PGN game count disagrees with presenter")
        if value > 0 and not 0 <= view.game_index < value:
            raise ValueError("PGN presenter index disagrees with game count")
        return value

    def set_language(self, language: UILanguage | str) -> PgnWebViewEvent:
        if isinstance(language, str):
            try:
                language = UILanguage(language.strip().lower())
            except ValueError:
                raise ValueError("unsupported UI language") from None
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._language = language
        self._presenter.set_language(language)
        return PgnWebViewEvent("render", self.snapshot())

    def _tree_item(self, item: PgnTreeItem) -> dict[str, object]:
        selected = item.node_id == self._presenter.selected_node_id
        return {
            "dom_id": _dom_token(item.node_id),
            "node_id": item.node_id,
            "kind": item.kind,
            "aria_level": item.depth + 1,
            "selected": selected,
            "label": _bounded_text(item.label, language=self._language, limit=240),
            "san": _bounded_text(item.san, language=self._language, limit=80),
            "comments": tuple(
                _bounded_text(comment, language=self._language, limit=1200)
                for comment in item.comments
                if comment.strip()
            ),
            "nags": tuple(
                _bounded_text(nag, language=self._language, limit=40)
                for nag in item.nags
                if nag.strip()
            ),
            "has_parent": item.parent_id is not None,
        }

    def _comment_editor(self, *, enabled: bool, value: str, message: str) -> dict[str, object]:
        labels = _LABELS[self._language]
        return {
            "enabled": enabled,
            "value": value,
            "message": message,
            "title": labels["comment_title"],
            "label": labels["comment_label"],
            "save_label": labels["save"],
            "cancel_label": labels["cancel"],
        }

    def _safe_view(self, view: PgnGameView, count: int) -> dict[str, object]:
        labels = _LABELS[self._language]
        if view.game_index < 0:
            return {
                "status": "empty",
                "empty_message": labels["empty"],
                "game": {},
                "tree": (),
                "focus_target": "",
                "actions": (),
                "comment_editor": self._comment_editor(enabled=False, value="", message=""),
            }

        tree = tuple(self._tree_item(item) for item in view.items)
        selected = self._presenter.selected()
        selected_comments = tuple(selected.comments) if selected is not None else ()
        ambiguous_comments = len(selected_comments) > 1
        focus_target = next(
            (str(item["dom_id"]) for item in tree if item["selected"]),
            "",
        )
        tags = tuple(
            {
                "name": _bounded_text(name, language=self._language, limit=80),
                "value": _bounded_text(value, language=self._language, limit=360),
            }
            for name, value in view.tags
        )
        warnings = tuple(
            _bounded_text(warning, language=self._language, limit=720)
            for warning in view.warnings
            if warning.strip()
        )
        has_selection = selected is not None
        selected_is_variation = bool(selected and selected.kind == "variation")
        single_comment = len(selected_comments) == 1
        return {
            "status": "ready",
            "empty_message": "",
            "game": {
                "index": view.game_index,
                "number": view.game_index + 1,
                "count": count,
                "heading": _bounded_text(view.title, language=self._language, limit=240),
                "position_label": f"{labels['game']} {view.game_index + 1} {labels['of']} {count}",
                "result_label": labels["result"],
                "result": _bounded_text(view.result, language=self._language, limit=32),
                "tags_heading": labels["tags"],
                "tags": tags,
                "warnings_heading": labels["warnings"],
                "warnings": warnings,
                "tree_heading": labels["tree"],
                "can_previous_game": view.game_index > 0,
                "can_next_game": view.game_index + 1 < count,
            },
            "tree": tree,
            "focus_target": focus_target,
            "actions": (
                {"action": "pgn.previous_game", "label": labels["previous_game"], "enabled": view.game_index > 0},
                {"action": "pgn.next_game", "label": labels["next_game"], "enabled": view.game_index + 1 < count},
                {"action": "pgn.parent", "label": labels["parent"], "enabled": bool(selected and selected.parent_id)},
                {"action": "pgn.comment_edit", "label": labels["comment_edit"], "enabled": has_selection and not ambiguous_comments},
                {"action": "pgn.comment_delete", "label": labels["comment_delete"], "enabled": single_comment},
                {"action": "pgn.variation_delete", "label": labels["variation_delete"], "enabled": selected_is_variation},
                {"action": "pgn.variation_promote", "label": labels["variation_promote"], "enabled": selected_is_variation},
                {"action": "pgn.copy_selection", "label": labels["copy"], "enabled": has_selection},
                {"action": "pgn.export_selection", "label": labels["export"], "enabled": has_selection},
            ),
            "comment_editor": self._comment_editor(
                enabled=has_selection and not ambiguous_comments,
                value=_bounded_text(
                    selected_comments[0] if single_comment else "",
                    language=self._language,
                    limit=8000,
                ),
                message=labels["multiple_comments"] if ambiguous_comments else "",
            ),
        }

    def snapshot(self) -> dict[str, object]:
        count = self._count()
        return {
            "document": {"lang": self._language.value, "landmark": "main"},
            **self._safe_view(self._presenter.view(), count),
        }

    def _render_event(self, *, announce: str = "") -> PgnWebViewEvent:
        snapshot = self.snapshot()
        return PgnWebViewEvent(
            "selection",
            {
                "snapshot": snapshot,
                "focus_target": snapshot.get("focus_target", ""),
                "announcement": announce,
            },
        )

    def select(self, node_id: str) -> PgnWebViewEvent:
        if not isinstance(node_id, str) or not node_id.strip() or len(node_id) > 4096:
            raise ValueError("invalid PGN node id")
        self._presenter.select(node_id.strip())
        return self._render_event()

    def move_selection(self, delta: int) -> PgnWebViewEvent:
        self._presenter.move_selection(delta)
        return self._render_event()

    def select_parent(self) -> PgnWebViewEvent:
        self._presenter.select_parent()
        return self._render_event()

    def previous_game(self) -> PgnWebViewEvent:
        self._presenter.previous_game()
        return self._render_event()

    def next_game(self) -> PgnWebViewEvent:
        self._presenter.next_game()
        return self._render_event()

    def _dispatch_selected(
        self,
        action_id: str,
        *,
        extra: Mapping[str, object] | None = None,
    ) -> PgnWebViewEvent:
        selected = self._presenter.selected()
        if selected is None:
            raise LookupError("PGN selection is required")
        if action_id == "pgn.comment_edit":
            if len(selected.comments) > 1:
                raise ValueError("ambiguous PGN comment selection")
        elif action_id == "pgn.comment_delete":
            if len(selected.comments) != 1:
                raise ValueError("exactly one PGN comment is required")
        elif action_id in {"pgn.variation_delete", "pgn.variation_promote"}:
            if selected.kind != "variation":
                raise ValueError("PGN variation action requires variation selection")
        self._presenter.dispatch_edit(action_id, self._dispatch, extra=extra)
        return PgnWebViewEvent("delegated", {"action": action_id})

    def edit_comment(self, text: str) -> PgnWebViewEvent:
        if not isinstance(text, str):
            raise TypeError("PGN comment text must be text")
        if "\x00" in text or len(text) > 8000:
            raise ValueError("PGN comment text is invalid")
        return self._dispatch_selected("pgn.comment_edit", extra={"text": text})

    def delete_comment(self) -> PgnWebViewEvent:
        return self._dispatch_selected("pgn.comment_delete")

    def delete_variation(self) -> PgnWebViewEvent:
        return self._dispatch_selected("pgn.variation_delete")

    def promote_variation(self) -> PgnWebViewEvent:
        return self._dispatch_selected("pgn.variation_promote")

    def copy_selection(self) -> PgnWebViewEvent:
        return self._dispatch_selected("pgn.copy_selection")

    def export_selection(self) -> PgnWebViewEvent:
        return self._dispatch_selected("pgn.export_selection")

    def safe_call(self, method: Callable[[], PgnWebViewEvent]) -> PgnWebViewEvent:
        try:
            return method()
        except Exception as exc:
            return PgnWebViewEvent(
                "error",
                {"message": concise_user_error(exc, language=self._language)},
            )
