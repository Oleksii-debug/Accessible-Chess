from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

from acs import webapp_keymap
from acs.ui_native_menu import (
    _resolve_windows_host_form,
    _same_managed_object,
    install_windows_native_menu,
    make_keymap_menu,
    native_menu_attachment_state,
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


def test_host_resolution_prefers_the_form_that_actually_owns_webview2() -> None:
    """A wrapper/native object must not win over WebView2's real FindForm owner."""
    real_form = SimpleNamespace(Controls=[], MainMenuStrip=None, TopLevel=True)

    class WebViewControl:
        TopLevelControl = real_form

        def FindForm(self):
            return real_form

    detached_wrapper = SimpleNamespace(
        Controls=[], MainMenuStrip=None, TopLevel=True, webview=WebViewControl()
    )
    window = SimpleNamespace(native=detached_wrapper)

    assert _resolve_windows_host_form(window) is real_form


def test_host_resolution_rejects_non_top_level_wrapper_when_real_form_missing() -> None:
    wrapper = SimpleNamespace(Controls=[], MainMenuStrip=None, TopLevel=False)
    window = SimpleNamespace(native=wrapper)

    assert _resolve_windows_host_form(window) is None


def test_managed_identity_does_not_depend_on_python_proxy_identity() -> None:
    class ManagedProxy:
        def __init__(self, managed_id: str):
            self.managed_id = managed_id

        def Equals(self, other):
            return getattr(other, "managed_id", None) == self.managed_id

    first = ManagedProxy("same-clr-object")
    second = ManagedProxy("same-clr-object")

    assert first is not second
    assert _same_managed_object(first, second) is True


def test_attachment_diagnostic_accepts_distinct_proxies_for_same_managed_objects() -> None:
    """Model repeated Python.NET property access returning fresh CLR proxies."""
    class ManagedProxy:
        def __init__(self, managed_id: str):
            self.managed_id = managed_id

        def Equals(self, other):
            return getattr(other, "managed_id", None) == self.managed_id

    host = ManagedProxy("host")
    host.TopLevel = True
    menu = ManagedProxy("menu")
    menu.Parent = ManagedProxy("host")
    host.MainMenuStrip = ManagedProxy("menu")
    window = SimpleNamespace(
        _accessible_chess_native_menu_host=host,
        _accessible_chess_native_menu=menu,
    )

    state = native_menu_attachment_state(window)

    assert menu.Parent is not host
    assert host.MainMenuStrip is not menu
    assert state == {
        "host_exists": True,
        "menu_exists": True,
        "host_top_level": True,
        "parent_is_host": True,
        "main_menu_strip_is_menu": True,
    }


def test_production_native_menu_targets_actual_webview_owner_and_checks_parent() -> None:
    source = inspect.getsource(install_windows_native_menu)
    resolver = inspect.getsource(_resolve_windows_host_form)

    assert "MenuStrip" in source
    assert "ToolStripMenuItem" in source
    assert "AccessibleRole.MenuBar" in source
    assert "_resolve_windows_host_form(window)" in source
    assert "webview_control.FindForm()" in resolver
    assert "webview_control, \"TopLevelControl\"" in resolver
    assert "form.MainMenuStrip = menu" in source
    assert "form.Controls.Add(menu)" in source
    assert "menu.BringToFront()" in source
    assert "_same_managed_object(getattr(menu, \"Parent\", None), form)" in source
    assert "_same_managed_object(getattr(form, \"MainMenuStrip\", None), menu)" in source
    assert "MainMenu(" not in source


def test_release_launcher_attaches_menu_at_before_show_host_lifecycle() -> None:
    source = inspect.getsource(webapp_keymap.main)

    assert "window.events.before_show += install_menu_on_native_host" in source
    assert "install_windows_native_menu(window, api)" in source
    assert "Accessible native Windows menu could not be attached" in source
    assert 'webview.start(gui="edgechromium", private_mode=True)' in source
    assert "webview.start(install_menu" not in source


def test_windows_package_gate_documents_real_uia_and_keyboard_semantics() -> None:
    smoke = Path("docs/WINDOWS_NATIVE_MENU_SMOKE.md").read_text(encoding="utf-8")

    assert "ControlType.MenuBar" in smoke
    assert "Alt" in smoke
    assert "Arrow" in smoke
    assert "Enter" in smoke
    assert "Esc" in smoke
    assert "NVDA" in smoke
    assert "native_menu_attachment_state" in smoke
