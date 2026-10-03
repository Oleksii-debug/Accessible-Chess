from __future__ import annotations

import unittest

from acs.full_product_presenters import LibraryPresenter
from acs.full_product_ui_shell import UILanguage
from acs.library_webview_projection import LibraryWebViewProjection
from acs.search_service import GameSearchItem, GameSearchPage, GameSearchQuery


def _item(game_id: int, result: str | None) -> GameSearchItem:
    return GameSearchItem(
        game_id=game_id,
        source_id=1,
        source_name="library.pgn",
        source_format="pgn",
        source_index=game_id - 1,
        import_status="ok",
        white="White",
        black="Black",
        event="Result canonicality",
        site=None,
        game_date=None,
        round=None,
        result=result,
        eco=None,
        opening=None,
        start_fen=None,
    )


class _Service:
    def __init__(self) -> None:
        self.result: str | None = "1-0"

    def search(self, query: GameSearchQuery) -> GameSearchPage:
        query = query.normalized()
        if query.after_game_id is None and query.player != "Replacement":
            return GameSearchPage(
                items=(_item(10, "1-0"),),
                next_after_game_id=10,
                has_more=True,
            )
        return GameSearchPage(
            items=(_item(11, self.result),),
            next_after_game_id=None,
            has_more=False,
        )


class LibraryResultMetadataCanonicalityTests(unittest.TestCase):
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

    def test_noncanonical_successor_result_is_transient_error_without_commit(self) -> None:
        invalid_results = (
            "",
            "2-0",
            "1 - 0",
            "1/2 - 1/2",
            "draw",
            "0:1",
        )
        for value in invalid_results:
            with self.subTest(result=value):
                service, projection = self._build()
                before = projection.snapshot()
                query_before = projection.query
                service.result = value

                event = projection.next_page()

                self.assertEqual("error", event.payload["snapshot"]["status"])
                self.assertEqual(before, projection.snapshot())
                self.assertEqual(query_before, projection.query)

    def test_noncanonical_replacement_result_preserves_committed_search(self) -> None:
        for value in ("", "2-0", "1 - 0", "draw"):
            with self.subTest(result=value):
                service, projection = self._build()
                before = projection.snapshot()
                query_before = projection.query
                service.result = value

                event = projection.search(
                    GameSearchQuery(player="Replacement", limit=25)
                )

                self.assertEqual("error", event.payload["snapshot"]["status"])
                self.assertEqual(before, projection.snapshot())
                self.assertEqual(query_before, projection.query)

    def test_all_canonical_result_tokens_and_missing_result_remain_supported(self) -> None:
        for value in ("1-0", "0-1", "1/2-1/2", "*", None):
            with self.subTest(result=value):
                service, projection = self._build()
                service.result = value

                event = projection.next_page()

                snapshot = event.payload["snapshot"]
                self.assertEqual("ready", snapshot["status"])
                self.assertEqual(11, snapshot["selected_game_id"])
                expected = value or "*"
                self.assertEqual(expected, snapshot["rows"][0]["result"])


if __name__ == "__main__":
    unittest.main()
