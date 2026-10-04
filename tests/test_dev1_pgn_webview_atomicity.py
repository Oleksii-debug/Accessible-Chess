from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

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


class PgnWebViewAtomicityTests(unittest.TestCase):
    def test_one_browser_snapshot_uses_one_immutable_presenter_view(self) -> None:
        games = tuple(parse_games(PGN))
        presenter = PgnTreePresenter(games, language=UILanguage.EN)
        projection = PgnWebViewProjection(
            presenter,
            lambda _action, _payload: None,
            lambda: len(games),
            language=UILanguage.EN,
        )
        original_view = presenter.view
        state = {
            "view_calls": 0,
            "first_selected_node_id": "",
            "live_selected_after_first_read": "",
        }

        def mutating_view():
            state["view_calls"] += 1
            view = original_view()
            if state["view_calls"] == 1 and len(view.items) > 1:
                state["first_selected_node_id"] = view.selected_node_id or ""
                presenter.select(view.items[1].node_id)
                state["live_selected_after_first_read"] = presenter.selected_node_id or ""
            return view

        # Inject re-entrancy into one exact canonical presenter rather than
        # making a presenter subclass part of the product ingress contract.
        with patch.object(presenter, "view", side_effect=mutating_view):
            snapshot = projection.snapshot()

        self.assertEqual(1, state["view_calls"])
        self.assertNotEqual(
            state["first_selected_node_id"],
            state["live_selected_after_first_read"],
        )

        selected_rows = [row for row in snapshot["tree"] if row["selected"]]
        self.assertEqual(1, len(selected_rows))
        self.assertEqual(state["first_selected_node_id"], selected_rows[0]["node_id"])
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
        presenter = PgnTreePresenter(games, language=UILanguage.EN)
        projection = PgnWebViewProjection(
            presenter,
            lambda _action, _payload: None,
            lambda: len(games),
            language=UILanguage.EN,
        )
        broken = replace(presenter.view(), selected_node_id="missing-node")

        with patch.object(presenter, "view", return_value=broken):
            with self.assertRaises(ValueError):
                projection.snapshot()


if __name__ == "__main__":
    unittest.main()
