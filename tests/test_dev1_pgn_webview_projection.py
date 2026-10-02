from __future__ import annotations

import unittest

from acs.full_product_presenters import PgnTreePresenter
from acs.full_product_ui_shell import UILanguage
from acs.gametree import parse_games, serialize_games
from acs.pgn_webview_projection import PgnWebViewProjection


PGN = """[Event \"C:/Users/private/tournament.pgn\"]
[White \"White\"]
[Black \"Black\"]
[Result \"*\"]

1. e4 {main /home/private/notes.txt} e5 $1 (1... c5 {Sicilian} 2. Nf3 (2. Nc3)) 2. Nf3 *

[Event \"Second\"]
[White \"A\"]
[Black \"B\"]
[Result \"1-0\"]

1. d4 {one} {two} d5 1-0
"""


class PgnWebViewProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.games = tuple(parse_games(PGN))
        self.calls: list[tuple[str, dict[str, object]]] = []

        def dispatch(action_id: str, payload: dict[str, object]):
            self.calls.append((action_id, dict(payload)))
            return {
                "token": "SECRET",
                "path": "C:/Users/private/export.pgn",
                "fen": "8/8/8/8/8/8/8/8 w - - 0 1",
            }

        self.dispatch = dispatch
        self.presenter = PgnTreePresenter(self.games, language=UILanguage.EN)
        self.projection = PgnWebViewProjection(
            self.presenter,
            dispatch,
            lambda: len(self.games),
            language=UILanguage.EN,
        )

    def test_recursive_tree_tags_warnings_and_paths_are_safely_projected(self) -> None:
        snapshot = self.projection.snapshot()
        self.assertEqual("ready", snapshot["status"])
        self.assertEqual("Game 1 of 2", snapshot["game"]["position_label"])
        self.assertEqual("White — Black", snapshot["game"]["heading"])
        tree = snapshot["tree"]
        self.assertTrue(any(item["kind"] == "variation" for item in tree))
        self.assertGreaterEqual(max(item["aria_level"] for item in tree), 4)
        self.assertTrue(any("$1" in item["label"] for item in tree))
        serialized = repr(snapshot)
        self.assertIn("[local path hidden]", serialized)
        self.assertNotIn("C:/Users/private", serialized)
        self.assertNotIn("/home/private", serialized)

    def test_raw_node_identity_is_not_reused_as_dom_identity(self) -> None:
        snapshot = self.projection.snapshot()
        first = snapshot["tree"][0]
        self.assertTrue(first["node_id"].startswith("g0:main/"))
        self.assertTrue(first["dom_id"].startswith("pgn-node-"))
        self.assertNotIn(first["node_id"], first["dom_id"])
        self.assertEqual(first["dom_id"], snapshot["focus_target"])

    def test_keyboard_navigation_parent_and_game_switch_preserve_explicit_focus(self) -> None:
        first = self.projection.snapshot()["focus_target"]
        moved = self.projection.move_selection(1)
        self.assertEqual("selection", moved.kind)
        self.assertNotEqual(first, moved.payload["focus_target"])
        variation = next(item for item in self.presenter.items() if item.kind == "variation")
        selected = self.projection.select(variation.node_id)
        self.assertEqual("selection", selected.kind)
        parent = self.projection.select_parent()
        self.assertEqual(variation.parent_id, self.presenter.selected_node_id)
        self.assertEqual(self.projection.snapshot()["focus_target"], parent.payload["focus_target"])
        second = self.projection.next_game()
        self.assertEqual(1, second.payload["snapshot"]["game"]["index"])
        previous = self.projection.previous_game()
        self.assertEqual(0, previous.payload["snapshot"]["game"]["index"])

    def test_language_changes_labels_not_canonical_presentation_identity(self) -> None:
        before = self.projection.snapshot()
        event = self.projection.set_language(UILanguage.UA)
        self.assertEqual("render", event.kind)
        after = self.projection.snapshot()
        self.assertEqual(
            [item["node_id"] for item in before["tree"]],
            [item["node_id"] for item in after["tree"]],
        )
        self.assertEqual(
            [item["dom_id"] for item in before["tree"]],
            [item["dom_id"] for item in after["tree"]],
        )
        self.assertEqual("Партія 1 з 2", after["game"]["position_label"])
        self.assertEqual("Коментар PGN", after["comment_editor"]["title"])
        self.assertEqual("Зберегти", after["comment_editor"]["save_label"])

    def test_comment_and_variation_commands_do_not_mutate_ui_tree_or_expose_backend_result(self) -> None:
        before = serialize_games(self.games)
        event = self.projection.edit_comment("new comment")
        self.assertEqual("delegated", event.kind)
        self.assertEqual("pgn.comment_edit", event.payload["action"])
        self.assertNotIn("SECRET", repr(event.payload))
        self.assertNotIn("C:/Users/private", repr(event.payload))
        self.assertEqual(before, serialize_games(self.games))
        self.assertEqual("pgn.comment_edit", self.calls[-1][0])
        self.assertEqual("new comment", self.calls[-1][1]["text"])

        variation = next(item for item in self.presenter.items() if item.kind == "variation")
        self.projection.select(variation.node_id)
        promoted = self.projection.promote_variation()
        self.assertEqual("pgn.variation_promote", promoted.payload["action"])
        deleted = self.projection.delete_variation()
        self.assertEqual("pgn.variation_delete", deleted.payload["action"])
        self.assertEqual(before, serialize_games(self.games))

    def test_multiple_comments_are_not_silently_collapsed_for_editing(self) -> None:
        self.projection.next_game()
        move = next(item for item in self.presenter.items() if item.kind == "move" and item.san == "d4")
        self.projection.select(move.node_id)
        snapshot = self.projection.snapshot()
        self.assertEqual(2, len(next(item for item in snapshot["tree"] if item["node_id"] == move.node_id)["comments"]))
        self.assertFalse(snapshot["comment_editor"]["enabled"])
        self.assertIn("multiple comments", snapshot["comment_editor"]["message"].lower())
        before = list(self.calls)
        with self.assertRaises(ValueError):
            self.projection.edit_comment("must not merge")
        self.assertEqual(before, self.calls)

    def test_comment_delete_requires_exactly_one_comment(self) -> None:
        first = self.presenter.selected()
        self.assertIsNotNone(first)
        self.assertEqual(1, len(first.comments))
        event = self.projection.delete_comment()
        self.assertEqual("pgn.comment_delete", event.payload["action"])

        no_comment = next(item for item in self.presenter.items() if item.kind == "move" and not item.comments)
        self.projection.select(no_comment.node_id)
        before = list(self.calls)
        with self.assertRaises(ValueError):
            self.projection.delete_comment()
        self.assertEqual(before, self.calls)

    def test_variation_mutations_fail_closed_on_move_selection(self) -> None:
        move = next(item for item in self.presenter.items() if item.kind == "move")
        self.projection.select(move.node_id)
        before = list(self.calls)
        with self.assertRaises(ValueError):
            self.projection.promote_variation()
        with self.assertRaises(ValueError):
            self.projection.delete_variation()
        self.assertEqual(before, self.calls)

    def test_copy_and_export_are_delegated_without_backend_payload_projection(self) -> None:
        copied = self.projection.copy_selection()
        exported = self.projection.export_selection()
        self.assertEqual("pgn.copy_selection", copied.payload["action"])
        self.assertEqual("pgn.export_selection", exported.payload["action"])
        serialized = repr((copied.payload, exported.payload))
        self.assertNotIn("SECRET", serialized)
        self.assertNotIn("fen", serialized.lower())

    def test_game_count_provider_rejects_false_green_or_coercive_values(self) -> None:
        for value in (True, -1, len(self.games) + 1):
            with self.subTest(value=value):
                projection = PgnWebViewProjection(
                    PgnTreePresenter(self.games),
                    self.dispatch,
                    lambda value=value: value,
                )
                with self.assertRaises(ValueError):
                    projection.snapshot()

    def test_comment_input_is_bounded_and_nul_rejected_before_dispatch(self) -> None:
        before = list(self.calls)
        with self.assertRaises(ValueError):
            self.projection.edit_comment("x" * 8001)
        with self.assertRaises(ValueError):
            self.projection.edit_comment("bad\x00comment")
        self.assertEqual(before, self.calls)


if __name__ == "__main__":
    unittest.main()
