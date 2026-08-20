from __future__ import annotations

"""Windows-native application menu for Accessible Chess.

The release launcher attaches a real ``System.Windows.Forms.MenuStrip`` to the
actual top-level pywebview WinForms owner.  The HTML document never substitutes
for the Windows application menu.
"""

import json
from typing import Any, Callable


_LABELS_UK = {
    "file": "Файл", "game": "Гра", "board": "Дошка", "analysis": "Аналіз", "library": "Бібліотека",
    "settings": "Налаштування", "help": "Довідка",
    "new": "Нова стандартна позиція", "empty": "Порожня дошка", "exit": "Вихід",
    "undo": "Скасувати хід", "redo": "Повторити хід",
    "engine_play_new": "Нова гра проти Stockfish",
    "history_previous": "Попередня позиція в історії", "history_next": "Наступна позиція в історії",
    "history_go": "Перейти до ходу", "board_go": "Перейти на дошку",
    "move_input": "Поле введення ходу", "position_input": "Текстовий редактор позиції",
    "engine_toggle": "Увімкнути / вимкнути Stockfish",
    "analysis_restart": "Перезапустити аналіз",
    "analysis_lock": "Зафіксувати ціль / стежити за позицією",
    "analysis_previous_pv": "Попередній варіант",
    "analysis_next_pv": "Наступний варіант",
    "analysis_explore": "Тимчасово переглянути варіант",
    "analysis_return": "Повернутися до джерела",
    "analysis_insert_move": "Вставити вибраний хід",
    "analysis_insert_line": "Вставити вибраний варіант",
    "books_open": "Книги",
    "training_open": "Тренування",
    "book_previous": "Попередній блок книги",
    "book_next": "Наступний блок книги",
    "book_chess": "Відкрити шаховий блок",
    "book_return": "Повернутися до тексту книги",
    "book_bookmark": "Зберегти закладку",
    "training_hint": "Підказка",
    "training_reveal": "Показати рішення",
    "training_reset": "Скинути вправу",
    "training_analyse": "Аналізувати вправу",
    "training_close": "Закрити вправу",
    "keyboard": "Клавіатура і команди",
    "keyboard_reset": "Відновити всі клавіші та команди",
    "keyboard_reset_done": "Усі клавіші та команди відновлено за замовчуванням.",
    "keyboard_reset_failed": "Не вдалося відновити клавіші та команди.",
    "help_open": "Клавіші та довідка NVDA",
}

_LABELS_EN = {
    "file": "File", "game": "Game", "board": "Board", "analysis": "Analysis", "library": "Library",
    "settings": "Settings", "help": "Help",
    "new": "New standard position", "empty": "Empty board", "exit": "Exit",
    "undo": "Undo move", "redo": "Redo move",
    "engine_play_new": "New game against Stockfish",
    "history_previous": "Previous history position", "history_next": "Next history position",
    "history_go": "Go to move", "board_go": "Go to board",
    "move_input": "Move input", "position_input": "Position text editor",
    "engine_toggle": "Enable / disable Stockfish",
    "analysis_restart": "Restart analysis",
    "analysis_lock": "Lock target / follow position",
    "analysis_previous_pv": "Previous variation",
    "analysis_next_pv": "Next variation",
    "analysis_explore": "Temporarily explore variation",
    "analysis_return": "Return to source",
    "analysis_insert_move": "Insert selected move",
    "analysis_insert_line": "Insert selected variation",
    "books_open": "Books",
    "training_open": "Training",
    "book_previous": "Previous book block",
    "book_next": "Next book block",
    "book_chess": "Open chess block",
    "book_return": "Return to book text",
    "book_bookmark": "Save bookmark",
    "training_hint": "Hint",
    "training_reveal": "Reveal solution",
    "training_reset": "Reset exercise",
    "training_analyse": "Analyse exercise",
    "training_close": "Close exercise",
    "keyboard": "Keyboard and commands",
    "keyboard_reset": "Reset all keyboard commands",
    "keyboard_reset_done": "All keyboard commands were reset to defaults.",
    "keyboard_reset_failed": "Keyboard commands could not be reset.",
    "help_open": "Keys and NVDA help",
}

_MNEMONIC = {
    "uk": {"file": "&Файл", "game": "&Гра", "board": "&Дошка", "analysis": "&Аналіз", "library": "&Бібліотека", "settings": "&Налаштування", "help": "&Довідка"},
    "en": {"file": "&File", "game": "&Game", "board": "&Board", "analysis": "&Analysis", "library": "&Library", "settings": "&Settings", "help": "&Help"},
}


def _labels(lang: str) -> dict[str, str]:
    return _LABELS_EN if lang == "en" else _LABELS_UK


def _same_managed_object(left: Any, right: Any) -> bool:
    """Compare Python.NET managed objects without relying on proxy identity.

    Python ``is`` is not a valid ownership check for CLR objects: repeated
    property access may yield a different Python proxy for the same managed
    instance.  Prefer CLR reference identity, then managed ``Equals``, then
    normal equality for test doubles/non-CLR callers.
    """
    if left is right:
        return True
    if left is None or right is None:
        return False
    try:
        from System import Object  # type: ignore

        if bool(Object.ReferenceEquals(left, right)):
            return True
    except Exception:
        pass
    try:
        equals = getattr(left, "Equals", None)
        if callable(equals) and bool(equals(right)):
            return True
    except Exception:
        pass
    try:
        return bool(left == right)
    except Exception:
        return False


def active_binding(api: Any, action_id: str) -> str | None:
    try:
        rows = api.keymap_search("", None)
    except Exception:
        return None
    for row in rows:
        if str(row.get("action_id")) == action_id and str(row.get("value_kind")) == "shortcut":
            value = row.get("value")
            return str(value) if value else None
    return None


def menu_caption(api: Any, label: str, action_id: str | None = None) -> str:
    if not action_id:
        return label
    binding = active_binding(api, action_id)
    return f"{label}\t{binding}" if binding else label


def _js_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def reset_all_keybindings(api: Any, js: Callable[[str], None], *, lang: str = "uk") -> bool:
    text = _labels(lang)
    try:
        result = api.keymap_reset_all()
    except Exception:
        js(f"announce({_js_string(text['keyboard_reset_failed'])})")
        return False
    if not isinstance(result, dict) or not result.get("ok"):
        js(f"announce({_js_string(text['keyboard_reset_failed'])})")
        return False
    js(
        "localStorage.removeItem('accessibleChess.keymap.v1');"
        f"announce({_js_string(text['keyboard_reset_done'])});"
        "location.reload()"
    )
    return True


def _safe_js(window: Any, code: str) -> None:
    if window is None:
        return
    try:
        window.evaluate_js(code)
    except Exception:
        pass


def _invoke_api(window: Any, fn: Callable[[], Any]) -> None:
    try:
        fn()
    finally:
        _safe_js(window, "refreshState()")


def _optional_api_action(api: Any, name: str, *args: Any) -> Any:
    """Invoke newer menu actions without breaking older compatible API doubles."""

    action = getattr(api, name, None)
    return action(*args) if callable(action) else None


def make_keymap_menu(webview: Any, api: Any, window_holder: dict[str, Any]):
    """Legacy presentation projection used only by tests/compatibility."""
    Menu = webview.menu.Menu
    MenuAction = webview.menu.MenuAction
    MenuSeparator = webview.menu.MenuSeparator
    text = _labels(getattr(api, "lang", "uk"))

    def window():
        return window_holder.get("window")

    def js(code: str) -> None:
        _safe_js(window(), code)

    def refresh(fn):
        return lambda: _invoke_api(window(), fn)

    return [
        Menu(text["file"], [
            MenuAction(text["new"], refresh(api.new_game)),
            MenuAction(text["empty"], refresh(api.clear_board)),
            MenuSeparator(),
            MenuAction(text["exit"], lambda: window() and window().destroy()),
        ]),
        Menu(text["game"], [
            MenuAction(text["engine_play_new"], lambda: js("openEngineGameDialog()")),
            MenuSeparator(),
            MenuAction(menu_caption(api, text["undo"], "edit.undo"), refresh(api.undo)),
            MenuAction(menu_caption(api, text["redo"], "edit.redo"), refresh(api.redo)),
            MenuSeparator(),
            MenuAction(menu_caption(api, text["history_previous"], "history.previous"), refresh(api.review_previous)),
            MenuAction(menu_caption(api, text["history_next"], "history.next"), refresh(api.review_next)),
            MenuAction(menu_caption(api, text["history_go"], "history.go_to_move"), lambda: js("focusHistoryJump()")),
        ]),
        Menu(text["board"], [
            MenuAction(text["board_go"], lambda: js("enterBoard()")),
            MenuAction(text["move_input"], lambda: js("document.getElementById('move-input').focus()")),
            MenuAction(text["position_input"], lambda: js("document.getElementById('position-input').focus()")),
        ]),
        Menu(text["analysis"], [
            MenuAction(text["engine_toggle"], refresh(api.toggle_engine)),
            MenuAction(menu_caption(api, text["analysis_restart"], "analysis.restart"), refresh(lambda: _optional_api_action(api, "restart_analysis"))),
            MenuSeparator(),
            MenuAction(menu_caption(api, text["analysis_previous_pv"], "analysis.previous_pv"), refresh(lambda: _optional_api_action(api, "select_relative_analysis_pv", -1))),
            MenuAction(menu_caption(api, text["analysis_next_pv"], "analysis.next_pv"), refresh(lambda: _optional_api_action(api, "select_relative_analysis_pv", 1))),
            MenuAction(menu_caption(api, text["analysis_lock"], "analysis.lock_target"), refresh(lambda: _optional_api_action(api, "toggle_analysis_lock"))),
            MenuAction(menu_caption(api, text["analysis_explore"], "analysis.explore_pv"), refresh(lambda: _optional_api_action(api, "explore_analysis_pv"))),
            MenuAction(menu_caption(api, text["analysis_return"], "analysis.return"), refresh(lambda: _optional_api_action(api, "return_from_analysis"))),
            MenuSeparator(),
            MenuAction(menu_caption(api, text["analysis_insert_move"], "analysis.insert_move"), refresh(lambda: _optional_api_action(api, "insert_analysis_move"))),
            MenuAction(menu_caption(api, text["analysis_insert_line"], "analysis.insert_line"), refresh(lambda: _optional_api_action(api, "insert_analysis_line"))),
        ]),
        Menu(text["library"], [
            MenuAction(text["books_open"], lambda: js("openBooksPanel()")),
            MenuAction(text["training_open"], lambda: js("openTrainingPanel()")),
            MenuSeparator(),
            MenuAction(menu_caption(api, text["book_previous"], "book_reader.previous_block"), refresh(lambda: _optional_api_action(api, "book_previous_block"))),
            MenuAction(menu_caption(api, text["book_next"], "book_reader.next_block"), refresh(lambda: _optional_api_action(api, "book_next_block"))),
            MenuAction(menu_caption(api, text["book_chess"], "book_reader.open_chess_block"), refresh(lambda: _optional_api_action(api, "open_book_chess_block"))),
            MenuAction(menu_caption(api, text["book_return"], "book_reader.return_to_text"), refresh(lambda: _optional_api_action(api, "return_to_book_text"))),
            MenuAction(menu_caption(api, text["book_bookmark"], "book_reader.bookmark"), refresh(lambda: _optional_api_action(api, "save_bookmark"))),
            MenuSeparator(),
            MenuAction(menu_caption(api, text["training_hint"], "training.hint"), refresh(lambda: _optional_api_action(api, "request_training_hint"))),
            MenuAction(menu_caption(api, text["training_reveal"], "training.reveal_solution"), refresh(lambda: _optional_api_action(api, "reveal_training_solution"))),
            MenuAction(menu_caption(api, text["training_reset"], "training.reset"), refresh(lambda: _optional_api_action(api, "reset_training"))),
            MenuAction(menu_caption(api, text["training_analyse"], "training.analyse"), refresh(lambda: _optional_api_action(api, "analyze_training_position"))),
            MenuAction(menu_caption(api, text["training_close"], "training.close"), refresh(lambda: _optional_api_action(api, "close_training"))),
        ]),
        Menu(text["settings"], [
            MenuAction(text["keyboard"], lambda: js("document.getElementById('key-search').focus()")),
            MenuSeparator(),
            MenuAction(text["keyboard_reset"], lambda: reset_all_keybindings(api, js, lang=getattr(api, "lang", "uk"))),
        ]),
        Menu(text["help"], [MenuAction(text["help_open"], lambda: js("document.getElementById('help').focus()"))]),
    ]


def _resolve_windows_host_form(window: Any) -> Any | None:
    """Resolve the top-level WinForms Form that actually owns WebView2."""
    native = getattr(window, "native", None)
    if native is None:
        return None

    candidates: list[Any] = []
    webview_control = getattr(native, "webview", None)
    if webview_control is not None:
        try:
            found = webview_control.FindForm()
            if found is not None:
                candidates.append(found)
        except Exception:
            pass
        top = getattr(webview_control, "TopLevelControl", None)
        if top is not None:
            candidates.append(top)

    try:
        found = native.FindForm()
        if found is not None:
            candidates.append(found)
    except Exception:
        pass
    top = getattr(native, "TopLevelControl", None)
    if top is not None:
        candidates.append(top)
    candidates.append(native)

    for candidate in candidates:
        if candidate is None:
            continue
        if not hasattr(candidate, "Controls") or not hasattr(candidate, "MainMenuStrip"):
            continue
        try:
            if hasattr(candidate, "TopLevel") and not bool(candidate.TopLevel):
                continue
        except Exception:
            pass
        return candidate
    return None


def native_menu_attachment_state(window: Any) -> dict[str, bool]:
    """Return proxy-safe structural ownership state for Windows diagnostics."""
    host = getattr(window, "_accessible_chess_native_menu_host", None)
    menu = getattr(window, "_accessible_chess_native_menu", None)
    return {
        "host_exists": host is not None,
        "menu_exists": menu is not None,
        "host_top_level": bool(getattr(host, "TopLevel", False)) if host is not None else False,
        "parent_is_host": _same_managed_object(getattr(menu, "Parent", None), host) if menu is not None else False,
        "main_menu_strip_is_menu": _same_managed_object(getattr(host, "MainMenuStrip", None), menu) if host is not None else False,
    }


def install_windows_native_menu(window: Any, api: Any) -> bool:
    """Attach a real WinForms MenuStrip to the actual packaged host Form.

    QA must still verify the built executable and Oleksii must personally verify
    Alt/arrows/Enter/Esc with NVDA.  This function only owns native composition.
    """
    try:
        import clr  # type: ignore

        clr.AddReference("System.Windows.Forms")
        from System import Action  # type: ignore
        from System.Windows.Forms import (  # type: ignore
            AccessibleRole,
            DockStyle,
            MenuStrip,
            ToolStripMenuItem,
            ToolStripSeparator,
        )
    except Exception:
        return False

    form = _resolve_windows_host_form(window)
    if form is None:
        return False

    lang = "en" if getattr(api, "lang", "uk") == "en" else "uk"
    text = _labels(lang)
    mn = _MNEMONIC[lang]
    handlers: list[Any] = []

    def item(label: str, callback: Callable[[], Any] | None = None) -> Any:
        menu_item = ToolStripMenuItem(label)
        if callback is not None:
            def on_click(sender, event, cb=callback):
                cb()
            handlers.append(on_click)
            menu_item.Click += on_click
        return menu_item

    def submenu(label: str, children: list[Any]) -> Any:
        parent = ToolStripMenuItem(label)
        for child in children:
            parent.DropDownItems.Add(child)
        return parent

    def separator() -> Any:
        return ToolStripSeparator()

    menu = MenuStrip()
    menu.Name = "AccessibleChessMainMenu"
    menu.AccessibleName = "Application menu" if lang == "en" else "Меню програми"
    menu.AccessibleRole = AccessibleRole.MenuBar
    menu.Dock = DockStyle.Top
    menu.TabStop = False
    menu.Visible = True
    menu.Enabled = True

    top_menus = (
        submenu(mn["file"], [
            item(text["new"], lambda: _invoke_api(window, api.new_game)),
            item(text["empty"], lambda: _invoke_api(window, api.clear_board)),
            separator(), item(text["exit"], window.destroy),
        ]),
        submenu(mn["game"], [
            item(text["engine_play_new"], lambda: _safe_js(window, "openEngineGameDialog()")),
            separator(),
            item(menu_caption(api, text["undo"], "edit.undo"), lambda: _invoke_api(window, api.undo)),
            item(menu_caption(api, text["redo"], "edit.redo"), lambda: _invoke_api(window, api.redo)),
            separator(),
            item(menu_caption(api, text["history_previous"], "history.previous"), lambda: _invoke_api(window, api.review_previous)),
            item(menu_caption(api, text["history_next"], "history.next"), lambda: _invoke_api(window, api.review_next)),
            item(menu_caption(api, text["history_go"], "history.go_to_move"), lambda: _safe_js(window, "focusHistoryJump()")),
        ]),
        submenu(mn["board"], [
            item(text["board_go"], lambda: _safe_js(window, "enterBoard()")),
            item(text["move_input"], lambda: _safe_js(window, "document.getElementById('move-input').focus()")),
            item(text["position_input"], lambda: _safe_js(window, "document.getElementById('position-input').focus()")),
        ]),
        submenu(mn["analysis"], [
            item(text["engine_toggle"], lambda: _invoke_api(window, api.toggle_engine)),
            item(menu_caption(api, text["analysis_restart"], "analysis.restart"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "restart_analysis"))),
            separator(),
            item(menu_caption(api, text["analysis_previous_pv"], "analysis.previous_pv"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "select_relative_analysis_pv", -1))),
            item(menu_caption(api, text["analysis_next_pv"], "analysis.next_pv"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "select_relative_analysis_pv", 1))),
            item(menu_caption(api, text["analysis_lock"], "analysis.lock_target"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "toggle_analysis_lock"))),
            item(menu_caption(api, text["analysis_explore"], "analysis.explore_pv"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "explore_analysis_pv"))),
            item(menu_caption(api, text["analysis_return"], "analysis.return"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "return_from_analysis"))),
            separator(),
            item(menu_caption(api, text["analysis_insert_move"], "analysis.insert_move"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "insert_analysis_move"))),
            item(menu_caption(api, text["analysis_insert_line"], "analysis.insert_line"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "insert_analysis_line"))),
        ]),
        submenu(mn["library"], [
            item(text["books_open"], lambda: _safe_js(window, "openBooksPanel()")),
            item(text["training_open"], lambda: _safe_js(window, "openTrainingPanel()")),
            separator(),
            item(menu_caption(api, text["book_previous"], "book_reader.previous_block"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "book_previous_block"))),
            item(menu_caption(api, text["book_next"], "book_reader.next_block"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "book_next_block"))),
            item(menu_caption(api, text["book_chess"], "book_reader.open_chess_block"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "open_book_chess_block"))),
            item(menu_caption(api, text["book_return"], "book_reader.return_to_text"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "return_to_book_text"))),
            item(menu_caption(api, text["book_bookmark"], "book_reader.bookmark"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "save_bookmark"))),
            separator(),
            item(menu_caption(api, text["training_hint"], "training.hint"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "request_training_hint"))),
            item(menu_caption(api, text["training_reveal"], "training.reveal_solution"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "reveal_training_solution"))),
            item(menu_caption(api, text["training_reset"], "training.reset"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "reset_training"))),
            item(menu_caption(api, text["training_analyse"], "training.analyse"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "analyze_training_position"))),
            item(menu_caption(api, text["training_close"], "training.close"), lambda: _invoke_api(window, lambda: _optional_api_action(api, "close_training"))),
        ]),
        submenu(mn["settings"], [
            item(text["keyboard"], lambda: _safe_js(window, "document.getElementById('keymap-dialog').showModal();document.getElementById('key-search').focus()")),
            item(text["keyboard_reset"], lambda: reset_all_keybindings(api, lambda code: _safe_js(window, code), lang=lang)),
        ]),
        submenu(mn["help"], [item(text["help_open"], lambda: _safe_js(window, "document.getElementById('help-dialog').showModal();document.getElementById('help').focus()"))]),
    )
    for top in top_menus:
        menu.Items.Add(top)

    setattr(window, "_accessible_chess_native_menu", menu)
    setattr(window, "_accessible_chess_native_menu_handlers", handlers)
    setattr(window, "_accessible_chess_native_menu_host", form)

    def attach() -> None:
        form.SuspendLayout()
        try:
            stale = None
            for control in list(form.Controls):
                if getattr(control, "Name", "") == "AccessibleChessMainMenu":
                    stale = control
                    break
            if stale is not None and not _same_managed_object(stale, menu):
                form.Controls.Remove(stale)
                try:
                    stale.Dispose()
                except Exception:
                    pass

            form.MainMenuStrip = menu
            form.Controls.Add(menu)
            menu.BringToFront()
            form.PerformLayout()

            if not _same_managed_object(getattr(menu, "Parent", None), form):
                raise RuntimeError("native menu attached to wrong WinForms owner")
            if not _same_managed_object(getattr(form, "MainMenuStrip", None), menu):
                raise RuntimeError("native menu is not MainMenuStrip of host form")
        finally:
            form.ResumeLayout(True)

    try:
        if getattr(form, "InvokeRequired", False):
            form.Invoke(Action(attach))
        else:
            attach()
    except Exception:
        return False
    return True
