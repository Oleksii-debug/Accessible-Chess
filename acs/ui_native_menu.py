from __future__ import annotations

"""Windows-native menu for Accessible Chess.

The pywebview MenuStrip projection looked like a menu visually, but the real
NVDA acceptance test could not operate it with normal Alt/arrow/Enter/Escape
semantics. On Windows we attach a classic System.Windows.Forms.MainMenu to the
actual native Form. That control is owned by Windows rather than the WebView
DOM and exposes standard menu keyboard behaviour to accessibility clients.
"""

from typing import Any, Callable


_LABELS_UK = {
    "file": "&Файл", "game": "&Гра", "board": "&Дошка", "analysis": "&Аналіз",
    "settings": "&Налаштування", "help": "&Довідка",
    "new": "Нова партія", "empty": "Порожня дошка", "exit": "Вихід",
    "undo": "Скасувати хід", "redo": "Повторити хід",
    "history_previous": "Попередня позиція", "history_next": "Наступна позиція",
    "history_go": "Перейти до ходу", "board_go": "Перейти на дошку",
    "move_input": "Введення ходу", "position_input": "Редактор позиції",
    "engine_toggle": "Увімкнути / вимкнути Stockfish",
    "keyboard": "Клавіатура і команди", "keyboard_reset": "Відновити стандартні клавіші",
    "help_open": "Довідка",
}

_LABELS_EN = {
    "file": "&File", "game": "&Game", "board": "&Board", "analysis": "&Analysis",
    "settings": "&Settings", "help": "&Help",
    "new": "New game", "empty": "Empty board", "exit": "Exit",
    "undo": "Undo move", "redo": "Redo move",
    "history_previous": "Previous position", "history_next": "Next position",
    "history_go": "Go to move", "board_go": "Go to board",
    "move_input": "Move input", "position_input": "Position editor",
    "engine_toggle": "Enable / disable Stockfish",
    "keyboard": "Keyboard and commands", "keyboard_reset": "Reset keyboard defaults",
    "help_open": "Help",
}


def _labels(lang: str) -> dict[str, str]:
    return _LABELS_EN if lang == "en" else _LABELS_UK


def _safe_js(window: Any, code: str) -> None:
    try:
        window.evaluate_js(code)
    except Exception:
        pass


def _invoke_api(window: Any, fn: Callable[[], Any]) -> None:
    try:
        fn()
    finally:
        _safe_js(window, "refreshState()")


def install_windows_native_menu(window: Any, api: Any) -> bool:
    """Attach a classic native WinForms MainMenu to ``window.native``.

    This function is intentionally called only after pywebview has started,
    because ``window.native`` is guaranteed only after the native Form exists.
    It returns False on non-Windows/non-WinForms hosts so tests and other
    platforms can fail closed without pretending an accessible Alt menu exists.
    """

    try:
        import clr  # type: ignore
        clr.AddReference("System.Windows.Forms")
        from System import Action  # type: ignore
        from System.Windows.Forms import MainMenu, MenuItem  # type: ignore
    except Exception:
        return False

    form = getattr(window, "native", None)
    if form is None or not hasattr(form, "Menu"):
        return False

    text = _labels(getattr(api, "lang", "uk"))
    handlers: list[Any] = []

    def item(label: str, callback: Callable[[], Any] | None = None) -> Any:
        menu_item = MenuItem(label)
        if callback is not None:
            def on_click(sender, event, cb=callback):
                cb()
            handlers.append(on_click)
            menu_item.Click += on_click
        return menu_item

    def submenu(label: str, children: list[Any]) -> Any:
        parent = MenuItem(label)
        for child in children:
            parent.MenuItems.Add(child)
        return parent

    def separator() -> Any:
        return MenuItem("-")

    menu = MainMenu()
    file_menu = submenu(text["file"], [
        item(text["new"], lambda: _invoke_api(window, api.new_game)),
        item(text["empty"], lambda: _invoke_api(window, api.clear_board)),
        separator(),
        item(text["exit"], window.destroy),
    ])
    game_menu = submenu(text["game"], [
        item(text["undo"], lambda: _invoke_api(window, api.undo)),
        item(text["redo"], lambda: _invoke_api(window, api.redo)),
        separator(),
        item(text["history_previous"], lambda: _invoke_api(window, api.review_previous)),
        item(text["history_next"], lambda: _invoke_api(window, api.review_next)),
        item(text["history_go"], lambda: _safe_js(window, "focusHistoryJump()")),
    ])
    board_menu = submenu(text["board"], [
        item(text["board_go"], lambda: _safe_js(window, "enterBoard()")),
        item(text["move_input"], lambda: _safe_js(window, "document.getElementById('move-input').focus()")),
        item(text["position_input"], lambda: _safe_js(window, "document.getElementById('position-input').focus()")),
    ])
    analysis_menu = submenu(text["analysis"], [
        item(text["engine_toggle"], lambda: _invoke_api(window, api.toggle_engine)),
    ])
    settings_menu = submenu(text["settings"], [
        item(text["keyboard"], lambda: _safe_js(window, "document.getElementById('keymap-dialog').showModal();document.getElementById('key-search').focus()")),
        item(text["keyboard_reset"], lambda: _invoke_api(window, api.keymap_reset_all)),
    ])
    help_menu = submenu(text["help"], [
        item(text["help_open"], lambda: _safe_js(window, "document.getElementById('help-dialog').showModal();document.getElementById('help').focus()")),
    ])
    for top in (file_menu, game_menu, board_menu, analysis_menu, settings_menu, help_menu):
        menu.MenuItems.Add(top)

    # Keep managed objects and Python event handlers alive for the Form lifetime.
    setattr(window, "_accessible_chess_native_menu", menu)
    setattr(window, "_accessible_chess_native_menu_handlers", handlers)

    def attach() -> None:
        form.Menu = menu
        form.MainMenuStrip = None if hasattr(form, "MainMenuStrip") else getattr(form, "MainMenuStrip", None)

    try:
        if getattr(form, "InvokeRequired", False):
            form.Invoke(Action(attach))
        else:
            attach()
    except Exception:
        return False
    return True


# Backward-compatible name for tests/importers. It deliberately does not build
# the old pywebview MenuStrip anymore.
def make_keymap_menu(*args, **kwargs):
    raise RuntimeError("Use install_windows_native_menu after the native window is created")
