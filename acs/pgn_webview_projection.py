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

_MAX_PGN_RAW_TEXT = 12 * 1024 * 1024
_MAX_PGN_TREE_ITEMS = 10_000
_MAX_PGN_TAGS = 256
_MAX_PGN_WARNINGS = 256
_MAX_PGN_COMMENTS_PER_ITEM = 256
_MAX_PGN_NAGS_PER_ITEM = 64
_MAX_PGN_DEPTH = 256
_MAX_PGN_NODE_ID = 4096

_WINDOWS_LOCAL_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:"
    r"[a-z]:(?:[\\/]|(?=[^:\s]{1,160}(?:[\\/]|$)))[^\r\n\t]*"
    r"|\\\\(?:\?\\)?[^\\\s]+\\[^\r\n\t]*"
    r")"
)
_FILE_LOCAL_URI = re.compile(r"(?i)(?<![\w])file:///[^\r\n\t ]*")
_POSIX_LOCAL_PATH = re.compile(
    r"(?i)(?<![\w])(/(?:home|users|tmp|mnt|var|private|opt|usr|etc|srv|run|root|Applications)(?:/|\b)[^\r\n\t ]*)"
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
        "search": "Пошук у PGN",
        "append_moves": "Продовжити лінію",
        "tag_edit": "Редагувати тег PGN",
        "tag_delete": "Видалити тег PGN",
        "comment_edit": "Додати або змінити коментар",
        "comment_delete": "Видалити коментар",
        "nag_edit": "Змінити NAG",
        "variation_add": "Додати варіант",
        "variation_delete": "Видалити варіант",
        "variation_promote": "Підняти варіант",
        "copy": "Копіювати вибране",
        "export": "Експортувати вибране",
        "comment_title": "Коментар PGN",
        "comment_label": "Текст коментаря",
        "comment_before": "Перед ходом",
        "comment_after": "Після ходу",
        "comment_leading": "На початку варіанта",
        "comment_trailing": "Наприкінці варіанта",
        "game_leading_comments": "Коментарі перед головною лінією",
        "game_trailing_comments": "Коментарі після головної лінії",
        "nag_title": "Анотації NAG",
        "nag_label": "NAG, наприклад ! ? $1 $2",
        "variation_title": "Новий варіант",
        "variation_label": "Ходи варіанта у PGN/SAN",
        "save": "Зберегти",
        "cancel": "Скасувати",
        "multiple_comments": "На цьому вузлі кілька коментарів. Редагування вимкнено, доки канонічний API не надасть однозначний вибір коментаря.",
        "local_path": "[локальний шлях приховано]",
        "action_failed": "Не вдалося виконати дію.",
        "presentation_unavailable": "Подання PGN змінилося і не може бути безпечно оновлене. Оновіть подання.",
        "refresh": "Оновити подання PGN",
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
        "search": "Search PGN",
        "append_moves": "Continue line",
        "tag_edit": "Edit PGN tag",
        "tag_delete": "Delete PGN tag",
        "comment_edit": "Add or edit comment",
        "comment_delete": "Delete comment",
        "nag_edit": "Edit NAG",
        "variation_add": "Add variation",
        "variation_delete": "Delete variation",
        "variation_promote": "Promote variation",
        "copy": "Copy selection",
        "export": "Export selection",
        "comment_title": "PGN comment",
        "comment_label": "Comment text",
        "comment_before": "Before move",
        "comment_after": "After move",
        "comment_leading": "At variation start",
        "comment_trailing": "At variation end",
        "game_leading_comments": "Comments before main line",
        "game_trailing_comments": "Comments after main line",
        "nag_title": "NAG annotations",
        "nag_label": "NAGs, for example ! ? $1 $2",
        "variation_title": "New variation",
        "variation_label": "Variation moves in PGN/SAN",
        "save": "Save",
        "cancel": "Cancel",
        "multiple_comments": "This node has multiple comments. Editing is disabled until the canonical API exposes an unambiguous comment selection.",
        "local_path": "[local path hidden]",
        "action_failed": "The action could not be completed.",
        "presentation_unavailable": "The PGN view changed and could not be refreshed safely. Refresh the view.",
        "refresh": "Refresh PGN view",
    },
}


def _scrub_local_paths(text: str, language: UILanguage) -> str:
    replacement = _LABELS[language]["local_path"]
    text = _FILE_LOCAL_URI.sub(replacement, text)
    text = _WINDOWS_LOCAL_PATH.sub(replacement, text)
    return _POSIX_LOCAL_PATH.sub(replacement, text)


def _utf16_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _truncate_utf16(value: str, limit: int) -> str:
    if _utf16_units(value) <= limit:
        return value
    used = 0
    parts: list[str] = []
    for character in value:
        units = 2 if ord(character) > 0xFFFF else 1
        if used + units > limit:
            break
        parts.append(character)
        used += units
    return "".join(parts)


def _bounded_text(value: object, *, language: UILanguage, limit: int) -> str:
    if value is None:
        return ""
    if type(value) is not str:
        raise TypeError("PGN presentation text must be text")
    if len(value) > _MAX_PGN_RAW_TEXT:
        raise ValueError("PGN presentation text exceeds the raw text budget")
    text = value.replace("\x00", "").strip()
    return _truncate_utf16(_scrub_local_paths(text, language), limit)


def _dom_token(node_id: object) -> str:
    if (
        type(node_id) is not str
        or not node_id
        or len(node_id) > _MAX_PGN_NODE_ID
        or "\x00" in node_id
    ):
        raise ValueError("invalid PGN node id")
    return "pgn-node-" + sha256(node_id.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True, slots=True)
class PgnWebViewEvent:
    kind: str
    payload: Mapping[str, object]


class PgnWebViewProjection:
    """JSON-ready PGN/GameTree surface backed by ``PgnTreePresenter`` only.

    A browser render is intentionally derived from exactly one immutable
    ``PgnGameView``. This prevents a concurrent/re-entrant selection or game
    transition from mixing tree, focus, comments, and action availability from
    different presenter states in one sighted/NVDA snapshot.
    """

    def __init__(
        self,
        presenter: PgnTreePresenter,
        dispatch: CommandDispatch,
        game_count: GameCountProvider,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if type(presenter) is not PgnTreePresenter:
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

    def browser_presentation_guard(
        self,
        token: str | None,
    ) -> PgnWebViewEvent | None:
        if token is not None:
            raise ValueError("PGN presentation token is unexpected")
        return None

    def _count(self, view: PgnGameView) -> int:
        value = self._game_count()
        if type(value) is not int or value < 0 or value > 1_000_000_000:
            raise ValueError("PGN game count provider returned invalid count")
        # PgnTreePresenter freezes its game collection as a tuple at construction.
        # Reading that stable collection length does not re-read mutable selection
        # state, and lets the WebView fail closed if an external count provider is
        # stale or inflated instead of advertising inaccessible phantom games.
        if value != len(self._presenter._games):
            raise ValueError("PGN game count disagrees with presenter")
        if value == 0 and view.game_index != -1:
            raise ValueError("PGN game count disagrees with presenter")
        if value > 0 and not 0 <= view.game_index < value:
            raise ValueError("PGN presenter index disagrees with game count")
        return value

    def set_language(self, language: UILanguage | str) -> PgnWebViewEvent:
        if isinstance(language, UILanguage):
            pass
        elif type(language) is str:
            if len(language) > 16 or "\x00" in language:
                raise ValueError("unsupported UI language")
            try:
                language = UILanguage(language.strip().lower())
            except ValueError:
                raise ValueError("unsupported UI language") from None
        else:
            raise TypeError("language must be UILanguage")

        previous_language = self._language
        previous_presenter = self._presenter._capture_presentation_state()
        try:
            # PgnTreePresenter stages the complete localized tree before it
            # commits its own locale. Keep an exact rollback snapshot as well:
            # a later browser projection abort must not publish the new locale
            # into the hidden presenter while the user still has the old page.
            self._presenter.set_language(language)
            self._language = language
            snapshot = self.snapshot()
        except BaseException:
            self._language = previous_language
            self._presenter._restore_presentation_state(previous_presenter)
            raise
        return PgnWebViewEvent("render", snapshot)

    def _tree_item(
        self,
        item: PgnTreeItem,
        selected_node_id: str | None,
    ) -> dict[str, object]:
        if type(item) is not PgnTreeItem:
            raise TypeError("PGN presenter tree item is invalid")
        if (
            type(item.node_id) is not str
            or not item.node_id
            or len(item.node_id) > _MAX_PGN_NODE_ID
            or "\x00" in item.node_id
        ):
            raise ValueError("PGN presenter node id is invalid")
        if type(item.kind) is not str or item.kind not in {"move", "variation"}:
            raise ValueError("PGN presenter item kind is invalid")
        if type(item.depth) is not int or not 0 <= item.depth < _MAX_PGN_DEPTH:
            raise ValueError("PGN presenter item depth is invalid")
        if item.parent_id is not None and (
            type(item.parent_id) is not str
            or not item.parent_id
            or len(item.parent_id) > _MAX_PGN_NODE_ID
            or "\x00" in item.parent_id
        ):
            raise ValueError("PGN presenter parent id is invalid")
        if len(item.comments) > _MAX_PGN_COMMENTS_PER_ITEM:
            raise ValueError("PGN presenter item has too many comments")
        if len(item.nags) > _MAX_PGN_NAGS_PER_ITEM:
            raise ValueError("PGN presenter item has too many annotations")

        comments: list[str] = []
        for comment in item.comments:
            safe = _bounded_text(
                comment,
                language=self._language,
                limit=1200,
            )
            if safe:
                comments.append(safe)

        nags: list[str] = []
        for nag in item.nags:
            safe = _bounded_text(
                nag,
                language=self._language,
                limit=40,
            )
            if safe:
                nags.append(safe)

        return {
            "dom_id": _dom_token(item.node_id),
            "node_id": item.node_id,
            "kind": item.kind,
            "aria_level": item.depth + 1,
            "selected": item.node_id == selected_node_id,
            "label": _bounded_text(item.label, language=self._language, limit=240),
            "san": _bounded_text(item.san, language=self._language, limit=80),
            "comments": tuple(comments),
            "nags": tuple(nags),
            "has_parent": item.parent_id is not None,
        }

    def _comment_editor(
        self,
        *,
        enabled: bool,
        value: str,
        message: str,
        entries: tuple[dict[str, object], ...] = (),
        add_slots: tuple[dict[str, str], ...] = (),
    ) -> dict[str, object]:
        labels = _LABELS[self._language]
        return {
            "enabled": enabled,
            "value": value,
            "message": message,
            "entries": entries,
            "add_slots": add_slots,
            "title": labels["comment_title"],
            "label": labels["comment_label"],
            "save_label": labels["save"],
            "cancel_label": labels["cancel"],
        }

    def _comment_editor_for_selected(
        self,
        selected: PgnTreeItem | None,
    ) -> dict[str, object]:
        labels = _LABELS[self._language]
        if selected is None:
            return self._comment_editor(enabled=False, value="", message="")
        entries: list[dict[str, object]] = []
        add_slots: list[dict[str, str]] = []
        if selected.kind == "move":
            slots = (
                ("before", selected.comments_before, labels["comment_before"]),
                ("after", selected.comments_after, labels["comment_after"]),
            )
        else:
            slots = (
                ("leading", selected.comments, labels["comment_leading"]),
                ("trailing", selected.trailing_comments, labels["comment_trailing"]),
            )
        for slot, comments, slot_label in slots:
            add_slots.append({"slot": slot, "label": slot_label})
            for index, comment in enumerate(comments):
                safe = _bounded_text(comment, language=self._language, limit=8000)
                entries.append(
                    {
                        "slot": slot,
                        "index": index,
                        "label": f"{slot_label} {index + 1}",
                        "value": safe,
                    }
                )
        first_value = str(entries[0]["value"]) if entries else ""
        return self._comment_editor(
            enabled=True,
            value=first_value,
            message="",
            entries=tuple(entries),
            add_slots=tuple(add_slots),
        )

    @staticmethod
    def _selected_from_view(view: PgnGameView) -> PgnTreeItem | None:
        selected_node_id = view.selected_node_id
        if selected_node_id is None:
            return None
        selected = next(
            (item for item in view.items if item.node_id == selected_node_id),
            None,
        )
        if selected is None:
            raise ValueError("PGN presenter snapshot has an invalid selection")
        return selected

    def _safe_view(self, view: PgnGameView, count: int) -> dict[str, object]:
        if type(view) is not PgnGameView:
            raise TypeError("PGN presenter view is invalid")
        if (
            type(view.items) is not tuple
            or type(view.tags) is not tuple
            or type(view.warnings) is not tuple
            or type(view.leading_comments) is not tuple
            or type(view.trailing_comments) is not tuple
        ):
            raise TypeError("PGN presenter collections must be canonical tuples")
        if len(view.items) > _MAX_PGN_TREE_ITEMS:
            raise ValueError("PGN presenter tree exceeds the item-count budget")
        if len(view.tags) > _MAX_PGN_TAGS:
            raise ValueError("PGN presenter tags exceed the item-count budget")
        if len(view.warnings) > _MAX_PGN_WARNINGS:
            raise ValueError("PGN presenter warnings exceed the item-count budget")
        if (
            len(view.leading_comments) > _MAX_PGN_COMMENTS_PER_ITEM
            or len(view.trailing_comments) > _MAX_PGN_COMMENTS_PER_ITEM
        ):
            raise ValueError("PGN main-line comments exceed the item-count budget")
        if view.selected_node_id is not None and (
            type(view.selected_node_id) is not str
            or not view.selected_node_id
            or len(view.selected_node_id) > _MAX_PGN_NODE_ID
            or "\x00" in view.selected_node_id
        ):
            raise ValueError("PGN presenter selection id is invalid")

        for item in view.items:
            if type(item) is not PgnTreeItem:
                raise TypeError("PGN presenter tree item is invalid")
            if (
                type(item.node_id) is not str
                or not item.node_id
                or len(item.node_id) > _MAX_PGN_NODE_ID
                or "\x00" in item.node_id
            ):
                raise ValueError("PGN presenter node id is invalid")
            if (
                type(item.comments) is not tuple
                or type(item.nags) is not tuple
                or type(item.trailing_comments) is not tuple
                or type(item.comments_before) is not tuple
                or type(item.comments_after) is not tuple
            ):
                raise TypeError("PGN presenter item collections must be canonical tuples")
            if (
                len(item.comments) > _MAX_PGN_COMMENTS_PER_ITEM
                or len(item.trailing_comments) > _MAX_PGN_COMMENTS_PER_ITEM
                or len(item.comments_before) > _MAX_PGN_COMMENTS_PER_ITEM
                or len(item.comments_after) > _MAX_PGN_COMMENTS_PER_ITEM
            ):
                raise ValueError("PGN presenter item has too many comments")
        for tag in view.tags:
            if type(tag) is not tuple or len(tag) != 2:
                raise TypeError("PGN presenter tag entry is invalid")

        labels = _LABELS[self._language]
        if view.game_index < 0:
            if view.items or view.selected_node_id is not None:
                raise ValueError("empty PGN presenter snapshot is inconsistent")
            return {
                "status": "empty",
                "empty_message": labels["empty"],
                "game": {},
                "tree": (),
                "focus_target": "",
                "actions": (),
                "comment_editor": self._comment_editor(enabled=False, value="", message=""),
            }

        selected = self._selected_from_view(view)
        tree = tuple(
            self._tree_item(item, view.selected_node_id)
            for item in view.items
        )
        node_ids = [item["node_id"] for item in tree]
        dom_ids = [item["dom_id"] for item in tree]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("PGN presenter tree contains duplicate node ids")
        if len(set(dom_ids)) != len(dom_ids):
            raise ValueError("PGN browser tree contains duplicate DOM ids")
        selected_count = sum(1 for item in tree if item["selected"])
        if selected is None:
            if selected_count != 0:
                raise ValueError("PGN presenter selection is inconsistent")
        elif selected_count != 1:
            raise ValueError("PGN presenter selection is inconsistent")

        focus_target = next(
            (item["dom_id"] for item in tree if item["selected"]),
            "",
        )
        if selected is not None and not focus_target:
            raise ValueError("PGN presenter snapshot selection has no browser focus target")
        tags = tuple(
            {
                "name": _bounded_text(name, language=self._language, limit=80),
                "value": _bounded_text(value, language=self._language, limit=360),
            }
            for name, value in view.tags
        )
        safe_warnings: list[str] = []
        for warning in view.warnings:
            safe = _bounded_text(
                warning,
                language=self._language,
                limit=720,
            )
            if safe:
                safe_warnings.append(safe)
        warnings = tuple(safe_warnings)
        leading_comments = tuple(
            safe
            for safe in (
                _bounded_text(item, language=self._language, limit=1200)
                for item in view.leading_comments
            )
            if safe
        )
        trailing_comments = tuple(
            safe
            for safe in (
                _bounded_text(item, language=self._language, limit=1200)
                for item in view.trailing_comments
            )
            if safe
        )
        comment_editor = self._comment_editor_for_selected(selected)
        has_selection = selected is not None
        selected_is_variation = bool(selected and selected.kind == "variation")
        has_selected_comments = bool(comment_editor["entries"])
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
                "leading_comments_heading": labels["game_leading_comments"],
                "leading_comments": leading_comments,
                "trailing_comments_heading": labels["game_trailing_comments"],
                "trailing_comments": trailing_comments,
                "tree_heading": labels["tree"],
                "can_previous_game": view.game_index > 0,
                "can_next_game": view.game_index + 1 < count,
            },
            "tree": tree,
            "focus_target": focus_target,
            "actions": (
                {"action": "pgn.previous_game", "label": labels["previous_game"], "enabled": view.game_index > 0},
                {"action": "pgn.next_game", "label": labels["next_game"], "enabled": view.game_index + 1 < count},
                {"action": "pgn.search", "label": labels["search"], "enabled": True},
                {"action": "pgn.append_moves", "label": labels["append_moves"], "enabled": True},
                {"action": "pgn.tag_edit", "label": labels["tag_edit"], "enabled": True},
                {"action": "pgn.tag_delete", "label": labels["tag_delete"], "enabled": True},
                {"action": "pgn.parent", "label": labels["parent"], "enabled": bool(selected and selected.parent_id)},
                {"action": "pgn.comment_edit", "label": labels["comment_edit"], "enabled": has_selection},
                {"action": "pgn.comment_delete", "label": labels["comment_delete"], "enabled": has_selected_comments},
                {"action": "pgn.nag_edit", "label": labels["nag_edit"], "enabled": bool(selected and selected.kind == "move")},
                {"action": "pgn.variation_add", "label": labels["variation_add"], "enabled": bool(selected and selected.kind == "move")},
                {"action": "pgn.variation_delete", "label": labels["variation_delete"], "enabled": selected_is_variation},
                {"action": "pgn.variation_promote", "label": labels["variation_promote"], "enabled": selected_is_variation},
                {"action": "pgn.copy_selection", "label": labels["copy"], "enabled": has_selection},
                {"action": "pgn.export_selection", "label": labels["export"], "enabled": has_selection},
            ),
            "comment_editor": comment_editor,
        }

    def snapshot(self) -> dict[str, object]:
        view = self._presenter.view()
        if type(view) is not PgnGameView or type(view.game_index) is not int:
            raise TypeError("PGN presenter view is invalid")
        count = self._count(view)
        return {
            "document": {"lang": self._language.value, "landmark": "main"},
            "error_message": _LABELS[self._language]["action_failed"],
            **self._safe_view(view, count),
        }

    def _unavailable_snapshot(self) -> dict[str, object]:
        labels = _LABELS[self._language]
        return {
            "document": {"lang": self._language.value, "landmark": "main"},
            "error_message": labels["action_failed"],
            "status": "unavailable",
            "unavailable_message": labels["presentation_unavailable"],
            "refresh_label": labels["refresh"],
            "focus_target": "pgn-refresh-view",
            "game": {},
            "tree": (),
            "actions": (),
            "comment_editor": self._comment_editor(
                enabled=False,
                value="",
                message="",
            ),
        }

    def _unavailable_event(self) -> PgnWebViewEvent:
        snapshot = self._unavailable_snapshot()
        return PgnWebViewEvent(
            "selection",
            {
                "snapshot": snapshot,
                "focus_target": snapshot["focus_target"],
                "announcement": snapshot["unavailable_message"],
            },
        )

    def refresh_view(self) -> PgnWebViewEvent:
        snapshot = self.snapshot()
        announcement = (
            str(snapshot.get("unavailable_message", ""))
            if snapshot.get("status") == "unavailable"
            else ""
        )
        return PgnWebViewEvent(
            "selection",
            {
                "snapshot": snapshot,
                "focus_target": snapshot.get("focus_target", ""),
                "announcement": announcement,
            },
        )

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

    def _render_presenter_transition(
        self,
        operation: Callable[[], object],
        *,
        announce: str = "",
    ) -> PgnWebViewEvent:
        """Commit PGN cursor/game changes only with a valid browser snapshot."""
        previous = self._presenter._capture_presentation_state()
        try:
            operation()
            return self._render_event(announce=announce)
        except BaseException:
            self._presenter._restore_presentation_state(previous)
            raise

    def select(self, node_id: str) -> PgnWebViewEvent:
        if type(node_id) is not str:
            raise TypeError("PGN node id must be text")
        if len(node_id) > _MAX_PGN_NODE_ID or "\x00" in node_id:
            raise ValueError("invalid PGN node id")
        normalized = node_id.strip()
        if not normalized:
            raise ValueError("invalid PGN node id")
        return self._render_presenter_transition(
            lambda: self._presenter.select(normalized)
        )

    def move_selection(self, delta: int) -> PgnWebViewEvent:
        return self._render_presenter_transition(
            lambda: self._presenter.move_selection(delta)
        )

    def select_parent(self) -> PgnWebViewEvent:
        return self._render_presenter_transition(self._presenter.select_parent)

    def previous_game(self) -> PgnWebViewEvent:
        return self._render_presenter_transition(self._presenter.previous_game)

    def next_game(self) -> PgnWebViewEvent:
        return self._render_presenter_transition(self._presenter.next_game)

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
            exact = bool(extra and "slot" in extra and "index" in extra)
            if not exact and len(selected.comments) > 1:
                raise ValueError("ambiguous PGN comment selection")
        elif action_id == "pgn.comment_delete":
            exact = bool(extra and "slot" in extra and "index" in extra)
            if not exact and len(selected.comments) != 1:
                raise ValueError("exactly one PGN comment is required")
        elif action_id in {"pgn.nag_edit", "pgn.variation_add"}:
            if selected.kind != "move":
                raise ValueError("PGN move edit action requires a move selection")
        elif action_id in {"pgn.variation_delete", "pgn.variation_promote"}:
            if selected.kind != "variation":
                raise ValueError("PGN variation action requires variation selection")
        self._presenter.dispatch_edit(action_id, self._dispatch, extra=extra)
        return PgnWebViewEvent("delegated", {"action": action_id})

    def append_moves(self, text: str) -> PgnWebViewEvent:
        if type(text) is not str or not text.strip() or len(text) > 8192 or "\x00" in text:
            raise ValueError("PGN continuation text is invalid")
        return self._dispatch("pgn.append_moves", {"text": text})

    def edit_tag(self, name: str, value: str) -> PgnWebViewEvent:
        if type(name) is not str or not name or len(name) > 80 or "\x00" in name:
            raise ValueError("PGN tag name is invalid")
        if type(value) is not str or len(value) > 360 or "\x00" in value:
            raise ValueError("PGN tag value is invalid")
        self._dispatch("pgn.tag_edit", {"name": name, "value": value})
        return PgnWebViewEvent("delegated", {"action": "pgn.tag_edit"})

    def delete_tag(self, name: str) -> PgnWebViewEvent:
        if type(name) is not str or not name or len(name) > 80 or "\x00" in name:
            raise ValueError("PGN tag name is invalid")
        self._dispatch("pgn.tag_delete", {"name": name})
        return PgnWebViewEvent("delegated", {"action": "pgn.tag_delete"})

    def search(self, text: str) -> PgnWebViewEvent:
        if type(text) is not str or not text.strip() or len(text) > 4096 or "\x00" in text:
            raise ValueError("PGN search text is invalid")
        # Search is document-scoped, not move-scoped. A lawful PGN can have
        # tags/result but no moves, so search must work from the canonical root
        # even when there is no presentation node to select.
        self._presenter.dispatch_edit(
            "pgn.search",
            self._dispatch,
            extra={"text": text},
        )
        return PgnWebViewEvent("delegated", {"action": "pgn.search"})

    def edit_comment(
        self,
        text: str,
        *,
        slot: str | None = None,
        index: int | None = None,
    ) -> PgnWebViewEvent:
        if type(text) is not str:
            raise TypeError("PGN comment text must be text")
        if _utf16_units(text) > 8000 or "\x00" in text:
            raise ValueError("PGN comment text is invalid")
        extra: dict[str, object] = {"text": text}
        if slot is not None or index is not None:
            if type(slot) is not str or slot not in {"before", "after", "leading", "trailing"}:
                raise ValueError("PGN comment slot is invalid")
            if type(index) is not int or index < -1 or index > 255:
                raise ValueError("PGN comment index is invalid")
            extra.update(slot=slot, index=index)
        return self._dispatch_selected("pgn.comment_edit", extra=extra)

    def delete_comment(
        self,
        *,
        slot: str | None = None,
        index: int | None = None,
    ) -> PgnWebViewEvent:
        extra: dict[str, object] | None = None
        if slot is not None or index is not None:
            if type(slot) is not str or slot not in {"before", "after", "leading", "trailing"}:
                raise ValueError("PGN comment slot is invalid")
            if type(index) is not int or index < 0 or index > 255:
                raise ValueError("PGN comment index is invalid")
            extra = {"slot": slot, "index": index}
        return self._dispatch_selected("pgn.comment_delete", extra=extra)

    def edit_nags(self, text: str) -> PgnWebViewEvent:
        if type(text) is not str or len(text) > 512 or "\x00" in text:
            raise ValueError("PGN NAG text is invalid")
        return self._dispatch_selected("pgn.nag_edit", extra={"text": text})

    def add_variation(self, text: str) -> PgnWebViewEvent:
        if type(text) is not str or not text.strip() or len(text) > 8192 or "\x00" in text:
            raise ValueError("PGN variation text is invalid")
        return self._dispatch_selected("pgn.variation_add", extra={"text": text})

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
        except BaseException as exc:
            # Abort-class failures are implementation/control-flow details. Never
            # call their string conversion while building an NVDA/browser error.
            source: object = exc if isinstance(exc, Exception) else ""
            return PgnWebViewEvent(
                "error",
                {"message": concise_user_error(source, language=self._language)},
            )
