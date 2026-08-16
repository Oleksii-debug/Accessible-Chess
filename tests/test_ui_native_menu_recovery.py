from __future__ import annotations

import inspect
from types import SimpleNamespace

from acs.ui_native_menu import (
    install_windows_native_menu,
    make_keymap_menu,
    reset_all_keybindings,
)


class FakeMenuAction:
    def __init__(self, title, callback):
        self.title = title
        self.callback = callback


class FakeMenu:
    def __init__(self, title, items):
        self.title = title
        self.items = items


class FakeSeparator:
    pass


def fake_webview():
    return SimpleNamespace(
        menu=SimpleNamespace(
            Menu=FakeMenu,
            MenuAction=FakeMenuAction,
            MenuSeparator=FakeSeparator,
        )
    )


class FakeWindow:
    def __init__(self):
        self.calls: list[str] = []

    def evaluate_js(self, code: str) -> None:
        self.calls.append(code)


class FakeAPI:
    def __init__(self, *, lang: str = "uk", reset_ok: bool = True):
        self.lang = lang
        self.reset_ok = reset_ok
        self.reset_calls = 0

    def keymap_search(self, query, context):
        return []

    def keymap_reset_all(self):
        self.reset_calls += 1
        return {"ok": self.reset_ok, "message": "ok" if self.reset_ok else "failed"}

    def new_game(self):
        return {"ok": True}

    def clear_board(self):
        return {"ok": True}

    def undo(self):
        return {"ok": True}

    def redo(self):
        return {"ok": True}

    def review_previous(self):
        return {"ok": True}

    def review_next(self):
        return {"ok": True}

    def toggle_engine(self):
        return {"ok": True}


def _settings_actions(menus):
    settings = next(menu for menu in menus if menu.title in {"Налаштування", "Settings"})
    return [item for item in settings.items if isinstance(item, FakeMenuAction)]


def test_native_settings_menu_exposes_non_remappable_recovery_action() -> None:
    api = FakeAPI(lang="uk")
    window = FakeWindow()

    menus = make_keymap_menu(fake_webview(), api, {"window": window})
    titles = [item.title for item in _settings_actions(menus)]

    assert titles == ["Клавіатура і команди", "Відновити всі клавіші та команди"]


def test_native_recovery_resets_core_then_clears_only_legacy_keymap_cache() -> None:
    api = FakeAPI(lang="en")
    window = FakeWindow()
    menus = make_keymap_menu(fake_webview(), api, {"window": window})
    recovery = next(
        item for item in _settings_actions(menus)
        if item.title == "Reset all keyboard commands"
    )

    recovery.callback()

    assert api.reset_calls == 1
    assert len(window.calls) == 1
    script = window.calls[0]
    assert "localStorage.removeItem('accessibleChess.keymap.v1')" in script
    assert "All keyboard commands were reset to defaults." in script
    assert "location.reload()" in script
    assert "clear()" not in script


def test_reset_helper_does_not_reload_when_authoritative_reset_fails() -> None:
    api = FakeAPI(lang="uk", reset_ok=False)
    calls: list[str] = []

    result = reset_all_keybindings(api, calls.append, lang="uk")

    assert result is False
    assert api.reset_calls == 1
    assert len(calls) == 1
    assert "Не вдалося відновити клавіші та команди." in calls[0]
    assert "location.reload()" not in calls[0]
    assert "localStorage.removeItem" not in calls[0]


def test_reset_helper_handles_bridge_failure_without_destroying_other_data() -> None:
    class BrokenAPI(FakeAPI):
        def keymap_reset_all(self):
            self.reset_calls += 1
            raise RuntimeError("bridge unavailable")

    api = BrokenAPI(lang="en")
    calls: list[str] = []

    result = reset_all_keybindings(api, calls.append, lang="en")

    assert result is False
    assert api.reset_calls == 1
    assert len(calls) == 1
    assert "Keyboard commands could not be reset." in calls[0]
    assert "location.reload()" not in calls[0]


def test_production_native_menu_is_a_real_form_child_menustrip_with_uia_role() -> None:
    """Source-level contract for the Windows-only composition.

    Linux unit CI cannot prove the Windows accessibility tree. This guards the
    exact composition properties that QA must validate on the packaged EXE:
    a native MenuStrip child, assigned as MainMenuStrip, with MenuBar role.
    """
    source = inspect.getsource(install_windows_native_menu)

    assert "MenuStrip" in source
    assert "ToolStripMenuItem" in source
    assert "AccessibleRole.MenuBar" in source
    assert "form.MainMenuStrip = menu" in source
    assert "form.Controls.Add(menu)" in source
    assert "menu.BringToFront()" in source
    assert "MainMenu" not in source


def test_windows_package_gate_must_still_verify_real_uia_and_keyboard_semantics() -> None:
    source = inspect.getsource(install_windows_native_menu)

    assert "ControlType.MenuBar" in source
    assert "Alt/arrows/Enter/Esc" in source
