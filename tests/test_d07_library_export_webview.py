from __future__ import annotations

from pathlib import Path
import unittest

from acs.full_product_presenters import LibraryPresenter
from acs.full_product_ui_shell import UILanguage
from acs.library_export_webview_projection import LibraryExportWebViewProjection
from acs.library_webview_bridge import LibraryWebViewBridge
from acs.search_service import GameSearchItem, GameSearchPage, GameSearchQuery


def _item(game_id: int, white: str, *, event: str = "Event") -> GameSearchItem:
    return GameSearchItem(
        game_id=game_id,
        source_id=7,
        source_name=r"C:\private\hidden.pgn",
        source_format="PGN",
        source_index=game_id - 1,
        import_status="full",
        white=white,
        black="Black",
        event=event,
        site="Site",
        game_date="2026.08.31",
        round=str(game_id),
        result="*",
        eco="A00",
        opening="Opening",
        start_fen=None,
    )


class _Search:
    def __init__(self) -> None:
        self.calls: list[GameSearchQuery] = []

    def search(self, query: GameSearchQuery) -> GameSearchPage:
        q = query.normalized()
        self.calls.append(q)
        if q.after_game_id == 2:
            return GameSearchPage(items=(_item(3, "Three"),), next_after_game_id=None, has_more=False)
        return GameSearchPage(
            items=(_item(1, "One"), _item(2, "Two")),
            next_after_game_id=2,
            has_more=True,
        )


class LibraryExportWebViewTests(unittest.TestCase):
    def build(self):
        service = _Search()
        calls: list[tuple[str, dict[str, object]]] = []

        def dispatch(action_id, payload):
            calls.append((action_id, dict(payload)))
            return {"private_backend": r"C:\private\never-project-this"}

        presenter = LibraryPresenter(service, language=UILanguage.EN)
        projection = LibraryExportWebViewProjection(
            presenter,
            dispatch,
            language=UILanguage.EN,
        )
        bridge = LibraryWebViewBridge(projection)
        bridge.dispatch("library.search", {"event": "Event", "limit": 2})
        return service, presenter, projection, bridge, calls

    def test_export_checkboxes_are_distinct_from_current_open_selection(self) -> None:
        _service, _presenter, projection, bridge, _calls = self.build()
        initial = projection.snapshot()
        self.assertEqual(initial["selected_game_id"], 1)
        self.assertFalse(initial["rows"][1]["export_selected"])

        event = bridge.dispatch("library.toggle_export_selection", {"game_id": 2})
        snapshot = event.payload["snapshot"]
        self.assertEqual(snapshot["selected_game_id"], 1)
        self.assertTrue(snapshot["rows"][1]["export_selected"])
        self.assertEqual(projection.export_game_ids, (2,))
        self.assertEqual(event.payload["focus_target"], snapshot["rows"][1]["export_dom_id"])
        self.assertNotIn("private", repr(snapshot["rows"][1]["source_label"]).casefold())

    def test_multiple_selection_survives_page_navigation_and_exports_sorted_ids(self) -> None:
        _service, _presenter, projection, bridge, calls = self.build()
        bridge.dispatch("library.toggle_export_selection", {"game_id": 2})
        bridge.dispatch("library.toggle_export_selection", {"game_id": 1})
        page = bridge.dispatch("library.next_page", {})
        self.assertEqual(page.payload["snapshot"]["selected_game_id"], 3)
        bridge.dispatch("library.toggle_export_selection", {"game_id": 3})

        event = bridge.dispatch("library.export_selected", {})
        self.assertEqual(event.kind, "delegated")
        action_id, payload = calls[-1]
        self.assertEqual(action_id, "library.export")
        self.assertEqual(payload, {"scope": "selected", "game_ids": (1, 2, 3)})
        self.assertNotIn("path", repr(payload).casefold())
        self.assertNotIn("destination", repr(payload).casefold())

    def test_filtered_export_sends_current_filter_identity_without_page_authority(self) -> None:
        _service, _presenter, _projection, bridge, calls = self.build()
        event = bridge.dispatch("library.export_filtered", {})
        self.assertEqual(event.kind, "delegated")
        action_id, payload = calls[-1]
        self.assertEqual(action_id, "library.export")
        self.assertEqual(payload["scope"], "filtered")
        self.assertEqual(payload["filters"]["event"], "Event")
        self.assertNotIn("limit", payload["filters"])
        self.assertNotIn("after_game_id", payload["filters"])
        self.assertNotIn("path", repr(payload).casefold())

    def test_new_search_clears_export_selection_but_failed_browser_commands_do_not(self) -> None:
        _service, _presenter, projection, bridge, _calls = self.build()
        bridge.dispatch("library.toggle_export_selection", {"game_id": 1})
        self.assertEqual(projection.export_game_ids, (1,))
        rejected = bridge.dispatch("library.toggle_export_selection", {"game_id": 999})
        self.assertEqual(rejected.kind, "error")
        self.assertEqual(projection.export_game_ids, (1,))
        bridge.dispatch("library.search", {"event": "Different", "limit": 2})
        self.assertEqual(projection.export_game_ids, ())

    def test_empty_multi_selection_cannot_dispatch_export(self) -> None:
        _service, _presenter, _projection, bridge, calls = self.build()
        before = list(calls)
        event = bridge.dispatch("library.export_selected", {})
        self.assertEqual(event.kind, "error")
        self.assertEqual(calls, before)

    def test_clear_selection_is_explicit_and_accessibly_announced(self) -> None:
        _service, _presenter, projection, bridge, _calls = self.build()
        bridge.dispatch("library.toggle_export_selection", {"game_id": 1})
        cleared = bridge.dispatch("library.clear_export_selection", {})
        self.assertEqual(projection.export_game_ids, ())
        self.assertIn("cleared", str(cleared.payload["announcement"]).casefold())
        actions = {
            action["action"]: action
            for action in cleared.payload["snapshot"]["actions"]
        }
        self.assertFalse(actions["library.export_selected"]["enabled"])
        self.assertTrue(actions["library.export_filtered"]["enabled"])


class LibraryExportWebAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (Path(__file__).parents[1] / "web" / "full_product_library.js").read_text(
            encoding="utf-8"
        )

    def test_export_selection_uses_native_checkbox_fieldset_without_live_region(self) -> None:
        self.assertIn('node("fieldset")', self.source)
        self.assertIn('node("legend"', self.source)
        self.assertIn('checkbox.type = "checkbox"', self.source)
        self.assertIn('"library.toggle_export_selection"', self.source)
        self.assertNotIn('aria-live", "polite"', self.source)

    def test_export_controls_do_not_capture_global_keyboard_or_accept_paths(self) -> None:
        self.assertNotIn('document.addEventListener("keydown"', self.source)
        self.assertNotIn('window.addEventListener("keydown"', self.source)
        self.assertNotIn('input.type = "file"', self.source)
        self.assertNotIn('payload.path', self.source)
        self.assertNotIn('payload.destination', self.source)


if __name__ == "__main__":
    unittest.main()
