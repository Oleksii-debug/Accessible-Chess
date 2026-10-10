from __future__ import annotations

"""Section 51 keyboard native menu and safe post-shutdown export acceptance."""

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from acs.full_product_native_menu import NativeMenuItemKind
from acs.version2_profile import (
    Version2NativeMenuController,
    build_version2_router,
    build_version2_shell,
    build_version2_webview_adapter,
)
from acs.version2_release_ui import (
    Version2ReleaseAccessibleChessAPI,
    run_version2_release_window,
)
from tests.test_version2_release_ui import _Application, _WebView


class Section51NativeOwnerBackupTests(unittest.TestCase):
    def _menu(self, *, owner_export_callback=None):
        shell = build_version2_shell()
        router = build_version2_router(shell, lambda _a, _p: None)
        adapter = build_version2_webview_adapter(shell, router)
        return Version2NativeMenuController(
            adapter,
            lambda _value: None,
            exit_callback=lambda: None,
            owner_export_callback=owner_export_callback,
        )

    def test_export_menu_is_opt_in_and_keeps_existing_menu_actions(self):
        original = self._menu()
        self.assertFalse(
            any(item.host_command == "owner.export_all"
                for menu in original.spec() for item in menu.items)
        )
        calls: list[str] = []
        enabled = self._menu(owner_export_callback=lambda: calls.append("requested"))
        self.assertEqual(
            tuple(menu.menu_id for menu in original.spec()),
            tuple(menu.menu_id for menu in enabled.spec()),
        )
        base_actions = {
            item.action_id
            for menu in original.spec() for item in menu.items
            if item.kind is NativeMenuItemKind.ACTION
        }
        new_actions = {
            item.action_id
            for menu in enabled.spec() for item in menu.items
            if item.kind is NativeMenuItemKind.ACTION
        }
        self.assertEqual(base_actions, new_actions)
        file_menu = next(menu for menu in enabled.spec() if menu.menu_id == "file")
        backup = next(
            item for item in file_menu.items if item.host_command == "owner.export_all"
        )
        self.assertIn("копію", backup.label)
        self.assertEqual(enabled.activate(backup), None)
        self.assertEqual(calls, ["requested"])

    def test_shipping_final_product_menu_wires_the_same_backup_host(self):
        from acs.version2_final_product_profile import (
            FinalProductNativeMenuController,
            build_final_product_router,
            build_final_product_shell,
            build_final_product_webview_adapter,
        )

        shell = build_final_product_shell()
        router = build_final_product_router(shell, lambda _a, _p: None)
        adapter = build_final_product_webview_adapter(shell, router)
        notified = []
        controller = FinalProductNativeMenuController(
            adapter,
            lambda _value: None,
            exit_callback=lambda: None,
            owner_export_callback=lambda: notified.append("requested"),
        )
        menu = next(item for item in controller.spec() if item.menu_id == "file")
        entries = [
            item for item in menu.items
            if item.host_command == "owner.export_all"
        ]
        self.assertEqual(len(entries), 1)
        self.assertIn("копію", entries[0].label)
        self.assertIsNone(controller.activate(entries[0]))
        self.assertEqual(notified, ["requested"])

    def test_export_command_requires_callable_host_callback(self):
        with self.assertRaises(TypeError):
            self._menu(owner_export_callback="not callable")

    def test_gui_backup_runs_after_full_application_shutdown(self):
        with tempfile.TemporaryDirectory() as td:
            api = Version2ReleaseAccessibleChessAPI(
                keymap_path=Path(td) / "keymap.json"
            )
            app = _Application()
            app.progress_store = SimpleNamespace(path=Path(td) / "profile" / "training.json")
            view = _WebView()
            controller = []

            def installer(_window, menu):
                controller.append(menu)
                return True

            real_start = view.start

            def request_backup_from_native_menu(**kwargs):
                # The owner interacts with File menu while writers are open.
                # The action must schedule export, not copy live state.
                view.started = kwargs
                view.window.events.before_show.fire()
                file_menu = next(
                    menu for menu in controller[0].spec()
                    if menu.menu_id == "file"
                )
                owner_action = next(
                    item for item in file_menu.items
                    if item.host_command == "owner.export_all"
                )
                controller[0].activate(owner_action)
                self.assertFalse(app.closed)
                view.window.events.loaded.fire()

            view.start = request_backup_from_native_menu
            copied = []

            def export_after_close(layout):
                self.assertTrue(app.closed)
                self.assertTrue(view.window.destroyed)
                copied.append(layout.root)
                return Path(td) / "backup"

            with mock.patch(
                "acs.user_data_transfer.export_owner_profile",
                side_effect=export_after_close,
            ):
                run_version2_release_window(
                    api,
                    app,
                    webview_module=view,
                    menu_installer=installer,
                )
            self.assertEqual(copied, [Path(td) / "profile"])

    def test_failed_shutdown_never_runs_owner_backup(self):
        with tempfile.TemporaryDirectory() as td:
            api = Version2ReleaseAccessibleChessAPI(
                keymap_path=Path(td) / "keymap.json"
            )

            class BadShutdown(_Application):
                def shutdown(self):
                    raise RuntimeError("shutdown refusal")

            app = BadShutdown()
            app.progress_store = SimpleNamespace(path=Path(td) / "profile" / "training.json")
            view = _WebView()
            controllers = []

            def start(**_kwargs):
                view.window.events.before_show.fire()
                host = next(
                    item for menu in controllers[0].spec() for item in menu.items
                    if item.host_command == "owner.export_all"
                )
                controllers[0].activate(host)

            view.start = start
            with mock.patch(
                "acs.user_data_transfer.export_owner_profile"
            ) as export:
                with self.assertRaisesRegex(RuntimeError, "shutdown refusal"):
                    run_version2_release_window(
                        api,
                        app,
                        webview_module=view,
                        menu_installer=lambda _window, menu: controllers.append(menu) or True,
                    )
                export.assert_not_called()


if __name__ == "__main__":
    unittest.main()
