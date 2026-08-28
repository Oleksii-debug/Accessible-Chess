from __future__ import annotations

import unittest

from acs.full_product_actions import FullProductActionRouter, build_full_product_action_registry
from acs.full_product_native_menu import NativeMenuItemKind, build_full_product_menu_spec
from acs.full_product_ui_shell import AccessibleShellState, ROUTES, UILanguage
from acs.full_product_webview_adapter import FullProductWebViewAdapter
from acs.version2_profile import (
    VERSION2_ROUTE_IDS,
    VERSION2_TOP_MENU_IDS,
    Version2NativeMenuController,
    build_version2_action_registry,
    build_version2_menu_spec,
    build_version2_router,
    build_version2_shell,
    build_version2_webview_adapter,
    validate_version2_profile,
)


class Version2WindowsCompositionProfileTests(unittest.TestCase):
    def _composition(self):
        delegated: list[tuple[str, dict[str, object]]] = []

        def delegate(action_id: str, payload: dict[str, object]):
            delegated.append((action_id, dict(payload)))
            return {"ok": True}

        registry = build_version2_action_registry()
        shell = build_version2_shell(language=UILanguage.EN)
        router = build_version2_router(shell, delegate, registry=registry)
        adapter = build_version2_webview_adapter(shell, router)
        return registry, shell, router, adapter, delegated

    def test_profile_validates_and_exposes_only_version2_routes(self):
        validate_version2_profile()
        registry, shell, _router, adapter, _delegated = self._composition()
        snapshot = adapter.snapshot()
        self.assertEqual(
            tuple(item["route_id"] for item in snapshot["navigation"]),
            VERSION2_ROUTE_IDS,
        )
        self.assertEqual(shell.current_route.route_id, "board")
        self.assertNotIn("training", VERSION2_ROUTE_IDS)
        self.assertNotIn("teacher", VERSION2_ROUTE_IDS)
        self.assertNotIn("classes", VERSION2_ROUTE_IDS)
        for action_id in (
            "screen.training",
            "screen.teacher",
            "screen.classes",
            "training.submit",
            "teacher.pointer_input",
            "student.move",
            "classes.open",
            "remote.connect",
        ):
            with self.assertRaises(KeyError):
                registry.definition(action_id)

    def test_deferred_route_cannot_change_version2_shell_or_leak_internal_id(self):
        _registry, shell, _router, adapter, _delegated = self._composition()
        before = shell.semantic_snapshot()
        result = adapter.activate_action("screen.teacher", current_focus_id="move-input")
        self.assertEqual(result.kind, "error")
        self.assertEqual(result.payload["message"], "The action could not be completed.")
        self.assertEqual(shell.semantic_snapshot(), before)
        with self.assertRaises(ValueError):
            shell.open_route("teacher", current_focus_id="move-input")
        self.assertEqual(shell.current_route.route_id, "board")

    def test_version2_routes_keep_full_product_focus_restoration_semantics(self):
        _registry, shell, _router, adapter, _delegated = self._composition()
        library = adapter.activate_action("screen.library", current_focus_id="move-input")
        self.assertEqual(library.kind, "route")
        self.assertEqual(library.payload["route_id"], "library")
        self.assertEqual(library.payload["focus_target"], "library-search-player")
        adapter.record_focus("library-result-17")
        board = adapter.activate_action("screen.board", current_focus_id="library-result-17")
        self.assertEqual(board.kind, "route")
        self.assertEqual(board.payload["focus_target"], "move-input")
        back = adapter.activate_action("screen.library", current_focus_id="move-input")
        self.assertEqual(back.payload["focus_target"], "library-result-17")

    def test_version2_domain_actions_delegate_through_one_action_router(self):
        _registry, _shell, _router, adapter, delegated = self._composition()
        for action_id in ("pgn.open", "library.search", "book.open_position"):
            result = adapter.activate_action(action_id, {"source": "test"})
            self.assertEqual(result.kind, "delegated")
            self.assertEqual(result.payload, {"action_id": action_id})
        self.assertEqual(
            delegated,
            [
                ("pgn.open", {"source": "test"}),
                ("library.search", {"source": "test"}),
                ("book.open_position", {"source": "test"}),
            ],
        )

    def test_standard_editing_shortcuts_remain_native_in_version2_edit_controls(self):
        _registry, _shell, _router, adapter, _delegated = self._composition()
        for key in ("a", "c", "x", "v", "z", "y"):
            policy = adapter.keydown_policy(
                key=key,
                modifiers=("Ctrl",),
                tag_name="input",
            )
            self.assertEqual(policy.kind, "keydown-policy")
            self.assertFalse(policy.payload["global_keymap"])
            self.assertFalse(policy.payload["prevent_default"])
            self.assertTrue(policy.payload["editable"])

    def test_version2_native_menu_reuses_owner_spec_without_deferred_surfaces(self):
        registry, _shell, _router, _adapter, _delegated = self._composition()
        spec = build_version2_menu_spec(registry, language=UILanguage.EN)
        self.assertEqual(tuple(menu.menu_id for menu in spec), VERSION2_TOP_MENU_IDS)
        self.assertNotIn("training", VERSION2_TOP_MENU_IDS)
        self.assertNotIn("teacher", VERSION2_TOP_MENU_IDS)
        for menu in spec:
            for item in menu.items:
                if item.kind is NativeMenuItemKind.ACTION:
                    registry.definition(item.action_id)
                    self.assertFalse(item.action_id.startswith("training."))
                    self.assertFalse(item.action_id.startswith("teacher."))
                    self.assertFalse(item.action_id.startswith("classes."))
                    self.assertFalse(item.action_id.startswith("remote."))

    def test_version2_native_controller_delegates_activation_to_owner_controller(self):
        _registry, _shell, _router, adapter, delegated = self._composition()
        commands = []
        exits = []
        controller = Version2NativeMenuController(
            adapter,
            commands.append,
            exit_callback=lambda: exits.append(True),
            current_focus_provider=lambda: "library-search-player",
        )
        library_menu = next(menu for menu in controller.spec() if menu.menu_id == "library")
        search = next(item for item in library_menu.items if item.action_id == "library.search")
        command = controller.activate(search)
        self.assertIsNotNone(command)
        self.assertEqual(command.kind, "delegated")
        self.assertEqual(commands, [command])
        self.assertEqual(delegated, [("library.search", {})])
        self.assertEqual(exits, [])

    def test_long_term_full_product_preview_remains_intact_outside_version2_profile(self):
        full_registry = build_full_product_action_registry()
        full_shell = AccessibleShellState(language=UILanguage.EN)
        full_router = FullProductActionRouter(full_shell, lambda action_id, payload: None, registry=full_registry)
        full_adapter = FullProductWebViewAdapter(full_shell, full_router)
        route_ids = tuple(item["route_id"] for item in full_adapter.snapshot()["navigation"])
        self.assertEqual(route_ids, tuple(route.route_id for route in ROUTES))
        self.assertIn("training", route_ids)
        self.assertIn("teacher", route_ids)
        self.assertIn("classes", route_ids)
        full_menu = build_full_product_menu_spec(full_registry, language=UILanguage.EN)
        full_menu_ids = tuple(menu.menu_id for menu in full_menu)
        self.assertIn("training", full_menu_ids)
        self.assertIn("teacher", full_menu_ids)


if __name__ == "__main__":
    unittest.main()
