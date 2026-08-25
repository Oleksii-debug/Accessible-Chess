from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.full_product_actions import FullProductActionRouter
from acs.full_product_presenters import LibraryPresenter
from acs.full_product_ui_shell import AccessibleShellState, UILanguage
from acs.full_product_webview_adapter import FullProductWebViewAdapter
from acs.library_webview_bridge import LibraryWebViewBridge
from acs.library_webview_projection import LibraryWebViewProjection
from acs.search_service import GameSearchService


PGN = """[Event "Київ Open"]
[White "Олексій"]
[Black "Анна"]
[Result "1-0"]

1. e4 e5 1-0

[Event "Львів Open"]
[White "Богдан"]
[Black "ОЛЕКСІЙ"]
[Result "0-1"]

1. d4 d5 0-1

[Event "Одеса Open"]
[White "Олексій"]
[Black "Віра"]
[Result "1/2-1/2"]

1. c4 e5 1/2-1/2

[Event "Дніпро Open"]
[White "Ганна"]
[Black "Олексій"]
[Result "*"]

1. Nf3 d5 *

[Event "Control"]
[White "Delta"]
[Black "Echo"]
[Result "1-0"]

1. e4 c5 1-0
"""


class LibraryWorkspaceUiIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = AcsDatabase()
        self.report = self.database.import_pgn_text(
            PGN,
            source_name=r"C:\Users\private\library-uk.pgn",
        )
        self.open_calls: list[tuple[str, dict[str, object]]] = []

        def delegate(action_id: str, payload: dict[str, object]):
            copied = dict(payload)
            self.open_calls.append((action_id, copied))
            if action_id == "library.open_game":
                return self.database.get_game(int(copied["game_id"]))
            return None

        self.shell = AccessibleShellState(language=UILanguage.UA)
        router = FullProductActionRouter(self.shell, delegate)
        self.shell_adapter = FullProductWebViewAdapter(self.shell, router)
        presenter = LibraryPresenter(
            GameSearchService(self.database),
            language=UILanguage.UA,
        )
        projection = LibraryWebViewProjection(
            presenter,
            delegate,
            language=UILanguage.UA,
        )
        self.projection = projection
        self.bridge = LibraryWebViewBridge(projection)

    def tearDown(self) -> None:
        self.database.close()

    def test_real_database_search_page_select_open_and_exact_return_context(self) -> None:
        entered = self.shell_adapter.activate_action(
            "screen.library",
            current_focus_id="board-square-e4",
        )
        self.assertEqual("route", entered.kind)
        self.assertEqual("library-search-player", entered.payload["focus_target"])

        searched = self.bridge.dispatch(
            "library.search",
            {"player": "олексій", "limit": "2"},
        )
        first = searched.payload["snapshot"]
        self.assertEqual("ready", first["status"])
        self.assertEqual(2, len(first["rows"]))
        self.assertTrue(first["actions"][1]["enabled"])
        self.assertNotIn("Users", repr(first))
        self.assertNotIn("private", repr(first).casefold())

        second_page = self.bridge.dispatch("library.next_page", {}).payload["snapshot"]
        self.assertEqual(2, len(second_page["rows"]))
        selected_game_id = int(second_page["rows"][1]["game_id"])
        selected = self.bridge.dispatch(
            "library.select",
            {"game_id": selected_game_id},
        ).payload["snapshot"]
        selected_focus = str(selected["focus_target"])
        self.assertEqual(selected_game_id, selected["selected_game_id"])

        self.shell_adapter.record_focus(selected_focus)
        opened = self.bridge.dispatch("library.open_game", {})
        self.assertEqual("delegated", opened.kind)
        self.assertEqual({"action": "library.open_game"}, dict(opened.payload))
        self.assertEqual("library.open_game", self.open_calls[-1][0])
        self.assertEqual(selected_game_id, self.open_calls[-1][1]["game_id"])
        self.assertIsNotNone(self.database.get_game(selected_game_id))

        left = self.shell_adapter.activate_action(
            "screen.pgn",
            current_focus_id=selected_focus,
        )
        self.assertEqual("pgn", left.payload["route_id"])
        returned = self.shell_adapter.activate_action(
            "screen.library",
            current_focus_id="pgn-game-list",
        )
        self.assertEqual(selected_focus, returned.payload["focus_target"])

        restored = self.projection.snapshot()
        self.assertEqual("олексій", self.projection.query.player)
        self.assertEqual(2, self.projection.query.limit)
        self.assertEqual(selected_game_id, restored["selected_game_id"])
        self.assertEqual(
            [row["game_id"] for row in second_page["rows"]],
            [row["game_id"] for row in restored["rows"]],
        )
        self.assertEqual(selected_focus, restored["focus_target"])

    def test_invalid_browser_payload_and_ctrl_editing_shortcuts_are_non_destructive(self) -> None:
        self.bridge.dispatch("library.search", {"player": "Олексій", "limit": "2"})
        before = self.projection.snapshot()
        rejected = self.bridge.dispatch(
            "library.search",
            {"player": "Олексій", "after_game_id": 2},
        )
        self.assertEqual("error", rejected.kind)
        self.assertEqual(before, self.projection.snapshot())

        for key in "acxvzy":
            with self.subTest(key=key):
                policy = self.shell_adapter.keydown_policy(
                    key=key,
                    modifiers=["Ctrl"],
                    tag_name="input",
                )
                self.assertFalse(policy.payload["global_keymap"])
                self.assertFalse(policy.payload["prevent_default"])


if __name__ == "__main__":
    unittest.main()
