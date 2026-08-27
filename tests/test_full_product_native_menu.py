from __future__ import annotations

from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
import sys
import unittest

from acs.full_product_actions import FullProductActionRouter, build_full_product_action_registry
from acs.full_product_native_menu import (
    FullProductNativeMenuController,
    NativeMenuItemKind,
    build_full_product_menu_spec,
    install_full_product_windows_native_menu,
)
from acs.full_product_ui_shell import AccessibleShellState, UILanguage
from acs.full_product_webview_adapter import FullProductWebViewAdapter
from acs.ui_native_menu import native_menu_attachment_state


class EventHook:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self) -> None:
        for handler in tuple(self.handlers):
            handler(None, None)


class ItemCollection(list):
    def Add(self, item) -> None:
        self.append(item)


class FakeMenuItem:
    def __init__(self, label: str) -> None:
        self.Text = label
        self.DropDownItems = ItemCollection()
        self.Click = EventHook()


class FakeSeparator:
    pass


class FakeMenuStrip:
    def __init__(self) -> None:
        self.Name = ""
        self.AccessibleName = ""
        self.AccessibleRole = None
        self.Dock = None
        self.TabStop = True
        self.Visible = False
        self.Enabled = False
        self.Parent = None
        self.Items = ItemCollection()

    def BringToFront(self) -> None:
        pass


class FakeControls(list):
    def __init__(self, owner) -> None:
        super().__init__()
        self.owner = owner

    def Add(self, item) -> None:
        item.Parent = self.owner
        self.append(item)

    def Remove(self, item) -> None:
        item.Parent = None
        super().remove(item)


class FakeForm:
    def __init__(self) -> None:
        self.TopLevel = True
        self.MainMenuStrip = None
        self.InvokeRequired = False
        self.Controls = FakeControls(self)

    def SuspendLayout(self) -> None:
        pass

    def ResumeLayout(self, _perform: bool) -> None:
        pass

    def PerformLayout(self) -> None:
        pass


@contextmanager
def fake_winforms():
    names = ("clr", "System", "System.Windows.Forms")
    previous = {name: sys.modules.get(name) for name in names}
    clr = ModuleType("clr")
    clr.AddReference = lambda _name: None
    system = ModuleType("System")
    system.Action = lambda callback: callback
    forms = ModuleType("System.Windows.Forms")
    forms.AccessibleRole = SimpleNamespace(MenuBar="MenuBar")
    forms.DockStyle = SimpleNamespace(Top="Top")
    forms.MenuStrip = FakeMenuStrip
    forms.ToolStripMenuItem = FakeMenuItem
    forms.ToolStripSeparator = FakeSeparator
    sys.modules.update({"clr": clr, "System": system, "System.Windows.Forms": forms})
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def make_controller(*, language=UILanguage.EN, bindings=None):
    calls = []
    commands = []
    exits = []
    shell = AccessibleShellState(language=language)
    registry = build_full_product_action_registry(bindings=bindings)

    def delegate(action_id, payload):
        calls.append((action_id, dict(payload)))
        return {"ok": True}

    adapter = FullProductWebViewAdapter(
        shell,
        FullProductActionRouter(shell, delegate, registry=registry),
    )
    controller = FullProductNativeMenuController(
        adapter,
        commands.append,
        exit_callback=lambda: exits.append(True),
        current_focus_provider=lambda: "board-square-e4",
    )
    return controller, calls, commands, exits


class FullProductNativeMenuTests(unittest.TestCase):
    def test_inventory_is_complete_localized_and_registry_validated(self) -> None:
        registry = build_full_product_action_registry(
            bindings={"analysis.restart": "Ctrl+Alt+R"}
        )
        menus = build_full_product_menu_spec(registry, language=UILanguage.EN)
        self.assertEqual(
            [
                "file", "game", "position", "pgn", "library", "import", "export",
                "engine", "analysis", "books", "training", "teacher", "settings", "help",
            ],
            [menu.menu_id for menu in menus],
        )
        self.assertEqual("&Teacher/Classroom", menus[11].label)
        actions = [
            item
            for menu in menus
            for item in menu.items
            if item.kind is NativeMenuItemKind.ACTION
        ]
        for item in actions:
            registry.definition(item.action_id)
        restart = next(item for item in menus[7].items if item.action_id == "analysis.restart")
        self.assertTrue(restart.label.endswith("\tCtrl+Alt+R"))
        ua = build_full_product_menu_spec(registry, language=UILanguage.UA)
        self.assertEqual("&Файл", ua[0].label)
        self.assertEqual("&Учитель/Клас", ua[11].label)

    def test_native_and_webview_actions_share_router_and_focus_restoration(self) -> None:
        controller, calls, commands, exits = make_controller()
        library = next(
            item for item in controller.spec()[4].items if item.action_id == "screen.library"
        )
        command = controller.activate(library)
        self.assertEqual("route", command.kind)
        self.assertEqual("library", command.payload["route_id"])
        self.assertEqual("library-search-player", command.payload["focus_target"])
        self.assertEqual([], calls)
        self.assertEqual([command], commands)

        import_item = controller.spec()[5].items[0]
        delegated = controller.activate(import_item)
        self.assertEqual("delegated", delegated.kind)
        self.assertEqual([("library.import", {})], calls)
        exit_item = next(
            item for item in controller.spec()[0].items if item.kind is NativeMenuItemKind.HOST
        )
        self.assertIsNone(controller.activate(exit_item))
        self.assertEqual([True], exits)

    def test_real_menu_installer_attaches_one_extended_menustrip_to_owner(self) -> None:
        controller, _calls, commands, _exits = make_controller()
        form = FakeForm()
        window = SimpleNamespace(native=form)
        with fake_winforms():
            self.assertTrue(install_full_product_windows_native_menu(window, controller))
        state = native_menu_attachment_state(window)
        self.assertTrue(all(state.values()))
        menu = window._accessible_chess_native_menu
        self.assertEqual("AccessibleChessFullProductMenu", menu.Name)
        self.assertEqual("MenuBar", menu.AccessibleRole)
        self.assertEqual(14, len(menu.Items))
        self.assertIs(form.MainMenuStrip, menu)
        library_top = next(top for top in menu.Items if top.Text == "&Library")
        library_top.DropDownItems[0].Click.fire()
        self.assertEqual("route", commands[-1].kind)
        self.assertEqual("library", commands[-1].payload["route_id"])


if __name__ == "__main__":
    unittest.main()
