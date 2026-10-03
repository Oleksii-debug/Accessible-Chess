from __future__ import annotations

import unittest

from acs.full_product_actions import FullProductActionRouter, build_full_product_action_registry
from acs.full_product_native_menu import (
    FullProductNativeMenuController,
    NativeMenuItemKind,
    build_full_product_menu_spec,
)
from acs.full_product_ui_shell import AccessibleShellState, UILanguage
from acs.full_product_webview_adapter import FullProductWebViewAdapter
from acs.version2_profile import (
    Version2NativeMenuController,
    build_version2_action_registry,
    build_version2_menu_spec,
    build_version2_router,
    build_version2_shell,
    build_version2_webview_adapter,
)


class LibraryNativeRecoveryActionTests(unittest.TestCase):
    @staticmethod
    def _action_ids(menu) -> tuple[str, ...]:
        return tuple(
            item.action_id
            for item in menu.items
            if item.kind is NativeMenuItemKind.ACTION
        )

    def test_full_product_library_menu_exposes_page_navigation_in_order(self) -> None:
        registry = build_full_product_action_registry()
        spec = build_full_product_menu_spec(registry, language=UILanguage.EN)
        library = next(menu for menu in spec if menu.menu_id == "library")

        self.assertEqual(
            (
                "screen.library",
                "library.search",
                "library.reset_filters",
                "library.previous_page",
                "library.next_page",
                "library.open_game",
            ),
            self._action_ids(library),
        )
        labels = {
            item.action_id: item.label
            for item in library.items
            if item.kind is NativeMenuItemKind.ACTION
        }
        self.assertEqual("Previous Library page", labels["library.previous_page"])
        self.assertEqual("Next Library page", labels["library.next_page"])

    def test_full_product_import_menu_exposes_native_cancel_recovery(self) -> None:
        registry = build_full_product_action_registry()
        spec = build_full_product_menu_spec(registry, language=UILanguage.EN)
        import_menu = next(menu for menu in spec if menu.menu_id == "import")

        self.assertEqual(
            ("library.import", "library.cancel_import"),
            self._action_ids(import_menu),
        )
        cancel = next(
            item for item in import_menu.items
            if item.action_id == "library.cancel_import"
        )
        self.assertEqual("Cancel Library import", cancel.label)

    def test_ukrainian_native_labels_are_explicit_and_not_path_dependent(self) -> None:
        registry = build_full_product_action_registry()
        spec = build_full_product_menu_spec(registry, language=UILanguage.UA)
        library = next(menu for menu in spec if menu.menu_id == "library")
        import_menu = next(menu for menu in spec if menu.menu_id == "import")
        labels = {
            item.action_id: item.label
            for menu in (library, import_menu)
            for item in menu.items
            if item.kind is NativeMenuItemKind.ACTION
        }

        self.assertEqual(
            "Попередня сторінка бібліотеки",
            labels["library.previous_page"],
        )
        self.assertEqual(
            "Наступна сторінка бібліотеки",
            labels["library.next_page"],
        )
        self.assertEqual(
            "Скасувати імпорт до бібліотеки",
            labels["library.cancel_import"],
        )

    def test_version2_profile_keeps_all_three_native_recovery_actions(self) -> None:
        registry = build_version2_action_registry()
        spec = build_version2_menu_spec(registry, language=UILanguage.EN)
        library = next(menu for menu in spec if menu.menu_id == "library")
        import_menu = next(menu for menu in spec if menu.menu_id == "import")

        self.assertIn("library.previous_page", self._action_ids(library))
        self.assertIn("library.next_page", self._action_ids(library))
        self.assertIn("library.cancel_import", self._action_ids(import_menu))
        for action_id in (
            "library.previous_page",
            "library.next_page",
            "library.cancel_import",
        ):
            self.assertEqual(registry.definition(action_id).action_id, action_id)

    def test_full_product_native_controller_delegates_recovery_actions(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []
        commands = []
        shell = AccessibleShellState(language=UILanguage.EN)
        registry = build_full_product_action_registry()
        router = FullProductActionRouter(
            shell,
            lambda action, payload: calls.append((action, dict(payload))),
            registry=registry,
        )
        adapter = FullProductWebViewAdapter(shell, router)
        controller = FullProductNativeMenuController(
            adapter,
            commands.append,
            exit_callback=lambda: None,
            current_focus_provider=lambda: "library-search-player",
        )

        for action_id in (
            "library.previous_page",
            "library.next_page",
            "library.cancel_import",
        ):
            item = next(
                item
                for menu in controller.spec()
                for item in menu.items
                if item.kind is NativeMenuItemKind.ACTION
                and item.action_id == action_id
            )
            command = controller.activate(item)
            self.assertEqual("delegated", command.kind)
            self.assertEqual({"action_id": action_id}, dict(command.payload))

        self.assertEqual(
            [
                ("library.previous_page", {}),
                ("library.next_page", {}),
                ("library.cancel_import", {}),
            ],
            calls,
        )
        self.assertEqual(3, len(commands))

    def test_version2_native_controller_delegates_same_recovery_actions(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []
        commands = []
        shell = build_version2_shell(language=UILanguage.EN)
        registry = build_version2_action_registry()
        router = build_version2_router(
            shell,
            lambda action, payload: calls.append((action, dict(payload))),
            registry=registry,
        )
        adapter = build_version2_webview_adapter(shell, router)
        controller = Version2NativeMenuController(
            adapter,
            commands.append,
            exit_callback=lambda: None,
            current_focus_provider=lambda: "library-search-player",
        )

        for action_id in (
            "library.previous_page",
            "library.next_page",
            "library.cancel_import",
        ):
            item = next(
                item
                for menu in controller.spec()
                for item in menu.items
                if item.kind is NativeMenuItemKind.ACTION
                and item.action_id == action_id
            )
            command = controller.activate(item)
            self.assertEqual("delegated", command.kind)

        self.assertEqual(
            [
                ("library.previous_page", {}),
                ("library.next_page", {}),
                ("library.cancel_import", {}),
            ],
            calls,
        )
        self.assertEqual(3, len(commands))


if __name__ == "__main__":
    unittest.main()
