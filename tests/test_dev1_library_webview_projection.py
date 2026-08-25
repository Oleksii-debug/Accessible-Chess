from __future__ import annotations

from pathlib import Path
import unittest

from acs.full_product_presenters import LibraryPresenter, SurfaceStatus
from acs.full_product_ui_shell import UILanguage
from acs.library_webview_bridge import LibraryWebViewBridge
from acs.library_webview_projection import LibraryWebViewProjection
from acs.search_service import GameSearchItem, GameSearchPage, GameSearchQuery


def item(
    game_id: int,
    *,
    source_id: int = 10,
    source_name: str = r"C:\private\library.pgn",
    source_index: int = 0,
    white: str = "Alpha",
    black: str = "Beta",
    event: str | None = "Event",
    result: str = "1-0",
    eco: str | None = "C20",
    opening: str | None = "King Pawn",
) -> GameSearchItem:
    return GameSearchItem(
        game_id=game_id,
        source_id=source_id,
        source_name=source_name,
        source_format="PGN",
        source_index=source_index,
        import_status="full",
        white=white,
        black=black,
        event=event,
        site=None,
        game_date="2026.08.22",
        round="1",
        result=result,
        eco=eco,
        opening=opening,
        start_fen=None,
    )


class FakeSearchService:
    def __init__(self) -> None:
        self.calls: list[GameSearchQuery] = []
        self.pages = {
            None: GameSearchPage(
                items=(
                    item(1, source_index=0, white="Олексій", black="Beta"),
                    item(2, source_index=1, white="Gamma", black="Delta", result="0-1"),
                ),
                next_after_game_id=2,
                has_more=True,
            ),
            2: GameSearchPage(
                items=(
                    item(
                        3,
                        source_id=11,
                        source_name="/home/private/second.pgn",
                        white="Epsilon",
                        black="Zeta",
                        result="1/2-1/2",
                    ),
                ),
                next_after_game_id=None,
                has_more=False,
            ),
        }

    def search(self, query: GameSearchQuery) -> GameSearchPage:
        normalized = query.normalized()
        self.calls.append(normalized)
        return self.pages[normalized.after_game_id]


class FailingSearchService:
    def search(self, query: GameSearchQuery) -> GameSearchPage:
        raise RuntimeError(r"sqlite OperationalError at C:\private\library.db query SELECT secret")


class LibraryWebViewProjectionTests(unittest.TestCase):
    def build(self, service=None, *, language=UILanguage.EN):
        service = service or FakeSearchService()
        calls = []

        def dispatch(action_id, payload):
            calls.append((action_id, dict(payload)))
            return {"internal": "backend value must not reach browser"}

        presenter = LibraryPresenter(service, language=language)
        projection = LibraryWebViewProjection(presenter, dispatch, language=language)
        bridge = LibraryWebViewBridge(projection)
        return service, presenter, projection, bridge, calls

    def test_search_projects_semantic_rows_and_explicit_focus_from_one_view(self) -> None:
        _service, _presenter, projection, _bridge, _calls = self.build()
        event = projection.search(GameSearchQuery(player="  Олексій  ", limit=2))
        snapshot = event.payload["snapshot"]
        self.assertEqual("render", event.kind)
        self.assertEqual("ready", snapshot["status"])
        self.assertEqual(2, len(snapshot["rows"]))
        self.assertEqual(1, snapshot["selected_game_id"])
        selected = [row for row in snapshot["rows"] if row["selected"]]
        self.assertEqual(1, len(selected))
        self.assertEqual(selected[0]["dom_id"], snapshot["focus_target"])
        self.assertEqual("library.pgn", selected[0]["source_label"])
        self.assertNotIn("private", selected[0]["source_label"].casefold())

    def test_filter_projection_never_exposes_keyset_cursor(self) -> None:
        _service, _presenter, projection, _bridge, _calls = self.build()
        projection.search(
            GameSearchQuery(
                player="Alpha",
                event="Event",
                eco="C2",
                opening="King",
                result="1-0",
                source_id=10,
                source_name="library",
                limit=25,
            )
        )
        snapshot = projection.snapshot()
        ids = {field["id"] for field in snapshot["filters"]}
        self.assertEqual(
            {"player", "event", "eco", "opening", "result", "source_id", "source_name", "limit"},
            ids,
        )
        self.assertNotIn("after_game_id", repr(snapshot))

    def test_keyset_paging_is_owned_by_presenter_not_browser_payload(self) -> None:
        service, _presenter, projection, bridge, _calls = self.build()
        bridge.dispatch("library.search", {"player": "Alpha", "limit": "2"})
        event = bridge.dispatch("library.next_page", {})
        snapshot = event.payload["snapshot"]
        self.assertEqual(3, snapshot["selected_game_id"])
        self.assertEqual("second.pgn", snapshot["rows"][0]["source_label"])
        self.assertEqual([None, 2], [call.after_game_id for call in service.calls])
        self.assertNotIn("after_game_id", repr(snapshot))

    def test_keyboard_selection_moves_only_inside_current_rendered_page(self) -> None:
        _service, _presenter, projection, bridge, _calls = self.build()
        projection.search(GameSearchQuery(limit=2))
        moved = bridge.dispatch("library.move", {"delta": 1})
        snapshot = moved.payload["snapshot"]
        self.assertEqual(2, snapshot["selected_game_id"])
        self.assertEqual(2, [row for row in snapshot["rows"] if row["selected"]][0]["game_id"])
        boundary = bridge.dispatch("library.move", {"delta": 1})
        self.assertEqual("error", boundary.kind)

    def test_open_selected_delegates_only_neutral_identifiers_and_hides_return_value(self) -> None:
        _service, _presenter, projection, bridge, calls = self.build()
        projection.search(GameSearchQuery(limit=2))
        bridge.dispatch("library.select", {"game_id": 2})
        event = bridge.dispatch("library.open_game", {})
        self.assertEqual("delegated", event.kind)
        self.assertEqual({"action": "library.open_game"}, dict(event.payload))
        self.assertEqual(
            [("library.open_game", {"game_id": 2, "source_id": 10, "source_index": 1})],
            calls,
        )
        self.assertNotIn("backend value", repr(event.payload))

    def test_search_error_is_concise_and_does_not_leak_database_or_path_details(self) -> None:
        _service, _presenter, projection, _bridge, _calls = self.build(FailingSearchService())
        event = projection.search(GameSearchQuery(player="secret"))
        snapshot = event.payload["snapshot"]
        self.assertEqual(SurfaceStatus.ERROR.value, snapshot["status"])
        text = (snapshot["message"] + " " + snapshot["summary"]).casefold()
        self.assertNotIn("sqlite", text)
        self.assertNotIn("select", text)
        self.assertNotIn("c:\\", text)
        self.assertNotIn("private", text)

    def test_bridge_rejects_cursor_and_unknown_fields_without_reflecting_values(self) -> None:
        _service, _presenter, _projection, bridge, _calls = self.build()
        for payload in (
            {"after_game_id": 999},
            {"player": "TOP-SECRET", "sql": "SELECT * FROM games"},
            {"source_id": "999999999999999999999999999"},
            {"limit": 0},
        ):
            event = bridge.dispatch("library.search", payload)
            self.assertEqual("error", event.kind)
            visible = repr(event.payload).casefold()
            self.assertNotIn("top-secret", visible)
            self.assertNotIn("select *", visible)
            self.assertNotIn("999999", visible)

    def test_language_switch_changes_labels_but_preserves_row_and_focus_identity(self) -> None:
        _service, _presenter, projection, _bridge, _calls = self.build(language=UILanguage.UA)
        ua = projection.search(GameSearchQuery(limit=2)).payload["snapshot"]
        en = projection.set_language(UILanguage.EN).payload["snapshot"]
        self.assertNotEqual(ua["heading"], en["heading"])
        self.assertEqual(
            [row["dom_id"] for row in ua["rows"]],
            [row["dom_id"] for row in en["rows"]],
        )
        self.assertEqual(ua["focus_target"], en["focus_target"])

    def test_snapshot_does_not_mix_live_selection_changed_after_immutable_view_capture(self) -> None:
        service = FakeSearchService()

        class MutatingAfterReadPresenter(LibraryPresenter):
            def __init__(self, backend):
                super().__init__(backend, language=UILanguage.EN)
                self.view_calls = 0
                self.live_selection_after_read = None

            def view(self):
                self.view_calls += 1
                view = super().view()
                if self.view_calls == 1 and len(view.rows) > 1:
                    self._selected_game_id = view.rows[1].game_id
                    self.live_selection_after_read = self._selected_game_id
                return view

        presenter = MutatingAfterReadPresenter(service)
        projection = LibraryWebViewProjection(presenter, lambda _action, _payload: None, language=UILanguage.EN)
        # Seed pages through the base implementation so the adversarial read only
        # applies to the final browser snapshot under test.
        LibraryPresenter.search(presenter, GameSearchQuery(limit=2))
        presenter.view_calls = 0
        presenter._selected_game_id = 1
        snapshot = projection.snapshot()
        self.assertEqual(1, presenter.view_calls)
        self.assertEqual(2, presenter.live_selection_after_read)
        self.assertEqual(1, snapshot["selected_game_id"])
        self.assertEqual(1, [row for row in snapshot["rows"] if row["selected"]][0]["game_id"])


class LibraryWebAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (Path(__file__).parents[1] / "web" / "full_product_library.js").read_text(
            encoding="utf-8"
        )

    def test_renderer_uses_semantic_form_listbox_options_and_native_controls(self) -> None:
        source = self.source
        self.assertIn('node("form")', source)
        self.assertIn('node("input")', source)
        self.assertIn('node("select")', source)
        self.assertIn('node("button"', source)
        self.assertIn('setAttribute("role", "listbox")', source)
        self.assertIn('setAttribute("role", "option")', source)
        self.assertIn('setAttribute("aria-selected"', source)

    def test_renderer_never_uses_markup_injection(self) -> None:
        source = self.source
        self.assertIn("textContent", source)
        for token in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            self.assertNotIn(token, source)

    def test_keyboard_handler_is_scoped_to_result_options(self) -> None:
        source = self.source
        self.assertIn('option.addEventListener("keydown"', source)
        self.assertNotIn('document.addEventListener("keydown"', source)
        self.assertNotIn('window.addEventListener("keydown"', source)
        self.assertIn('event.key === "ArrowUp"', source)
        self.assertIn('event.key === "ArrowDown"', source)
        self.assertIn('event.key === "Enter"', source)

    def test_renderer_does_not_create_background_live_region_spam(self) -> None:
        source = self.source
        self.assertIn('setAttribute("aria-live", "off")', source)
        self.assertNotIn('aria-live", "polite"', source)
        self.assertNotIn('setAttribute("role", "status")', source)

    def test_transport_rejection_is_handled_without_backend_text(self) -> None:
        source = self.source
        self.assertIn('.catch(function ()', source)
        self.assertIn("transport_error_message", source)
        self.assertNotIn("error.message", source)
        self.assertNotIn("reason.message", source)

    def test_focus_moves_only_to_explicit_requested_target(self) -> None:
        source = self.source
        self.assertIn("function focusRequestedOption(root, focusTarget)", source)
        self.assertIn('focusRequestedOption(root, requestedFocus || "")', source)
        self.assertNotIn('[role="option"][aria-selected="true"]', source)


if __name__ == "__main__":
    unittest.main()


