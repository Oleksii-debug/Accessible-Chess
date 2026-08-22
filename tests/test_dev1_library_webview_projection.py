from __future__ import annotations

import unittest

from acs.full_product_presenters import LibraryPresenter
from acs.full_product_ui_shell import UILanguage
from acs.library_webview_projection import LibraryWebViewProjection
from acs.search_service import GameSearchItem, GameSearchPage


def item(game_id: int, *, source_name: str = "games.pgn", white: str = "White", black: str = "Black") -> GameSearchItem:
    return GameSearchItem(
        game_id=game_id,
        source_id=7,
        source_name=source_name,
        source_format="pgn",
        source_index=game_id - 1,
        import_status="full",
        white=white,
        black=black,
        event="Accessible Open",
        site="Kyiv",
        game_date="2026.08.22",
        round="1",
        result="1-0",
        eco="C20",
        opening="King's Pawn",
        start_fen="SECRET-FEN-MUST-NOT-ENTER-LIBRARY-SNAPSHOT",
    )


class FakeSearchService:
    def __init__(self) -> None:
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        if query.after_game_id is None:
            return GameSearchPage(
                items=(
                    item(1, source_name=r"C:\\Users\\Oleksii\\private\\one.pgn"),
                    item(2, source_name="two.pgn", white="Іван", black="José"),
                ),
                next_after_game_id=2,
                has_more=True,
            )
        if query.after_game_id == 2:
            return GameSearchPage(items=(item(3, source_name="three.pgn"),), next_after_game_id=None, has_more=False)
        raise AssertionError("unexpected keyset cursor")


class LibraryWebViewProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = FakeSearchService()
        self.calls = []

        def dispatch(action_id, payload):
            self.calls.append((action_id, dict(payload)))
            return {
                "token": "SECRET",
                "fen": "SECRET-FEN",
                "path": r"C:\\private\\database.acsdb",
            }

        self.presenter = LibraryPresenter(self.service, language=UILanguage.EN)
        self.projection = LibraryWebViewProjection(
            self.presenter,
            dispatch,
            language=UILanguage.EN,
        )

    def search(self):
        return self.projection.search(
            {
                "player": "  ІВАН   José  ",
                "event": " Accessible Open ",
                "eco": " C20 ",
                "opening": " King's Pawn ",
                "result": "1-0",
                "source_name": " one.pgn ",
            }
        )

    def test_search_builds_bounded_neutral_query_and_semantic_snapshot(self) -> None:
        event = self.search()
        query = self.service.queries[-1]
        self.assertEqual("ІВАН José", query.player)
        self.assertEqual("Accessible Open", query.event)
        self.assertEqual("C20", query.eco)
        self.assertEqual("King's Pawn", query.opening)
        self.assertEqual("1-0", query.result)
        self.assertEqual("one.pgn", query.source_name)
        self.assertEqual(50, query.limit)

        snapshot = event.payload["snapshot"]
        self.assertEqual("ready", snapshot["status"])
        self.assertEqual(2, len(snapshot["rows"]))
        self.assertEqual("one.pgn", snapshot["rows"][0]["source"])
        self.assertTrue(snapshot["rows"][0]["selected"])
        self.assertEqual(snapshot["rows"][0]["dom_id"], event.payload["focus_target"])
        self.assertNotIn("SECRET-FEN", repr(snapshot))
        self.assertNotIn("Users", repr(snapshot))
        self.assertNotEqual("library-game-1", snapshot["rows"][0]["dom_id"])

    def test_filter_bounds_and_result_enum_fail_before_service(self) -> None:
        values = {
            "player": "x" * 257,
            "event": "",
            "eco": "",
            "opening": "",
            "result": "",
            "source_name": "",
        }
        with self.assertRaises(ValueError):
            self.projection.search(values)
        self.assertEqual([], self.service.queries)

        values["player"] = ""
        values["result"] = "2-0"
        with self.assertRaises(ValueError):
            self.projection.search(values)
        self.assertEqual([], self.service.queries)

    def test_selection_and_keyset_paging_keep_exact_focus_identity(self) -> None:
        first = self.search().payload["snapshot"]
        selected = self.projection.move_selection(1)
        second = selected.payload["snapshot"]
        self.assertEqual(2, second["selected_game_id"])
        self.assertNotEqual(first["focus_target"], selected.payload["focus_target"])

        page2 = self.projection.next_page()
        self.assertEqual(3, page2.payload["snapshot"]["selected_game_id"])
        self.assertFalse(page2.payload["snapshot"]["paging"]["has_next"])
        self.assertTrue(page2.payload["snapshot"]["paging"]["has_previous"])

        # Canonical LibraryPresenter intentionally stabilizes a cached page to its
        # first row when the current selection belongs to another page. The WebView
        # must preserve that exact presenter contract rather than invent page-local
        # selection memory in a second UI model.
        page1 = self.projection.previous_page()
        self.assertEqual(1, page1.payload["snapshot"]["selected_game_id"])
        self.assertEqual(page1.payload["snapshot"]["rows"][0]["dom_id"], page1.payload["focus_target"])
        self.assertTrue(page1.payload["snapshot"]["paging"]["has_next"])

    def test_backend_return_payload_is_discarded_for_open_import_and_export(self) -> None:
        self.search()
        opened = self.projection.open_selected()
        imported = self.projection.external_action("library.import")
        exported = self.projection.external_action("library.export")
        joined = repr((opened, imported, exported))
        self.assertNotIn("SECRET", joined)
        self.assertNotIn("database.acsdb", joined)
        self.assertEqual("library.open_game", self.calls[0][0])
        self.assertEqual({"game_id": 1, "source_id": 7, "source_index": 0}, self.calls[0][1])
        self.assertEqual(("library.import", {}), self.calls[1])
        self.assertEqual(("library.export", {}), self.calls[2])

    def test_language_switch_changes_labels_not_result_identity(self) -> None:
        event = self.search()
        en = event.payload["snapshot"]
        ua = self.projection.set_language(UILanguage.UA).payload["snapshot"]
        self.assertEqual(
            [row["game_id"] for row in en["rows"]],
            [row["game_id"] for row in ua["rows"]],
        )
        self.assertEqual(
            [row["dom_id"] for row in en["rows"]],
            [row["dom_id"] for row in ua["rows"]],
        )
        self.assertNotEqual(en["heading"], ua["heading"])

    def test_reset_is_explicit_and_returns_focus_to_search_input(self) -> None:
        self.search()
        reset = self.projection.reset()
        self.assertEqual("library-search-player", reset.payload["focus_target"])
        self.assertTrue(all(not spec["value"] for key, spec in reset.payload["snapshot"]["filters"].items() if isinstance(spec, dict) and "value" in spec))


if __name__ == "__main__":
    unittest.main()
