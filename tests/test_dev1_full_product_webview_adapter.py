from __future__ import annotations

import unittest

from acs.full_product_actions import FullProductActionRouter
from acs.full_product_ui_shell import AccessibleShellState, UILanguage
from acs.full_product_webview_adapter import FullProductWebViewAdapter


class FullProductWebViewAdapterTests(unittest.TestCase):
    def make_adapter(self):
        calls = []

        def delegate(action_id, payload):
            calls.append((action_id, payload))
            return {"ok": True, "action_id": action_id}

        shell = AccessibleShellState(language=UILanguage.UA)
        router = FullProductActionRouter(shell, delegate)
        return FullProductWebViewAdapter(shell, router), calls

    def test_snapshot_projects_bilingual_semantics_and_registered_navigation(self):
        adapter, _ = self.make_adapter()
        snap = adapter.snapshot()
        self.assertEqual(snap["document"]["lang"], "uk")
        self.assertEqual(snap["document"]["heading_level"], 1)
        self.assertEqual(snap["screen"]["route_id"], "board")
        self.assertTrue(any(item["action_id"] == "screen.teacher" for item in snap["navigation"]))

    def test_language_switch_rerenders_without_changing_route(self):
        adapter, _ = self.make_adapter()
        command = adapter.set_language("en")
        self.assertEqual(command.kind, "render")
        self.assertEqual(command.payload["screen"]["route_id"], "board")
        self.assertEqual(command.payload["document"]["lang"], "en")

    def test_unknown_language_fails_closed(self):
        adapter, _ = self.make_adapter()
        with self.assertRaises(ValueError):
            adapter.set_language("de")

    def test_route_action_uses_single_router_and_restores_focus(self):
        adapter, calls = self.make_adapter()
        adapter.record_focus("move-input")
        command = adapter.activate_action("screen.teacher", current_focus_id="move-input")
        self.assertEqual(command.kind, "route")
        self.assertEqual(command.payload["route_id"], "teacher")
        self.assertEqual(command.payload["focus_target"], "teacher-pointer-input")
        self.assertEqual(calls, [])

    def test_domain_action_is_delegated_unchanged(self):
        adapter, calls = self.make_adapter()
        command = adapter.activate_action("teacher.highlight", {"square": "f3"})
        self.assertEqual(command.kind, "delegated")
        self.assertEqual(calls, [("teacher.highlight", {"square": "f3"})])

    def test_unknown_action_projects_safe_user_error(self):
        adapter, _ = self.make_adapter()
        command = adapter.activate_action("not.a.real.action")
        self.assertEqual(command.kind, "error")
        self.assertNotIn("KeyError", command.payload["message"])
        self.assertNotIn("not.a.real.action", command.payload["message"])

    def test_standard_editing_shortcuts_are_never_stolen_from_input(self):
        adapter, _ = self.make_adapter()
        for key in "acxvzy":
            with self.subTest(key=key):
                command = adapter.keydown_policy(key=key, modifiers=["Ctrl"], tag_name="input")
                self.assertFalse(command.payload["global_keymap"])
                self.assertFalse(command.payload["prevent_default"])
                self.assertTrue(command.payload["editable"])

    def test_standard_editing_shortcuts_are_never_stolen_from_contenteditable(self):
        adapter, _ = self.make_adapter()
        command = adapter.keydown_policy(
            key="c", modifiers=["Ctrl"], tag_name="div", content_editable=True
        )
        self.assertFalse(command.payload["global_keymap"])
        self.assertFalse(command.payload["prevent_default"])
        self.assertTrue(command.payload["editable"])

    def test_non_editable_global_shortcut_remains_available(self):
        adapter, _ = self.make_adapter()
        command = adapter.keydown_policy(key="p", modifiers=["Ctrl", "Alt"], tag_name="div")
        self.assertTrue(command.payload["global_keymap"])
        self.assertTrue(command.payload["prevent_default"])
        self.assertFalse(command.payload["editable"])

    def test_dialog_open_close_restores_exact_opener(self):
        adapter, _ = self.make_adapter()
        opened = adapter.open_dialog(
            "settings-dialog",
            opener_focus_id="open-settings",
            initial_focus_id="settings-list",
        )
        self.assertEqual(opened.kind, "dialog-open")
        self.assertEqual(opened.payload["focus_target"], "settings-list")
        closed = adapter.close_dialog("settings-dialog")
        self.assertEqual(closed.kind, "dialog-close")
        self.assertEqual(closed.payload["focus_target"], "open-settings")

    def test_route_change_while_dialog_open_projects_error_instead_of_breaking_focus(self):
        adapter, _ = self.make_adapter()
        adapter.open_dialog(
            "help-dialog",
            opener_focus_id="help-button",
            initial_focus_id="help-search",
        )
        command = adapter.activate_action("screen.teacher", current_focus_id="help-search")
        self.assertEqual(command.kind, "error")
        self.assertEqual(adapter.shell.current_route.route_id, "board")
        self.assertEqual(adapter.shell.active_dialog_id, "help-dialog")

    def test_internal_delegate_error_is_sanitized_before_webview_projection(self):
        shell = AccessibleShellState(language=UILanguage.EN)

        def delegate(action_id, payload):
            raise PermissionError(r"C:\Users\name\secret.sqlite")

        adapter = FullProductWebViewAdapter(shell, FullProductActionRouter(shell, delegate))
        command = adapter.activate_action("library.search", {"query": "x"})
        self.assertEqual(command.kind, "error")
        self.assertEqual(command.payload["message"], "The action could not be completed.")
        self.assertNotIn("secret", command.payload["message"])


if __name__ == "__main__":
    unittest.main()
