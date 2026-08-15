from __future__ import annotations

"""Native pywebview menu projection for the semantic Accessible Chess UI.

The WebView document and the Windows Alt menu must describe the same active
bindings. This module only projects stable action IDs into captions and menu
callbacks; normalization, persistence and conflict policy stay in KeymapService.

The native Settings menu also carries an emergency keymap recovery action. It is
intentionally independent from configurable application shortcuts so a broken
custom profile can never lock a keyboard/NVDA user out of restoring defaults.
"""

import json
from typing import Any, Callable


_MENU_LABELS_UK = {
    "file": "Файл",
    "game": "Гра",
    "board": "Дошка",
    "analysis": "Аналіз",
    "settings": "Налаштування",
    "help": "Довідка",
    "new": "Нова стандартна позиція",
    "empty": "Порожня дошка",
    "exit": "Вихід",
    "undo": "Скасувати хід",
    "redo": "Повторити хід",
    "history_previous": "Попередня позиція в історії",
    "history_next": "Наступна позиція в історії",
    "history_go": "Перейти до ходу",
    "board_go": "Перейти на дошку",
    "move_input": "Поле введення ходу",
    "position_input": "Текстовий редактор позиції",
    "engine_toggle": "Увімкнути / вимкнути Stockfish",
    "keyboard": "Клавіатура і команди",
    "keyboard_reset_all": "Відновити всі клавіші та команди",
    "keyboard_reset_done": "Усі клавіші та команди відновлено за замовчуванням.",
    "keyboard_reset_failed": "Не вдалося відновити клавіші та команди.",
    "nvda_help": "Клавіші та довідка NVDA",
}

_MENU_LABELS_EN = {
    "file": "File",
    "game": "Game",
    "board": "Board",
    "analysis": "Analysis",
    "settings": "Settings",
    "help": "Help",
    "new": "New standard position",
    "empty": "Empty board",
    "exit": "Exit",
    "undo": "Undo move",
    "redo": "Redo move",
    "history_previous": "Previous history position",
    "history_next": "Next history position",
    "history_go": "Go to move",
    "board_go": "Go to board",
    "move_input": "Move input",
    "position_input": "Position text editor",
    "engine_toggle": "Enable / disable Stockfish",
    "keyboard": "Keyboard and commands",
    "keyboard_reset_all": "Reset all keyboard commands",
    "keyboard_reset_done": "All keyboard commands were reset to defaults.",
    "keyboard_reset_failed": "Keyboard commands could not be reset.",
    "nvda_help": "Keys and NVDA help",
}


def _labels(lang: str) -> dict[str, str]:
    return _MENU_LABELS_EN if lang == "en" else _MENU_LABELS_UK


def active_binding(api: Any, action_id: str) -> str | None:
    """Read a binding from the authoritative service without copying defaults."""

    try:
        rows = api.keymap_search("", None)
    except Exception:
        return None
    for row in rows:
        if str(row.get("action_id")) == action_id:
            value = row.get("value")
            if str(row.get("value_kind")) == "shortcut" and value:
                return str(value)
            return None
    return None


def menu_caption(api: Any, label: str, action_id: str | None = None) -> str:
    """Append the current shortcut as a native-menu accelerator hint.

    A tab is the conventional Windows menu separator between the command caption
    and its accelerator hint. If an action has no shortcut, the plain label is
    returned. The hint is descriptive only; dispatch still goes through the
    central action registry/WebView bridge.
    """

    if not action_id:
        return label
    binding = active_binding(api, action_id)
    return f"{label}\t{binding}" if binding else label


def reset_all_keybindings(api: Any, js: Callable[[str], None], *, lang: str = "uk") -> bool:
    """Restore the authoritative keymap through a non-remappable native path.

    The current HTML still contains a legacy localStorage compatibility cache.
    After the central service resets successfully we clear only that obsolete
    keymap cache and reload the document so it cannot shadow the recovered Core
    profile. No game, database, PGN, book, account or other user data is touched.

    Once the WebView keymap screen is fully API-backed, the localStorage cleanup
    can be removed while this native recovery action remains valid.
    """

    text = _labels(lang)
    try:
        result = api.keymap_reset_all()
    except Exception:
        js(f"announce({json.dumps(text['keyboard_reset_failed'])})")
        return False

    if not isinstance(result, dict) or not result.get("ok"):
        js(f"announce({json.dumps(text['keyboard_reset_failed'])})")
        return False

    message = json.dumps(text["keyboard_reset_done"])
    js(
        "localStorage.removeItem('accessibleChess.keymap.v1');"
        f"announce({message});"
        "location.reload()"
    )
    return True


def make_keymap_menu(webview: Any, api: Any, window_holder: dict[str, Any]):
    """Build the Windows Alt menu from live keymap state at window creation."""

    Menu = webview.menu.Menu
    MenuAction = webview.menu.MenuAction
    MenuSeparator = webview.menu.MenuSeparator
    lang = getattr(api, "lang", "uk")
    text = _labels(lang)

    def js(code: str) -> None:
        window = window_holder.get("window")
        if window:
            try:
                window.evaluate_js(code)
            except Exception:
                pass

    def refresh_action(fn: Callable[[], Any]):
        def wrapped():
            fn()
            js("refreshState()")
        return wrapped

    return [
        Menu(text["file"], [
            MenuAction(text["new"], refresh_action(api.new_game)),
            MenuAction(text["empty"], refresh_action(api.clear_board)),
            MenuSeparator(),
            MenuAction(text["exit"], lambda: window_holder.get("window") and window_holder["window"].destroy()),
        ]),
        Menu(text["game"], [
            MenuAction(menu_caption(api, text["undo"], "edit.undo"), refresh_action(api.undo)),
            MenuAction(menu_caption(api, text["redo"], "edit.redo"), refresh_action(api.redo)),
            MenuSeparator(),
            MenuAction(menu_caption(api, text["history_previous"], "history.previous"), refresh_action(api.review_previous)),
            MenuAction(menu_caption(api, text["history_next"], "history.next"), refresh_action(api.review_next)),
            MenuAction(menu_caption(api, text["history_go"], "history.go_to_move"), lambda: js("focusHistoryJump()")),
        ]),
        Menu(text["board"], [
            MenuAction(text["board_go"], lambda: js("enterBoard()")),
            MenuAction(text["move_input"], lambda: js("document.getElementById('move-input').focus()")),
            MenuAction(text["position_input"], lambda: js("document.getElementById('position-input').focus()")),
        ]),
        Menu(text["analysis"], [
            MenuAction(text["engine_toggle"], refresh_action(api.toggle_engine)),
        ]),
        Menu(text["settings"], [
            MenuAction(text["keyboard"], lambda: js("document.getElementById('key-search').focus()")),
            MenuSeparator(),
            MenuAction(
                text["keyboard_reset_all"],
                lambda: reset_all_keybindings(api, js, lang=lang),
            ),
        ]),
        Menu(text["help"], [
            MenuAction(text["nvda_help"], lambda: js("document.getElementById('help').focus()")),
        ]),
    ]
