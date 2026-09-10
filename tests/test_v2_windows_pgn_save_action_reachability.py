from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from acs.full_product_actions import FullProductActionRouter, build_full_product_action_registry
from acs.full_product_native_menu import (
    FullProductNativeMenuController,
    NativeMenuItemKind,
    build_full_product_menu_spec,
)
from acs.full_product_ui_shell import AccessibleShellState, UILanguage
from acs.full_product_webview_adapter import FullProductWebViewAdapter
from acs.pgn_document import PgnDocumentSession
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)


class _Dialogs:
    def __init__(self) -> None:
        self.save_path: Path | None = None
        self.save_calls = 0

    def open_pgn(self) -> Path | None:
        return None

    def save_pgn_as(self, suggested_filename: str = "game.pgn") -> Path | None:
        self.save_calls += 1
        return self.save_path

    def select_library_import(self) -> Path | None:
        return None


class _UnusedLibrary:
    def import_games(self, *args, **kwargs):
        raise AssertionError("unexpected Library import")


class Version2WindowsPgnSaveActionReachabilityTests(unittest.TestCase):
    def _stack(self, destination: Path):
        dialogs = _Dialogs()
        dialogs.save_path = destination
        events = []
        commands = []
        session_box = {"value": PgnDocumentSession.new_game()}
        fallback = []

        def next_delegate(action_id, payload):
            fallback.append((action_id, dict(payload)))
            return None

        host = Version2WindowsFileActionDelegate(
            dialogs=dialogs,
            get_pgn_session=lambda: session_box["value"],
            set_pgn_session=lambda value: session_box.__setitem__("value", value),
            import_services_factory=lambda: Version2ImportWorkerServices(
                _UnusedLibrary(), None, lambda: None
            ),
            event_sink=events.append,
            next_delegate=next_delegate,
            current_focus_provider=lambda: "pgn-tree",
        )
        shell = AccessibleShellState(language=UILanguage.EN)
        registry = build_full_product_action_registry()
        router = FullProductActionRouter(shell, host, registry=registry)
        adapter = FullProductWebViewAdapter(shell, router)
        controller = FullProductNativeMenuController(
            adapter,
            commands.append,
            exit_callback=lambda: None,
            current_focus_provider=lambda: "pgn-tree",
        )
        return dialogs, events, commands, fallback, adapter, controller

    def test_action_registry_and_native_menu_expose_save_and_save_as(self) -> None:
        registry = build_full_product_action_registry()
        self.assertEqual(registry.definition("pgn.save").action_id, "pgn.save")
        self.assertEqual(registry.definition("pgn.save_as").action_id, "pgn.save_as")

        en = build_full_product_menu_spec(registry, language=UILanguage.EN)
        file_menu = next(menu for menu in en if menu.menu_id == "file")
        pgn_menu = next(menu for menu in en if menu.menu_id == "pgn")
        for menu in (file_menu, pgn_menu):
            ids = tuple(
                item.action_id
                for item in menu.items
                if item.kind is NativeMenuItemKind.ACTION
            )
            self.assertIn("pgn.save", ids)
            self.assertIn("pgn.save_as", ids)
        self.assertEqual(
            next(item.label for item in file_menu.items if item.action_id == "pgn.save"),
            "Save PGN",
        )
        self.assertEqual(
            next(item.label for item in file_menu.items if item.action_id == "pgn.save_as"),
            "Save PGN As",
        )

        ua = build_full_product_menu_spec(registry, language=UILanguage.UA)
        ua_file = next(menu for menu in ua if menu.menu_id == "file")
        self.assertEqual(
            next(item.label for item in ua_file.items if item.action_id == "pgn.save"),
            "Зберегти PGN",
        )
        self.assertEqual(
            next(item.label for item in ua_file.items if item.action_id == "pgn.save_as"),
            "Зберегти PGN як",
        )

    def test_native_menu_reaches_exact_trusted_host_without_browser_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "private-local-name.pgn"
            dialogs, events, commands, fallback, _adapter, controller = self._stack(destination)
            file_menu = next(menu for menu in controller.spec() if menu.menu_id == "file")
            save_as = next(item for item in file_menu.items if item.action_id == "pgn.save_as")
            save = next(item for item in file_menu.items if item.action_id == "pgn.save")

            command = controller.activate(save_as)
            self.assertEqual(command.kind, "delegated")
            self.assertEqual(dict(command.payload), {"action_id": "pgn.save_as"})
            self.assertTrue(destination.is_file())
            self.assertEqual(dialogs.save_calls, 1)
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.PGN_SAVED_AS)
            self.assertEqual(events[-1].focus_target, "pgn-tree")
            self.assertEqual(fallback, [])

            command = controller.activate(save)
            self.assertEqual(command.kind, "delegated")
            self.assertEqual(dict(command.payload), {"action_id": "pgn.save"})
            self.assertEqual(dialogs.save_calls, 1)
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.PGN_SAVED)
            self.assertEqual(events[-1].focus_target, "pgn-tree")

            for projected in (*commands, *events):
                text = repr(projected)
                self.assertNotIn(str(destination), text)
                self.assertNotIn("private-local-name", text)

    def test_browser_path_payload_fails_safely_before_native_save_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "target.pgn"
            dialogs, events, _commands, fallback, adapter, _controller = self._stack(destination)
            command = adapter.activate_action(
                "pgn.save_as",
                {"path": "C:/Users/private/secret.pgn"},
                current_focus_id="pgn-tree",
            )
            self.assertEqual(command.kind, "error")
            self.assertNotIn("C:/Users/private/secret.pgn", repr(command))
            self.assertNotIn("secret.pgn", repr(command))
            self.assertEqual(dialogs.save_calls, 0)
            self.assertEqual(events, [])
            self.assertEqual(fallback, [])


if __name__ == "__main__":
    unittest.main()
