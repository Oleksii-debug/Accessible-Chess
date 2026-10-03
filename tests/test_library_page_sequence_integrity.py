from __future__ import annotations

import unittest

from acs.full_product_presenters import LibraryPresenter
from acs.full_product_ui_shell import UILanguage
from acs.library_webview_projection import LibraryWebViewProjection
from acs.search_service import GameSearchItem, GameSearchPage, GameSearchQuery


def _item(
    game_id: int,
    *,
    source_id: int = 1,
    source_index: int | None = None,
    source_name: object = "library.pgn",
    white: object = "White",
) -> GameSearchItem:
    return GameSearchItem(
        game_id=game_id,
        source_id=source_id,
        source_name=source_name,  # type: ignore[arg-type]
        source_format="pgn",
        source_index=game_id - 1 if source_index is None else source_index,
        import_status="ok",
        white=white,  # type: ignore[arg-type]
        black="Black",
        event="Sequence integrity",
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
        self.next_mode = "valid"
        self.replacement_mode = "valid"

    def _malformed(self, mode: str) -> GameSearchPage:
        if mode == "replay":
            return GameSearchPage(
                items=(_item(20),),
                next_after_game_id=None,
                has_more=False,
            )
        if mode == "out_of_order":
            return GameSearchPage(
                items=(_item(22), _item(21)),
                next_after_game_id=None,
                has_more=False,
            )
        if mode == "invalid_source_id":
            return GameSearchPage(
                items=(_item(21, source_id=0),),
                next_after_game_id=None,
                has_more=False,
            )
        if mode == "invalid_source_index":
            return GameSearchPage(
                items=(_item(21, source_index=-1),),
                next_after_game_id=None,
                has_more=False,
            )
        if mode == "invalid_source_metadata":
            return GameSearchPage(
                items=(_item(21, source_name=object()),),
                next_after_game_id=None,
                has_more=False,
            )
        if mode == "invalid_game_metadata":
            return GameSearchPage(
                items=(_item(21, white=object()),),
                next_after_game_id=None,
                has_more=False,
            )
        if mode == "mutable_items":
            return GameSearchPage(  # type: ignore[arg-type]
                items=[_item(21)],
                next_after_game_id=None,
                has_more=False,
            )
        if mode == "duplicate":
            return GameSearchPage(
                items=(_item(21), _item(21)),
                next_after_game_id=None,
                has_more=False,
            )
        raise AssertionError("unexpected malformed-page mode")

    def search(self, query: GameSearchQuery) -> GameSearchPage:
        query = query.normalized()
        if query.player == "Broken":
            if self.replacement_mode == "valid":
                return GameSearchPage(
                    items=(_item(30),),
                    next_after_game_id=None,
                    has_more=False,
                )
            return self._malformed(self.replacement_mode)
        if query.after_game_id is None:
            return GameSearchPage(
                items=(_item(10), _item(20)),
                next_after_game_id=20,
                has_more=True,
            )
        if query.after_game_id != 20:
            raise AssertionError("unexpected keyset cursor")
        if self.next_mode != "valid":
            return self._malformed(self.next_mode)
        return GameSearchPage(
            items=(_item(21), _item(22)),
            next_after_game_id=None,
            has_more=False,
        )


class LibraryPageSequenceIntegrityTests(unittest.TestCase):
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

    def test_malformed_next_pages_are_rejected_without_cache_or_selection_commit(self) -> None:
        modes = (
            "replay",
            "out_of_order",
            "invalid_source_id",
            "invalid_source_index",
            "invalid_source_metadata",
            "invalid_game_metadata",
            "mutable_items",
            "duplicate",
        )
        for mode in modes:
            with self.subTest(mode=mode):
                service, projection = self._build()
                before = projection.snapshot()
                query_before = projection.query
                service.next_mode = mode

                failed = projection.next_page()

                self.assertEqual("error", failed.payload["snapshot"]["status"])
                self.assertEqual(before, projection.snapshot())
                self.assertEqual(query_before, projection.query)

                service.next_mode = "valid"
                retry = projection.next_page()
                self.assertEqual("ready", retry.payload["snapshot"]["status"])
                self.assertEqual(21, retry.payload["snapshot"]["selected_game_id"])

    def test_malformed_replacement_search_preserves_committed_query_and_page(self) -> None:
        for mode in (
            "out_of_order",
            "invalid_source_id",
            "invalid_source_index",
            "invalid_source_metadata",
            "invalid_game_metadata",
            "mutable_items",
            "duplicate",
        ):
            with self.subTest(mode=mode):
                service, projection = self._build()
                before = projection.snapshot()
                query_before = projection.query
                service.replacement_mode = mode

                failed = projection.search(
                    GameSearchQuery(player="Broken", limit=25)
                )

                self.assertEqual("error", failed.payload["snapshot"]["status"])
                self.assertEqual(before, projection.snapshot())
                self.assertEqual(query_before, projection.query)

    def test_valid_strictly_increasing_successor_page_remains_supported(self) -> None:
        _service, projection = self._build()

        event = projection.next_page()

        snapshot = event.payload["snapshot"]
        self.assertEqual("ready", snapshot["status"])
        self.assertEqual([21, 22], [row["game_id"] for row in snapshot["rows"]])
        self.assertEqual(21, snapshot["selected_game_id"])


if __name__ == "__main__":
    unittest.main()
