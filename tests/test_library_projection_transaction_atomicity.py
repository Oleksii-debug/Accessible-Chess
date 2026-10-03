from __future__ import annotations

import unittest
from unittest.mock import patch

from acs.full_product_presenters import LibraryPresenter
from acs.full_product_ui_shell import UILanguage
from acs.library_export_webview_projection import LibraryExportWebViewProjection
from acs.library_webview_projection import LibraryWebViewProjection
from acs.search_service import GameSearchItem, GameSearchPage, GameSearchQuery


def _item(game_id: int, white: str, black: str) -> GameSearchItem:
    return GameSearchItem(
        game_id=game_id,
        source_id=1,
        source_name="library.pgn",
        source_format="pgn",
        source_index=game_id - 1,
        import_status="ok",
        white=white,
        black=black,
        event="Projection transaction",
        site=None,
        game_date=None,
        round=None,
        result="1-0",
        eco=None,
        opening=None,
        start_fen=None,
    )


class _Service:
    def __init__(self) -> None:
        self.calls: list[GameSearchQuery] = []

    def search(self, query: GameSearchQuery) -> GameSearchPage:
        query = query.normalized()
        self.calls.append(query)
        if query.player == "Second":
            return GameSearchPage(
                items=(_item(10, "Second", "Result"),),
                next_after_game_id=None,
                has_more=False,
            )
        if query.after_game_id is None:
            return GameSearchPage(
                items=(
                    _item(1, "Alpha", "Beta"),
                    _item(2, "Gamma", "Delta"),
                ),
                next_after_game_id=2,
                has_more=True,
            )
        if query.after_game_id == 2:
            return GameSearchPage(
                items=(_item(3, "Epsilon", "Zeta"),),
                next_after_game_id=None,
                has_more=False,
            )
        raise AssertionError("unexpected Library cursor")


class LibraryProjectionTransactionAtomicityTests(unittest.TestCase):
    def _build(self, *, export: bool = False):
        service = _Service()
        presenter = LibraryPresenter(service, language=UILanguage.EN)
        projection_type = (
            LibraryExportWebViewProjection if export else LibraryWebViewProjection
        )
        projection = projection_type(
            presenter,
            lambda _action, _payload: None,
            language=UILanguage.EN,
        )
        return service, presenter, projection

    def test_search_render_failure_rolls_back_presenter_and_query(self) -> None:
        _service, _presenter, projection = self._build()
        projection.search(GameSearchQuery(player="Alpha", limit=25))
        before = projection.snapshot()
        query_before = projection.query

        with patch.object(
            projection.import_projection,
            "snapshot",
            side_effect=RuntimeError("snapshot publication failed"),
        ):
            with self.assertRaises(RuntimeError):
                projection.search(GameSearchQuery(player="Second", limit=25))

        self.assertEqual(query_before, projection.query)
        self.assertEqual(before, projection.snapshot())

        retry = projection.search(GameSearchQuery(player="Second", limit=25))
        self.assertEqual(10, retry.payload["snapshot"]["selected_game_id"])

    def test_next_page_render_failure_rolls_back_cache_page_and_selection(self) -> None:
        service, _presenter, projection = self._build()
        projection.search(GameSearchQuery(player="Alpha", limit=25))
        before = projection.snapshot()
        calls_before = len(service.calls)

        with patch.object(
            projection.import_projection,
            "snapshot",
            side_effect=RuntimeError("snapshot publication failed"),
        ):
            with self.assertRaises(RuntimeError):
                projection.next_page()

        self.assertEqual(before, projection.snapshot())
        self.assertEqual(calls_before + 1, len(service.calls))

        retry = projection.next_page()
        self.assertEqual(3, retry.payload["snapshot"]["selected_game_id"])
        self.assertEqual(calls_before + 2, len(service.calls))

    def test_previous_page_render_failure_restores_current_page(self) -> None:
        _service, _presenter, projection = self._build()
        projection.search(GameSearchQuery(player="Alpha", limit=25))
        projection.next_page()
        before = projection.snapshot()

        with patch.object(
            projection.import_projection,
            "snapshot",
            side_effect=RuntimeError("snapshot publication failed"),
        ):
            with self.assertRaises(RuntimeError):
                projection.previous_page()

        self.assertEqual(before, projection.snapshot())
        previous = projection.previous_page()
        self.assertEqual(1, previous.payload["snapshot"]["selected_game_id"])

    def test_selection_render_failure_restores_exact_selected_game(self) -> None:
        _service, _presenter, projection = self._build()
        projection.search(GameSearchQuery(player="Alpha", limit=25))
        before = projection.snapshot()

        with patch.object(
            projection.import_projection,
            "snapshot",
            side_effect=RuntimeError("snapshot publication failed"),
        ):
            with self.assertRaises(RuntimeError):
                projection.select(2)

        self.assertEqual(before, projection.snapshot())
        self.assertEqual(1, projection.snapshot()["selected_game_id"])

    def test_keyboard_move_render_failure_restores_exact_selected_game(self) -> None:
        _service, _presenter, projection = self._build()
        projection.search(GameSearchQuery(player="Alpha", limit=25))
        before = projection.snapshot()

        with patch.object(
            projection.import_projection,
            "snapshot",
            side_effect=RuntimeError("snapshot publication failed"),
        ):
            with self.assertRaises(RuntimeError):
                projection.move_selection(1)

        self.assertEqual(before, projection.snapshot())
        self.assertEqual(1, projection.snapshot()["selected_game_id"])

    def test_export_search_render_failure_restores_query_page_and_checks(self) -> None:
        _service, _presenter, projection = self._build(export=True)
        projection.search(GameSearchQuery(player="Alpha", limit=25))
        projection.toggle_export_selection(1)
        before = projection.snapshot()
        query_before = projection.query
        export_before = projection.export_game_ids

        with patch.object(
            projection.import_projection,
            "snapshot",
            side_effect=RuntimeError("snapshot publication failed"),
        ):
            with self.assertRaises(RuntimeError):
                projection.search(GameSearchQuery(player="Second", limit=25))

        self.assertEqual(query_before, projection.query)
        self.assertEqual(export_before, projection.export_game_ids)
        self.assertEqual(before, projection.snapshot())

    def test_export_toggle_focus_failure_restores_checkbox_state(self) -> None:
        _service, _presenter, projection = self._build(export=True)
        projection.search(GameSearchQuery(player="Alpha", limit=25))
        projection.toggle_export_selection(1)
        export_before = projection.export_game_ids

        with patch.object(
            projection,
            "_export_focus_target",
            side_effect=RuntimeError("focus target failed"),
        ):
            with self.assertRaises(RuntimeError):
                projection.toggle_export_selection(2)

        self.assertEqual(export_before, projection.export_game_ids)
        snapshot = projection.snapshot()
        selected = {
            row["game_id"]
            for row in snapshot["rows"]
            if row["export_selected"]
        }
        self.assertEqual({1}, selected)

    def test_export_clear_render_failure_restores_checkbox_state(self) -> None:
        _service, _presenter, projection = self._build(export=True)
        projection.search(GameSearchQuery(player="Alpha", limit=25))
        projection.toggle_export_selection(1)
        projection.toggle_export_selection(2)
        export_before = projection.export_game_ids

        with patch.object(
            projection,
            "_render_event",
            side_effect=RuntimeError("snapshot publication failed"),
        ):
            with self.assertRaises(RuntimeError):
                projection.clear_export_selection()

        self.assertEqual(export_before, projection.export_game_ids)


if __name__ == "__main__":
    unittest.main()
