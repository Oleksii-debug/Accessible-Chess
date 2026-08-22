from __future__ import annotations

import unittest

from acs.full_product_presenters import PgnTreePresenter
from acs.full_product_ui_shell import UILanguage
from acs.gametree import parse_games
from acs.pgn_webview_projection import PgnWebViewProjection


PGN = """[Event "Atomic"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 {first comment} e5 2. Nf3 *
"""


class MutatingAfterReadPresenter(PgnTreePresenter):
    """Mutate live selection after the first immutable view has been captured."""

    def __init__(self, games) -> None:
        super().__init__(games, language=UILanguage.EN)
        self.view_calls = 0
        self.first_selected_node_id = ""
        self.live_selected_after_first_read = ""

    def view(self):
        self.view_calls += 1
        view = super().view()
        if self.view_calls == 1 and len(view.items) > 1:
            self.first_selected_node_id = view.selected_node_id or ""
            self.select(view.items[1].node_id)
            self.live_selected_after_first_read = self.selected_node_id or ""
        return view


class PgnWebViewAtomicityTests(unittest.TestCase):
    def test_one_browser_snapshot_uses_one_immutable_presenter_view(self) -> None:
        games = tuple(parse_games(PGN))
        presenter = MutatingAfterReadPresenter(games)
        projection = PgnWebViewProjection(
            presenter,
            lambda _action, _payload: None,
            lambda: len(games),
            language=UILanguage.EN,
        )

        # Construction changes language but does not call view(). Keep the assertion
        # explicit so a future constructor change cannot hide extra render reads.
        presenter.view_calls = 0
        snapshot = projection.snapshot()

        self.assertEqual(1, presenter.view_calls)
        self.assertNotEqual(
            presenter.first_selected_node_id,
            presenter.live_selected_after_first_read,
        )

        selected_rows = [row for row in snapshot["tree"] if row["selected"]]
        self.assertEqual(1, len(selected_rows))
        self.assertEqual(presenter.first_selected_node_id, selected_rows[0]["node_id"])
        self.assertEqual(selected_rows[0]["dom_id"], snapshot["focus_target"])

        # The captured first node has exactly one comment. The live presenter was
        # moved to the second node before view() returned. Action/editor state must
        # still come from the captured immutable view rather than the live mutation.
        self.assertTrue(snapshot["comment_editor"]["enabled"])
        self.assertEqual("first comment", snapshot["comment_editor"]["value"])
        action_state = {
            action["action"]: action["enabled"]
            for action in snapshot["actions"]
        }
        self.assertTrue(action_state["pgn.comment_delete"])

    def test_inconsistent_selected_node_in_immutable_view_fails_closed(self) -> None:
        games = tuple(parse_games(PGN))

        class BrokenPresenter(PgnTreePresenter):
            def view(self):
                view = super().view()
                return type(view)(
                    game_index=view.game_index,
                    title=view.title,
                    result=view.result,
                    tags=view.tags,
                    warnings=view.warnings,
                    items=view.items,
                    selected_node_id="missing-node",
                )

        projection = PgnWebViewProjection(
            BrokenPresenter(games, language=UILanguage.EN),
            lambda _action, _payload: None,
            lambda: len(games),
            language=UILanguage.EN,
        )
        with self.assertRaises(ValueError):
            projection.snapshot()


if __name__ == "__main__":
    unittest.main()
