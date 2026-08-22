from __future__ import annotations

import unittest

from acs.full_product_presenters import LibraryPresenter
from acs.full_product_ui_shell import UILanguage
from acs.library_webview_bridge import LibraryWebViewBridge
from acs.library_webview_projection import LibraryWebViewProjection
from acs.search_service import GameSearchItem, GameSearchPage


class Service:
    def __init__(self) -> None:
        self.calls = []

    def search(self, query):
        self.calls.append(query)
        row = GameSearchItem(
            game_id=11,
            source_id=2,
            source_name="safe.pgn",
            source_format="pgn",
            source_index=0,
            import_status="full",
            white="A",
            black="B",
            event="E",
            site=None,
            game_date=None,
            round=None,
            result="*",
            eco=None,
            opening=None,
            start_fen="SECRET-FEN",
        )
        return GameSearchPage((row,), None, False)


class LibraryWebViewBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = Service()
        self.domain = []

        def dispatch(action_id, payload):
            self.domain.append((action_id, dict(payload)))
            return {"secret": "TOKEN", "path": r"C:\\private\\x"}

        presenter = LibraryPresenter(self.service, language=UILanguage.EN)
        projection = LibraryWebViewProjection(presenter, dispatch, language=UILanguage.EN)
        self.bridge = LibraryWebViewBridge(projection)
        self.search_payload = {
            "player": "",
            "event": "",
            "eco": "",
            "opening": "",
            "result": "",
            "source_name": "",
        }

    def test_exact_search_payload_routes_without_arbitrary_action_dispatch(self) -> None:
        event = self.bridge.dispatch("library.search", self.search_payload)
        self.assertEqual("render", event.kind)
        self.assertEqual(1, len(self.service.calls))
        self.assertEqual([], self.domain)

    def test_unknown_command_extra_fields_and_scalar_payload_fail_closed(self) -> None:
        bad = self.bridge.dispatch("board.input", {})
        extra = self.bridge.dispatch("library.search", {**self.search_payload, "sql": "DROP TABLE games"})
        scalar = self.bridge.dispatch("library.search", "player=A")
        for result in (bad, extra, scalar):
            self.assertEqual("error", result.kind)
            self.assertNotIn("board.input", repr(result))
            self.assertNotIn("DROP TABLE", repr(result))
        self.assertEqual([], self.service.calls)
        self.assertEqual([], self.domain)

    def test_boolean_game_id_and_delta_are_rejected(self) -> None:
        self.bridge.dispatch("library.search", self.search_payload)
        for command, payload in (
            ("library.select", {"game_id": True}),
            ("library.move", {"delta": True}),
            ("library.move", {"delta": 0}),
        ):
            result = self.bridge.dispatch(command, payload)
            self.assertEqual("error", result.kind)
        self.assertEqual([], self.domain)

    def test_open_and_external_commands_discard_backend_return(self) -> None:
        self.bridge.dispatch("library.search", self.search_payload)
        opened = self.bridge.dispatch("library.open", {})
        imported = self.bridge.dispatch("library.import", {})
        exported = self.bridge.dispatch("library.export", {})
        text = repr((opened, imported, exported))
        self.assertNotIn("TOKEN", text)
        self.assertNotIn("private", text)
        self.assertEqual("library.open_game", self.domain[0][0])
        self.assertEqual(("library.import", {}), self.domain[1])
        self.assertEqual(("library.export", {}), self.domain[2])

    def test_filter_scalar_does_not_get_string_coerced(self) -> None:
        payload = dict(self.search_payload)
        payload["player"] = 123
        result = self.bridge.dispatch("library.search", payload)
        self.assertEqual("error", result.kind)
        self.assertEqual([], self.service.calls)


if __name__ == "__main__":
    unittest.main()
