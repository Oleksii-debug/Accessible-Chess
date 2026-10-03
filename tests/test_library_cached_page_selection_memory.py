from __future__ import annotations

import unittest
from unittest.mock import patch

from acs.full_product_presenters import LibraryPresenter
from acs.full_product_ui_shell import UILanguage
from acs.library_webview_projection import LibraryWebViewProjection
from acs.search_service import GameSearchItem, GameSearchPage, GameSearchQuery


def _item(game_id: int) -> GameSearchItem:
    return GameSearchItem(
        game_id=game_id,
        source_id=1,
        source_name="library.pgn",
        source_format="pgn",
        source_index=game_id - 1,
        import_status="ok",
        white=f"White {game_id}",
        black=f"Black {game_id}",
        event="Cached selection memory",
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
        if query.after_game_id is None:
            return GameSearchPage(
                items=(_item(1), _item(2)),
                next_after_game_id=2,
                has_more=True,
            )
        if query.after_game_id == 2:
            return GameSearchPage(
                items=(_item(3), _item(4)),
                next_after_game_id=None,
                has_more=False,
            )
        raise AssertionError("unexpected cursor")


class LibraryCachedPageSelectionMemoryTests(unittest.TestCase):
    def _build(self):
        service = _Service()
        presenter = LibraryPresenter(service, language=UILanguage.EN)
        projection = LibraryWebViewProjection(
            presenter,
            lambda _action, _payload: None,
            language=UILanguage.EN,
        )
        projection.search(GameSearchQuery(player="Stable", limit=25))
        return service, projection

    def test_cached_back_forward_restores_each_pages_exact_keyboard_selection(self) -> None:
        service, projection = self._build()
        projection.select(2)
        projection.next_page()
        projection.select(4)

        previous = projection.previous_page()
        self.assertEqual(2, previous.payload["snapshot"]["selected_game_id"])
        calls_after_fetch = len(service.calls)

        cached_forward = projection.next_page()
        snapshot = cached_forward.payload["snapshot"]

        self.assertEqual(calls_after_fetch, len(service.calls))
        self.assertEqual(4, snapshot["selected_game_id"])
        selected = [row for row in snapshot["rows"] if row["selected"]]
        self.assertEqual([4], [row["game_id"] for row in selected])
        self.assertEqual(selected[0]["dom_id"], snapshot["focus_target"])

    def test_failed_cached_forward_render_rolls_back_page_and_selection_memory(self) -> None:
        service, projection = self._build()
        projection.select(2)
        projection.next_page()
        projection.select(4)
        projection.previous_page()
        before = projection.snapshot()
        calls_before = len(service.calls)

        with patch.object(
            projection.import_projection,
            "snapshot",
            side_effect=RuntimeError("snapshot publication failed"),
        ):
            with self.assertRaises(RuntimeError):
                projection.next_page()

        self.assertEqual(calls_before, len(service.calls))
        self.assertEqual(before, projection.snapshot())
        self.assertEqual(2, projection.snapshot()["selected_game_id"])

        retry = projection.next_page()
        self.assertEqual(calls_before, len(service.calls))
        self.assertEqual(4, retry.payload["snapshot"]["selected_game_id"])

    def test_each_cached_page_keeps_its_latest_selection_independently(self) -> None:
        service, projection = self._build()
        projection.select(2)
        projection.next_page()
        projection.select(4)

        projection.previous_page()
        projection.select(1)
        projection.next_page()
        self.assertEqual(4, projection.snapshot()["selected_game_id"])

        projection.previous_page()
        self.assertEqual(1, projection.snapshot()["selected_game_id"])
        self.assertEqual(2, len(service.calls))


if __name__ == "__main__":
    unittest.main()
