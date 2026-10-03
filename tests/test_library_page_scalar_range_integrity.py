from __future__ import annotations

import unittest

from acs.full_product_presenters import LibraryPresenter
from acs.full_product_ui_shell import UILanguage
from acs.library_webview_projection import LibraryWebViewProjection
from acs.search_service import GameSearchItem, GameSearchPage, GameSearchQuery


MAX = (1 << 63) - 1


def _item(
    game_id: int,
    *,
    source_id: int = 1,
    source_index: int = 0,
) -> GameSearchItem:
    return GameSearchItem(
        game_id=game_id,
        source_id=source_id,
        source_name="library.pgn",
        source_format="pgn",
        source_index=source_index,
        import_status="ok",
        white="White",
        black="Black",
        event="Scalar range integrity",
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
        self.mode = "valid"

    def _candidate(self) -> GameSearchItem:
        if self.mode == "game_overflow":
            return _item(MAX + 1)
        if self.mode == "source_overflow":
            return _item(11, source_id=MAX + 1)
        if self.mode == "index_overflow":
            return _item(11, source_index=MAX + 1)
        if self.mode == "game_bool":
            return _item(True)  # type: ignore[arg-type]
        if self.mode == "source_bool":
            return _item(11, source_id=True)  # type: ignore[arg-type]
        if self.mode == "index_bool":
            return _item(11, source_index=True)  # type: ignore[arg-type]
        return _item(11, source_id=MAX, source_index=MAX)

    def search(self, query: GameSearchQuery) -> GameSearchPage:
        query = query.normalized()
        if query.after_game_id is None and query.player != "Replacement":
            return GameSearchPage(
                items=(_item(10),),
                next_after_game_id=10,
                has_more=True,
            )
        candidate = self._candidate()
        return GameSearchPage(
            items=(candidate,),
            next_after_game_id=None,
            has_more=False,
        )


class LibraryPageScalarRangeIntegrityTests(unittest.TestCase):
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

    def test_successor_page_rejects_non_sqlite_identifiers_without_commit(self) -> None:
        modes = (
            "game_overflow",
            "source_overflow",
            "index_overflow",
            "game_bool",
            "source_bool",
            "index_bool",
        )
        for mode in modes:
            with self.subTest(mode=mode):
                service, projection = self._build()
                before = projection.snapshot()
                query_before = projection.query
                service.mode = mode

                event = projection.next_page()

                self.assertEqual("error", event.payload["snapshot"]["status"])
                self.assertEqual(before, projection.snapshot())
                self.assertEqual(query_before, projection.query)

    def test_replacement_search_rejects_non_sqlite_identifiers_without_commit(self) -> None:
        for mode in (
            "game_overflow",
            "source_overflow",
            "index_overflow",
            "game_bool",
            "source_bool",
            "index_bool",
        ):
            with self.subTest(mode=mode):
                service, projection = self._build()
                before = projection.snapshot()
                query_before = projection.query
                service.mode = mode

                event = projection.search(
                    GameSearchQuery(player="Replacement", limit=25)
                )

                self.assertEqual("error", event.payload["snapshot"]["status"])
                self.assertEqual(before, projection.snapshot())
                self.assertEqual(query_before, projection.query)

    def test_sqlite_maximum_identity_values_remain_supported(self) -> None:
        service, projection = self._build()
        service.mode = "valid"

        event = projection.next_page()
        snapshot = event.payload["snapshot"]

        self.assertEqual("ready", snapshot["status"])
        self.assertEqual(11, snapshot["selected_game_id"])
        self.assertEqual(11, snapshot["rows"][0]["game_id"])


if __name__ == "__main__":
    unittest.main()
