from __future__ import annotations

import unittest
from unittest.mock import patch

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

    def test_failed_language_snapshot_restores_application_shell_locale(self):
        adapter, _ = self.make_adapter()
        before = adapter.snapshot()
        self.assertEqual("uk", before["document"]["lang"])

        with patch.object(
            adapter,
            "snapshot",
            side_effect=RuntimeError("candidate semantic snapshot rejected"),
        ):
            with self.assertRaisesRegex(RuntimeError, "candidate semantic snapshot rejected"):
                adapter.set_language("en")

        restored = adapter.snapshot()
        self.assertEqual("uk", restored["document"]["lang"])
        self.assertEqual(before["screen"]["heading"], restored["screen"]["heading"])

        committed = adapter.set_language("en")
        self.assertEqual("en", committed.payload["document"]["lang"])
        self.assertNotEqual(before["screen"]["heading"], committed.payload["screen"]["heading"])

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

    def test_failed_route_snapshot_restores_route_but_preserves_observed_focus(self):
        adapter, calls = self.make_adapter()
        before = adapter.snapshot()
        self.assertEqual("board", before["screen"]["route_id"])
        self.assertEqual("move-input", adapter.shell.restore_focus_target())

        with patch.object(
            adapter,
            "snapshot",
            side_effect=RuntimeError("candidate route snapshot rejected"),
        ):
            failed = adapter.activate_action(
                "screen.teacher",
                current_focus_id="board-launcher",
            )

        self.assertEqual("error", failed.kind)
        self.assertEqual("board", adapter.shell.current_route.route_id)
        self.assertEqual("board-launcher", adapter.shell.restore_focus_target())
        self.assertEqual([], calls)

        committed = adapter.activate_action(
            "screen.teacher",
            current_focus_id="board-launcher",
        )
        self.assertEqual("route", committed.kind)
        self.assertEqual("teacher", committed.payload["route_id"])
        self.assertEqual("teacher", adapter.shell.current_route.route_id)
        adapter.shell.open_route("board")
        self.assertEqual("board-launcher", adapter.shell.restore_focus_target())

    def test_delegate_failure_restores_shell_route_and_preserves_observed_focus(self):
        shell = AccessibleShellState(language=UILanguage.EN)

        def delegate(action_id, payload):
            self.assertEqual("teacher.highlight", action_id)
            self.assertEqual({"square": "f3"}, payload)
            shell.open_route("teacher")
            raise RuntimeError("provider failed after route mutation")

        adapter = FullProductWebViewAdapter(
            shell,
            FullProductActionRouter(shell, delegate),
        )
        failed = adapter.activate_action(
            "teacher.highlight",
            {"square": "f3"},
            current_focus_id="board-launcher",
        )

        self.assertEqual("error", failed.kind)
        self.assertEqual("board", shell.current_route.route_id)
        self.assertEqual("board-launcher", shell.restore_focus_target())
        self.assertEqual(
            "The action could not be completed.",
            failed.payload["message"],
        )

    def test_delegate_internal_focus_mutation_does_not_replace_observed_ingress_focus(self):
        shell = AccessibleShellState(language=UILanguage.EN)

        def delegate(action_id, payload):
            self.assertEqual("teacher.highlight", action_id)
            shell.record_focus("delegate-only-focus")
            shell.open_route("teacher")
            raise RuntimeError("provider mutated focus before failure")

        adapter = FullProductWebViewAdapter(
            shell,
            FullProductActionRouter(shell, delegate),
        )
        failed = adapter.activate_action(
            "teacher.highlight",
            {"square": "f3"},
            current_focus_id="board-launcher",
        )

        self.assertEqual("error", failed.kind)
        self.assertEqual("board", shell.current_route.route_id)
        self.assertEqual("board-launcher", shell.restore_focus_target())

    def test_delegated_route_transition_preserves_invoking_focus(self):
        shell = AccessibleShellState(language=UILanguage.EN)

        def delegate(action_id, payload):
            self.assertEqual(action_id, "teacher.highlight")
            self.assertEqual(payload, {"square": "f3"})
            shell.open_route("teacher")

        adapter = FullProductWebViewAdapter(
            shell,
            FullProductActionRouter(shell, delegate),
        )
        command = adapter.activate_action(
            "teacher.highlight",
            {"square": "f3"},
            current_focus_id="board-launcher",
        )

        self.assertEqual(command.kind, "delegated")
        self.assertEqual(shell.current_route.route_id, "teacher")
        shell.open_route("board")
        self.assertEqual(shell.restore_focus_target(), "board-launcher")

    def test_repeated_delegated_round_trips_restore_latest_invoking_focus(self):
        shell = AccessibleShellState(
            language=UILanguage.EN,
            initial_route="books",
        )

        def delegate(action_id, payload):
            self.assertEqual(action_id, "teacher.highlight")
            self.assertEqual(payload, {"square": "f3"})
            shell.open_route("board")

        adapter = FullProductWebViewAdapter(
            shell,
            FullProductActionRouter(shell, delegate),
        )

        for focus_id in ("book-block-1", "book-block-3"):
            command = adapter.activate_action(
                "teacher.highlight",
                {"square": "f3"},
                current_focus_id=focus_id,
            )
            self.assertEqual(command.kind, "delegated")
            self.assertEqual(shell.current_route.route_id, "board")

            shell.open_route("books")
            self.assertEqual(shell.restore_focus_target(), focus_id)

    def test_malformed_delegated_focus_fails_before_domain_dispatch(self):
        adapter, calls = self.make_adapter()
        for focus_id in (
            "bad focus",
            "book.block",
            "\x00",
            " move-input",
            "move-input ",
            "x" * 161,
        ):
            with self.subTest(focus_id=repr(focus_id)):
                command = adapter.activate_action(
                    "teacher.highlight",
                    {"square": "f3"},
                    current_focus_id=focus_id,
                )
                self.assertEqual(command.kind, "error")
                self.assertEqual(adapter.shell.current_route.route_id, "board")
                self.assertEqual(adapter.shell.restore_focus_target(), "move-input")
                self.assertEqual(calls, [])

    def test_unknown_action_does_not_preserve_unrecorded_focus(self):
        adapter, calls = self.make_adapter()
        command = adapter.activate_action(
            "not.a.real.action",
            current_focus_id="board-launcher",
        )
        self.assertEqual("error", command.kind)
        self.assertEqual("move-input", adapter.shell.restore_focus_target())
        self.assertEqual([], calls)

    def test_domain_action_is_delegated_unchanged(self):
        adapter, calls = self.make_adapter()
        command = adapter.activate_action("teacher.highlight", {"square": "f3"})
        self.assertEqual(command.kind, "delegated")
        self.assertEqual(command.payload, {"action_id": "teacher.highlight"})
        self.assertEqual(calls, [("teacher.highlight", {"square": "f3"})])

    def test_domain_backend_return_value_never_crosses_into_webview(self):
        secret = r"C:\\Users\\Teacher\\private\\lesson.sqlite"
        shell = AccessibleShellState(language=UILanguage.EN)
        adapter = FullProductWebViewAdapter(
            shell,
            FullProductActionRouter(shell, lambda _action, _payload: {"path": secret}),
        )
        command = adapter.activate_action("library.import")
        self.assertEqual(command.payload, {"action_id": "library.import"})
        self.assertNotIn(secret, repr(command))

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

    def test_active_focus_and_dialog_text_subclasses_fail_before_shell_mutation(self):
        adapter, _ = self.make_adapter()

        class HostileText(str):
            touched = False

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("active text hook must not execute")

        hostile_focus = HostileText("board-launcher")
        with self.assertRaisesRegex(TypeError, "focus target id"):
            adapter.record_focus(hostile_focus)
        self.assertFalse(HostileText.touched)
        self.assertEqual("move-input", adapter.shell.restore_focus_target())

        hostile_dialog = HostileText("settings-dialog")
        failed = adapter.open_dialog(
            hostile_dialog,
            opener_focus_id="open-settings",
            initial_focus_id="settings-list",
        )
        self.assertEqual("error", failed.kind)
        self.assertFalse(HostileText.touched)
        self.assertIsNone(adapter.shell.active_dialog_id)

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
        self.assertEqual("help-search", adapter.shell.restore_focus_target())

    def test_internal_delegate_error_is_sanitized_before_webview_projection(self):
        shell = AccessibleShellState(language=UILanguage.EN)

        def delegate(action_id, payload):
            raise PermissionError(r"C:\Users\name\secret.sqlite")

        adapter = FullProductWebViewAdapter(shell, FullProductActionRouter(shell, delegate))
        command = adapter.activate_action("library.search", {"query": "x"})
        self.assertEqual(command.kind, "error")
        self.assertEqual(command.payload["message"], "The action could not be completed.")
        self.assertNotIn("secret", command.payload["message"])


    def test_language_abort_restores_application_shell_locale(self):
        class AbortSignal(BaseException):
            pass

        adapter, _ = self.make_adapter()
        before = adapter.snapshot()
        with patch.object(
            adapter,
            "snapshot",
            side_effect=AbortSignal("private locale abort"),
        ):
            with self.assertRaises(AbortSignal):
                adapter.set_language("en")

        restored = adapter.snapshot()
        self.assertEqual("uk", restored["document"]["lang"])
        self.assertEqual(before["screen"]["heading"], restored["screen"]["heading"])

    def test_delegate_abort_restores_shell_route_and_projects_safe_error(self):
        class AbortSignal(BaseException):
            pass

        shell = AccessibleShellState(language=UILanguage.EN)

        def delegate(action_id, payload):
            self.assertEqual("teacher.highlight", action_id)
            shell.open_route("teacher")
            raise AbortSignal("private provider abort")

        adapter = FullProductWebViewAdapter(
            shell,
            FullProductActionRouter(shell, delegate),
        )
        failed = adapter.activate_action(
            "teacher.highlight",
            {"square": "f3"},
            current_focus_id="board-launcher",
        )

        self.assertEqual("error", failed.kind)
        self.assertEqual("board", shell.current_route.route_id)
        self.assertEqual("board-launcher", shell.restore_focus_target())
        self.assertNotIn("private provider abort", repr(failed))

    def test_route_snapshot_abort_restores_route_and_observed_focus(self):
        class AbortSignal(BaseException):
            pass

        adapter, _ = self.make_adapter()
        with patch.object(
            adapter,
            "snapshot",
            side_effect=AbortSignal("private route render abort"),
        ):
            failed = adapter.activate_action(
                "screen.teacher",
                current_focus_id="board-launcher",
            )

        self.assertEqual("error", failed.kind)
        self.assertEqual("board", adapter.shell.current_route.route_id)
        self.assertEqual("board-launcher", adapter.shell.restore_focus_target())
        self.assertNotIn("private route render abort", repr(failed))

    def test_open_dialog_abort_restores_dialog_stack(self):
        class AbortSignal(BaseException):
            pass

        adapter, _ = self.make_adapter()
        original_open = adapter.shell.open_dialog

        def abort_after_open(*args, **kwargs):
            original_open(*args, **kwargs)
            raise AbortSignal("private dialog-open abort")

        with patch.object(adapter.shell, "open_dialog", side_effect=abort_after_open):
            failed = adapter.open_dialog(
                "settings-dialog",
                opener_focus_id="open-settings",
                initial_focus_id="settings-list",
            )

        self.assertEqual("error", failed.kind)
        self.assertIsNone(adapter.shell.active_dialog_id)
        self.assertEqual("move-input", adapter.shell.restore_focus_target())
        self.assertNotIn("private dialog-open abort", repr(failed))

    def test_close_dialog_abort_restores_dialog_and_focus_contract(self):
        class AbortSignal(BaseException):
            pass

        adapter, _ = self.make_adapter()
        opened = adapter.open_dialog(
            "settings-dialog",
            opener_focus_id="open-settings",
            initial_focus_id="settings-list",
        )
        self.assertEqual("dialog-open", opened.kind)
        original_close = adapter.shell.close_dialog

        def abort_after_close(*args, **kwargs):
            original_close(*args, **kwargs)
            raise AbortSignal("private dialog-close abort")

        with patch.object(adapter.shell, "close_dialog", side_effect=abort_after_close):
            failed = adapter.close_dialog("settings-dialog")

        self.assertEqual("error", failed.kind)
        self.assertEqual("settings-dialog", adapter.shell.active_dialog_id)
        self.assertEqual("settings-list", adapter.shell.restore_focus_target())
        self.assertNotIn("private dialog-close abort", repr(failed))


if __name__ == "__main__":
    unittest.main()
