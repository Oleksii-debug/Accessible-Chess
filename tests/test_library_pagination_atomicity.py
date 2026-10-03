from __future__ import annotations

import unittest

from acs.full_product_presenters import LibraryPresenter
from acs.library_webview_projection import LibraryWebViewProjection
from acs.search_service import GameSearchItem, GameSearchPage, GameSearchQuery


def _item(game_id: int, white: str, black: str) -> GameSearchItem:
    return GameSearchItem(
        game_id=game_id,
        source_id=1,
        source_name="starter.acsdb",
        source_format="pgn",
        source_index=game_id - 1,
        import_status="ok",
        white=white,
        black=black,
        event="Atomic paging",
        site=None,
        game_date=None,
        round=None,
        result="1-0",
        eco=None,
        opening=None,
        start_fen=None,
    )


class _PagingService:
    def __init__(self) -> None:
        self.fail_next = False
        self.calls: list[GameSearchQuery] = []

    def search(self, query: GameSearchQuery) -> GameSearchPage:
        query = query.normalized()
        self.calls.append(query)
        if query.after_game_id is None:
            return GameSearchPage(
                items=(_item(1, "Alpha", "Beta"),),
                next_after_game_id=1,
                has_more=True,
            )
        if query.after_game_id != 1:
            raise AssertionError("unexpected paging cursor")
        if self.fail_next:
            raise PermissionError(r"C:\\Users\\BlindTeacher\\private-library.sqlite")
        return GameSearchPage(
            items=(_item(2, "Gamma", "Delta"),),
            next_after_game_id=None,
            has_more=False,
        )


class LibraryPaginationAtomicityTests(unittest.TestCase):
    def test_failed_next_page_is_transient_and_retry_keeps_navigation_coherent(self) -> None:
        service = _PagingService()
        presenter = LibraryPresenter(service)  # type: ignore[arg-type]
        projection = LibraryWebViewProjection(presenter, lambda _action, _payload: None)
        query = GameSearchQuery(player="Alpha", limit=25).normalized()

        first = projection.search(query)
        self.assertEqual("ready", first.payload["snapshot"]["status"])
        self.assertEqual(1, first.payload["snapshot"]["selected_game_id"])
        committed = projection.snapshot()

        service.fail_next = True
        failed = projection.next_page()
        failed_snapshot = failed.payload["snapshot"]
        self.assertEqual("error", failed_snapshot["status"])
        self.assertEqual(1, failed_snapshot["selected_game_id"])
        self.assertNotIn("BlindTeacher", failed_snapshot["message"])
        self.assertNotIn("private-library", failed_snapshot["message"])

        # The failed action is announced, but the canonical Library state remains
        # the exact last committed page so keyboard/NVDA navigation can retry.
        self.assertEqual(committed, projection.snapshot())
        self.assertEqual(query, projection.query)

        service.fail_next = False
        second = projection.next_page()
        self.assertEqual("ready", second.payload["snapshot"]["status"])
        self.assertEqual(2, second.payload["snapshot"]["selected_game_id"])
        self.assertEqual("", second.payload["snapshot"]["message"])
        calls_after_retry = len(service.calls)

        previous = projection.previous_page()
        self.assertEqual("ready", previous.payload["snapshot"]["status"])
        self.assertEqual(1, previous.payload["snapshot"]["selected_game_id"])
        self.assertEqual("", previous.payload["snapshot"]["message"])

        cached_second = projection.next_page()
        self.assertEqual("ready", cached_second.payload["snapshot"]["status"])
        self.assertEqual(2, cached_second.payload["snapshot"]["selected_game_id"])
        self.assertEqual("", cached_second.payload["snapshot"]["message"])
        self.assertEqual(calls_after_retry, len(service.calls))


if __name__ == "__main__":
    unittest.main()
