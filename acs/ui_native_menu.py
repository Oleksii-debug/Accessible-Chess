from __future__ import annotations

"""Windows-native menu for Accessible Chess.

Production attaches a real System.Windows.Forms.MenuStrip to the actual
pywebview WinForms host. The important part is ownership: packaged WebView2
builds can expose a different child/control hierarchy than source-level tests
suggest, so the menu is resolved against the native WebView's real FindForm /
TopLevelControl owner before attachment. A small legacy projection remains only
as a presentation/test helper; the release launcher never passes it to
pywebview.
"""

import json
from typing import Any, Callable


_LABELS_UK = {
    "file": "Файл", "game": "Гра", "board": "Дошка", "analysis": "Аналіз",
    "settings": "Налаштування", "help": "Довідка",
    "new": "Нова стандартна позиція", "empty": "Порожня дошка", "exit": "Вихід",
    "undo": "Скасувати хід", "redo": "Повторити хід",
    "history_previous": "Попередня позиція в історії", "history_next": "Наступна позиція в історії",
    "history_go": "Перейти до ходу", "board_go": "Перейти на дошку",
    "move_input": "Поле введення ходу", "position_input": "Текстовий редактор позиції",
    "engine_toggle": "Увімкнути / вимкнути Stockfish",
    "keyboard": "Клавіатура і команди",
    "keyboard_reset": "Відновити всі клавіші та команди",
    "keyboard_reset_done": "Усі клавіші та команди відновлено за замовчуванням.",
    "keyboard_reset_failed": "Не вдалося відновити клавіші та команди.",
    "help_open": "Клавіші та довідка NVDA",
}

_LABELS_EN = {
    "file": "File", "game": "Game", "board": "Board", "analysis": "Analysis",
    "settings": "Settings", "help": "Help",
    "new": "New standard position", "empty": "Empty board", "exit": "Exit",
    "undo": "Undo move", "redo": "Redo move",
    "history_previous": "Previous history position", "history_next": "Next history position",
    "history_go": "Go to move", "board_go": "Go to board",
    "move_input": "Move input", "position_input": "Position text editor",
    "engine_toggle": "Enable / disable Stockfish",
    "keyboard": "Keyboard and commands",
    "keyboard_reset": "Reset all keyboard commands",
    "keyboard_reset_done": "All keyboard commands were reset to defaults.",
    "keyboard_reset_failed": "Keyboard commands could not be reset.",
    "help_open": "Keys and NVDA help",
}

_MNEMONIC = {
    "uk": {"file": "&Файл", "game": "&Гра", "board": "&Дошка", "analysis": "&Аналіз", "settings": "&Налаштування", "help": "&Довідка"},
    "en": {"file": "&File", "game": "&Game", "board": "&Board", "analysis": "&Analysis", "settings": "&Settings", "help": "&Help"},
}


def _labels(lang: str) -> dict[str, str]:
    return _LABELS_EN if lang == "en" else _LABELS_UK


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


def make_keymap_menu(webview: Any, api: Any, window_holder: dict[str, Any]):
    """Legacy presentation projection for tests/compatibility only.

    The production launcher does not install this pywebview MenuStrip. It uses
    :func:`install_windows_native_menu` against the real WinForms host.
    """
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
        Menu(text["analysis"], [MenuAction(text["engine_toggle"], refresh(api.toggle_engine))]),
        Menu(text["settings"], [
            MenuAction(text["keyboard"], lambda: js("document.getElementById('key-search').focus()")),
            MenuSeparator(),
            MenuAction(text["keyboard_reset"], lambda: reset_all_keybindings(api, js, lang=getattr(api, "lang", "uk"))),
        ]),
        Menu(text["help"], [MenuAction(text["help_open"], lambda: js("document.getElementById('help').focus()"))]),
    ]


def _resolve_windows_host_form(window: Any) -> Any | None:
    """Return the real top-level WinForms Form that owns the WebView2 control.

    pywebview 5.x assigns ``window.native`` to BrowserForm, but packaged builds
    must not rely on that implementation detail alone. Resolve through the
    native WebView control's FindForm/TopLevelControl first when available and
    only then fall back to the native object itself. This makes ownership
    explicit and prevents attaching a MenuStrip to a detached/wrapper control
    that is absent from the top-level UIA subtree.
    """
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


def install_windows_native_menu(window: Any, api: Any) -> bool:
    """Attach a native WinForms MenuStrip to the actual packaged host Form.

    The menu is attached to the Form that actually owns the WebView2 control,
    not merely to whichever object happens to be present on ``window.native``.
    QA must still verify the built executable exposes ControlType.MenuBar and
    supports Alt/arrows/Enter/Esc through normal Windows/NVDA semantics.
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
        submenu(mn["analysis"], [item(text["engine_toggle"], lambda: _invoke_api(window, api.toggle_engine))]),
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
            # Remove only our own stale retry instance, never another app menu.
            stale = None
            for control in list(form.Controls):
                if getattr(control, "Name", "") == "AccessibleChessMainMenu":
                    stale = control
                    break
            if stale is not None and stale is not menu:
                form.Controls.Remove(stale)
                try:
                    stale.Dispose()
                except Exception:
                    pass

            form.MainMenuStrip = menu
            form.Controls.Add(menu)
            menu.BringToFront()
            form.PerformLayout()

            # Fail closed if the control was not attached to the exact owner
            # resolved from the packaged WebView2 host hierarchy.
            if getattr(menu, "Parent", None) is not form:
                raise RuntimeError("native menu attached to wrong WinForms owner")
            if getattr(form, "MainMenuStrip", None) is not menu:
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
