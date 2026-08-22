from __future__ import annotations

import unittest

from acs.full_product_presenters import LibraryPresenter, LibraryView
from acs.full_product_ui_shell import UILanguage
from acs.library_webview_projection import LibraryWebViewProjection
from acs.search_service import GameSearchItem, GameSearchPage, GameSearchQuery


def row(game_id: int) -> GameSearchItem:
    return GameSearchItem(
        game_id=game_id,
        source_id=1,
        source_name="safe.pgn",
        source_format="pgn",
        source_index=game_id,
        import_status="full",
        white=f"White {game_id}",
        black=f"Black {game_id}",
        event=None,
        site=None,
        game_date=None,
        round=None,
        result="*",
        eco=None,
        opening=None,
        start_fen=None,
    )


class Service:
    def search(self, _query):
        return GameSearchPage((row(1), row(2)), None, False)


class MutatingAfterReadPresenter(LibraryPresenter):
    def __init__(self, service) -> None:
        super().__init__(service, language=UILanguage.EN)
        self.view_calls = 0
        self.mutate_after_read = False
        self.captured_selected = None
        self.live_selected_after_read = None

    def view(self):
        self.view_calls += 1
        view = super().view()
        if self.mutate_after_read and self.view_calls == 1 and len(view.rows) > 1:
            self.captured_selected = view.selected_game_id
            self._selected_game_id = view.rows[1].game_id
            self.live_selected_after_read = self._selected_game_id
        return view


class LibraryWebViewAtomicityTests(unittest.TestCase):
    def test_passive_browser_snapshot_uses_one_immutable_library_view(self) -> None:
        presenter = MutatingAfterReadPresenter(Service())
        presenter.search(GameSearchQuery())
        presenter.view_calls = 0
        presenter.mutate_after_read = True
        projection = LibraryWebViewProjection(
            presenter,
            lambda _action, _payload: None,
            language=UILanguage.EN,
        )

        snapshot = projection.snapshot()
        self.assertEqual(1, presenter.view_calls)
        self.assertNotEqual(presenter.captured_selected, presenter.live_selected_after_read)
        selected = [item for item in snapshot["rows"] if item["selected"]]
        self.assertEqual(1, len(selected))
        self.assertEqual(presenter.captured_selected, selected[0]["game_id"])
        self.assertEqual(selected[0]["dom_id"], snapshot["focus_target"])

    def test_inconsistent_immutable_selection_fails_closed(self) -> None:
        class BrokenPresenter(LibraryPresenter):
            def view(self):
                view = super().view()
                return LibraryView(
                    status=view.status,
                    rows=view.rows,
                    selected_game_id=999,
                    has_previous_page=view.has_previous_page,
                    has_next_page=view.has_next_page,
                    message=view.message,
                )

        presenter = BrokenPresenter(Service(), language=UILanguage.EN)
        presenter.search(GameSearchQuery())
        projection = LibraryWebViewProjection(
            presenter,
            lambda _action, _payload: None,
            language=UILanguage.EN,
        )
        with self.assertRaises(ValueError):
            projection.snapshot()


if __name__ == "__main__":
    unittest.main()
