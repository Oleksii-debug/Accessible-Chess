from __future__ import annotations

from dataclasses import dataclass
import threading
import unittest

from acs.version2_application import Version2Application


@dataclass
class Route:
    route_id: str


class Shell:
    def __init__(self, route_id="board", dialog=None):
        self.current_route = Route(route_id)
        self.active_dialog_id = dialog


class DispatchResult:
    def __init__(self, value):
        self.value = value


class Router:
    def __init__(self):
        self.calls = []

    def dispatch(self, action_id, payload, *, current_focus_id=""):
        self.calls.append((action_id, dict(payload), current_focus_id))
        return DispatchResult({"ok": True})


class TactileApplicationIngressTests(unittest.TestCase):
    def app(self, *, route="board", dialog=None):
        app = Version2Application.__new__(Version2Application)
        app._thread = threading.get_ident()
        app.shell = Shell(route, dialog)
        app.router = Router()
        app._focus = "board-square"
        return app

    def test_visible_board_command_uses_existing_router(self):
        app = self.app()
        value = app._dispatch_tactile_action("board.current", {})
        self.assertEqual({"ok": True}, value)
        self.assertEqual(
            [("board.current", {}, "board-square")],
            app.router.calls,
        )

    def test_hidden_board_rejects_before_dispatch(self):
        app = self.app(route="books")
        with self.assertRaises(ValueError):
            app._dispatch_tactile_action("board.current", {})
        self.assertEqual([], app.router.calls)

    def test_active_dialog_rejects_before_dispatch(self):
        app = self.app(dialog="settings")
        with self.assertRaises(ValueError):
            app._dispatch_tactile_action("board.current", {})
        self.assertEqual([], app.router.calls)

    def test_wrong_thread_rejects_before_dispatch(self):
        app = self.app()
        app._thread = threading.get_ident() + 1
        with self.assertRaises(RuntimeError):
            app._dispatch_tactile_action("board.current", {})
        self.assertEqual([], app.router.calls)


if __name__ == "__main__":
    unittest.main()
