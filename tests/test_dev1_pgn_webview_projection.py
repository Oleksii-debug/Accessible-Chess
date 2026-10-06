from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

from acs.full_product_presenters import PgnGameView, PgnTreeItem, PgnTreePresenter
from acs.full_product_ui_shell import UILanguage
from acs.gametree import (
    GameTreeContractError,
    MoveNode,
    PgnGame,
    VariationLine,
    parse_games,
    serialize_games,
)
from acs.pgn_webview_bridge import PgnWebViewBridge
from acs.pgn_webview_projection import PgnWebViewProjection, _utf16_units
from acs.pgn_workspace import (
    MAX_PGN_EDIT_TAG_NAME_CHARS,
    MAX_PGN_EDIT_TAG_VALUE_CHARS,
)


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
        self.bridge = PgnWebViewBridge(self.projection)

    def test_recursive_tree_tags_warnings_and_paths_are_safely_projected(self) -> None:
        snapshot = self.projection.snapshot()
        self.assertEqual("ready", snapshot["status"])
        self.assertEqual(
            {
                "tag_name_max_chars": MAX_PGN_EDIT_TAG_NAME_CHARS,
                "tag_value_max_chars": MAX_PGN_EDIT_TAG_VALUE_CHARS,
            },
            snapshot["edit_contract"],
        )
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

    def test_search_from_move_less_game_delegates_canonical_root_target(self) -> None:
        games = tuple(parse_games('[Event "Needle Event"]\n[Result "*"]\n\n*'))
        calls: list[tuple[str, dict[str, object]]] = []

        def dispatch(action_id: str, payload: dict[str, object]):
            calls.append((action_id, dict(payload)))
            return None

        presenter = PgnTreePresenter(games, language=UILanguage.EN)
        projection = PgnWebViewProjection(
            presenter,
            dispatch,
            lambda: len(games),
            language=UILanguage.EN,
        )
        bridge = PgnWebViewBridge(projection)

        snapshot = projection.snapshot()
        self.assertEqual((), snapshot["tree"])
        search = next(
            action for action in snapshot["actions"] if action["action"] == "pgn.search"
        )
        self.assertTrue(search["enabled"])

        event = bridge.dispatch("pgn.search", {"text": "needle"})
        self.assertEqual("delegated", event.kind)
        self.assertEqual("pgn.search", event.payload["action"])
        self.assertEqual(
            ("pgn.search", {"game_index": 0, "node_id": "", "text": "needle"}),
            calls[-1],
        )

    def test_move_less_main_line_comment_uses_trusted_root_scope(self) -> None:
        games = tuple(
            parse_games('[Event "Root comments"]\n[Result "*"]\n\n{Opening note} *')
        )
        calls: list[tuple[str, dict[str, object]]] = []

        def dispatch(action_id: str, payload: dict[str, object]):
            calls.append((action_id, dict(payload)))
            return None

        presenter = PgnTreePresenter(games, language=UILanguage.EN)
        projection = PgnWebViewProjection(
            presenter,
            dispatch,
            lambda: len(games),
            language=UILanguage.EN,
        )
        bridge = PgnWebViewBridge(projection)

        snapshot = projection.snapshot()
        self.assertEqual((), snapshot["tree"])
        self.assertTrue(
            next(
                action["enabled"]
                for action in snapshot["actions"]
                if action["action"] == "pgn.comment_edit"
            )
        )
        main_entries = [
            entry for entry in snapshot["comment_editor"]["entries"] if entry["main"]
        ]
        self.assertEqual("Opening note", main_entries[0]["value"])

        event = bridge.dispatch(
            "pgn.comment_edit",
            {
                "text": "Updated opening",
                "slot": "leading",
                "index": 0,
                "main": True,
            },
        )
        self.assertEqual("delegated", event.kind)
        self.assertEqual(
            (
                "pgn.comment_edit",
                {
                    "game_index": 0,
                    "node_id": "g0:main",
                    "text": "Updated opening",
                    "slot": "leading",
                    "index": 0,
                },
            ),
            calls[-1],
        )
        self.assertNotIn("main", calls[-1][1])

    def test_move_tree_labels_use_shared_accessible_san_spacing(self) -> None:
        snapshot = self.projection.snapshot()
        move_items = [item for item in snapshot["tree"] if item["kind"] == "move"]
        knight = next(item for item in move_items if item["san"] == "Nf3")

        self.assertIn("N f 3", knight["label"])
        self.assertNotIn("Nf3", knight["label"])

    def test_recovered_malformed_san_remains_readable_but_is_not_presented_as_canonical(self) -> None:
        game = PgnGame(
            tags={"White": "A", "Black": "B"},
            line=VariationLine(moves=[MoveNode("not-a-chess-move")]),
            warnings=["Recovered historical movetext"],
        )
        presenter = PgnTreePresenter((game,), language=UILanguage.EN)
        projection = PgnWebViewProjection(
            presenter,
            self.dispatch,
            lambda: 1,
            language=UILanguage.EN,
        )

        snapshot = projection.snapshot()
        item = snapshot["tree"][0]
        self.assertEqual("not-a-chess-move", item["san"])
        self.assertEqual(
            "Unparsed move text: not-a-chess-move",
            item["label"],
        )
        self.assertEqual(
            ("Recovered historical movetext",),
            snapshot["game"]["warnings"],
        )

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

    def test_failed_language_rebuild_does_not_publish_mixed_nvda_locale(self) -> None:
        move = MoveNode("not-a-chess-move")
        line = VariationLine(moves=[move])
        game = PgnGame(
            tags={"White": "A", "Black": "B"},
            line=line,
            warnings=["Recovered historical movetext"],
        )
        presenter = PgnTreePresenter((game,), language=UILanguage.EN)
        projection = PgnWebViewProjection(
            presenter,
            self.dispatch,
            lambda: 1,
            language=UILanguage.EN,
        )
        before = projection.snapshot()

        move.variations.append(line)
        with self.assertRaisesRegex(GameTreeContractError, "cycle"):
            projection.set_language(UILanguage.UA)

        self.assertIs(UILanguage.EN, projection.language)
        after = projection.snapshot()
        self.assertEqual("en", after["document"]["lang"])
        self.assertEqual(
            "Unparsed move text: not-a-chess-move",
            after["tree"][0]["label"],
        )
        self.assertEqual(before["tree"], after["tree"])
        self.assertEqual("PGN comment", after["comment_editor"]["title"])

    def test_language_render_failure_rolls_back_presenter_and_projection_locale(self) -> None:
        move = MoveNode("not-a-chess-move")
        game = PgnGame(
            tags={"White": "A", "Black": "B"},
            line=VariationLine(moves=[move]),
        )
        count = [1]
        presenter = PgnTreePresenter((game,), language=UILanguage.EN)
        projection = PgnWebViewProjection(
            presenter,
            self.dispatch,
            lambda: count[0],
            language=UILanguage.EN,
        )

        count[0] = 2
        with self.assertRaisesRegex(ValueError, "game count disagrees"):
            projection.set_language(UILanguage.UA)

        self.assertIs(UILanguage.EN, projection.language)
        count[0] = 1
        snapshot = projection.snapshot()
        self.assertEqual("en", snapshot["document"]["lang"])
        self.assertEqual(
            "Unparsed move text: not-a-chess-move",
            snapshot["tree"][0]["label"],
        )
        self.assertEqual("PGN comment", snapshot["comment_editor"]["title"])

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

    def test_presenter_subclass_is_rejected_before_presentation_hooks(self) -> None:
        class HostilePresenter(PgnTreePresenter):
            armed = False
            touched = False

            def set_language(self, language):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("hostile presenter hook must not execute")
                return super().set_language(language)

        hostile = HostilePresenter(self.games, language=UILanguage.EN)
        HostilePresenter.armed = True

        with self.assertRaisesRegex(TypeError, "presenter must be PgnTreePresenter"):
            PgnWebViewProjection(
                hostile,
                self.dispatch,
                lambda: len(self.games),
                language=UILanguage.EN,
            )

        self.assertFalse(HostilePresenter.touched)

    def test_detailed_comment_editor_collections_are_bounded_before_projection(self) -> None:
        base = self.presenter.view()
        variation = next(item for item in base.items if item.kind == "variation")

        for replacement, error, message in (
            (
                replace(variation, trailing_comments=["not-a-tuple"]),
                TypeError,
                "canonical tuples",
            ),
            (
                replace(variation, trailing_comments=("tail",) * 257),
                ValueError,
                "too many comments",
            ),
        ):
            with self.subTest(error=error.__name__):
                items = tuple(
                    replacement if item.node_id == variation.node_id else item
                    for item in base.items
                )
                hostile = replace(
                    base,
                    items=items,
                    selected_node_id=variation.node_id,
                )
                with patch.object(self.presenter, "view", return_value=hostile):
                    with self.assertRaisesRegex(error, message):
                        self.projection.snapshot()

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

    def test_hostile_string_subclasses_fail_before_projection_hooks(self) -> None:
        class HostileText(str):
            touched = False

            def strip(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("hostile strip must never execute")

            def replace(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("hostile replace must never execute")

            def encode(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("hostile encode must never execute")

            def __eq__(self, _other):
                type(self).touched = True
                raise AssertionError("hostile equality must never execute")

        base = self.presenter.view()
        hostile_title = replace(base, title=HostileText("Alpha — Beta"))
        with patch.object(self.presenter, "view", return_value=hostile_title):
            with self.assertRaisesRegex(TypeError, "presentation text must be text"):
                self.projection.snapshot()
        self.assertFalse(HostileText.touched)

        first = base.items[0]
        hostile_item = replace(first, node_id=HostileText(first.node_id))
        hostile_items = replace(
            base,
            items=(hostile_item, *base.items[1:]),
        )
        with patch.object(self.presenter, "view", return_value=hostile_items):
            with self.assertRaisesRegex(ValueError, "node id is invalid"):
                self.projection.snapshot()
        self.assertFalse(HostileText.touched)

        with self.assertRaisesRegex(TypeError, "language must be UILanguage"):
            self.projection.set_language(HostileText("en"))
        with self.assertRaisesRegex(TypeError, "node id must be text"):
            self.projection.select(HostileText(first.node_id))
        with self.assertRaisesRegex(TypeError, "comment text must be text"):
            self.projection.edit_comment(HostileText("note"))
        self.assertFalse(HostileText.touched)

    def test_projection_cardinality_budgets_fail_before_materialization(self) -> None:
        base = self.presenter.view()
        first = base.items[0]

        oversized_tree = replace(
            base,
            items=(first,) * 10001,
            selected_node_id=first.node_id,
        )
        with patch.object(self.presenter, "view", return_value=oversized_tree):
            with self.assertRaisesRegex(ValueError, "tree exceeds the item-count budget"):
                self.projection.snapshot()

        oversized_tags = replace(
            base,
            tags=tuple(("Tag", str(index)) for index in range(257)),
        )
        with patch.object(self.presenter, "view", return_value=oversized_tags):
            with self.assertRaisesRegex(ValueError, "tags exceed the item-count budget"):
                self.projection.snapshot()

        oversized_warnings = replace(
            base,
            warnings=tuple("warning" for _ in range(257)),
        )
        with patch.object(self.presenter, "view", return_value=oversized_warnings):
            with self.assertRaisesRegex(ValueError, "warnings exceed the item-count budget"):
                self.projection.snapshot()

        comment_heavy = replace(
            first,
            comments=tuple("comment" for _ in range(257)),
        )
        heavy_view = replace(
            base,
            items=(comment_heavy, *base.items[1:]),
        )
        with patch.object(self.presenter, "view", return_value=heavy_view):
            with self.assertRaisesRegex(ValueError, "too many comments"):
                self.projection.snapshot()

    def test_raw_text_budget_precedes_path_scrub_scan(self) -> None:
        base = self.presenter.view()
        oversized_title = replace(base, title="xxxxx")
        with (
            patch("acs.pgn_webview_projection._MAX_PGN_RAW_TEXT", 4),
            patch(
                "acs.pgn_webview_projection._scrub_local_paths",
                side_effect=AssertionError("oversized PGN text reached path scrub"),
            ) as scrub,
            patch.object(self.presenter, "view", return_value=oversized_title),
        ):
            with self.assertRaisesRegex(ValueError, "raw text budget"):
                self.projection.snapshot()
        scrub.assert_not_called()

    def test_malformed_presenter_collection_shapes_fail_closed(self) -> None:
        base = self.presenter.view()
        malformed_items = PgnGameView(
            base.game_index,
            base.title,
            base.result,
            base.tags,
            base.warnings,
            list(base.items),  # type: ignore[arg-type]
            base.selected_node_id,
        )
        with patch.object(self.presenter, "view", return_value=malformed_items):
            with self.assertRaisesRegex(TypeError, "canonical tuples"):
                self.projection.snapshot()

        malformed_tag = replace(
            base,
            tags=(["White", "Alpha"],),  # type: ignore[list-item]
        )
        with patch.object(self.presenter, "view", return_value=malformed_tag):
            with self.assertRaisesRegex(TypeError, "tag entry is invalid"):
                self.projection.snapshot()

    def test_bridge_rejects_hostile_scalars_and_payload_dict_subclasses(self) -> None:
        class HostileText(str):
            touched = False

            def strip(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("bridge strip hook must never execute")

            def __contains__(self, _item):
                type(self).touched = True
                raise AssertionError("bridge contains hook must never execute")

        class HostileDict(dict):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("bridge len hook must never execute")

            def items(self):
                type(self).touched = True
                raise AssertionError("bridge items hook must never execute")

        result = self.bridge.dispatch(HostileText("pgn.parent"), {})
        self.assertEqual("error", result.kind)
        self.assertFalse(HostileText.touched)

        result = self.bridge.dispatch("pgn.parent", HostileDict())
        self.assertEqual("error", result.kind)
        self.assertFalse(HostileDict.touched)

        result = self.bridge.dispatch(
            "pgn.select",
            {"node_id": HostileText(self.presenter.selected_node_id or "")},
        )
        self.assertEqual("error", result.kind)
        self.assertFalse(HostileText.touched)

    def test_bridge_rejects_oversized_command_before_normalization(self) -> None:
        class StripBomb(str):
            touched = False

            def strip(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("oversized command must fail before strip")

        result = self.bridge.dispatch(StripBomb("x" * 65), {})
        self.assertEqual("error", result.kind)
        self.assertFalse(StripBomb.touched)

    def test_direct_projection_rejects_surrogate_edit_text_before_dispatch(self) -> None:
        before = list(self.calls)
        operations = (
            lambda: self.projection.search("\ud800"),
            lambda: self.projection.append_moves("e4 {\ud800}"),
            lambda: self.projection.edit_comment("\udfff"),
            lambda: self.projection.edit_nags("$1 \ud800"),
            lambda: self.projection.add_variation("c5 {\udfff}"),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaises(ValueError):
                    operation()
                self.assertEqual(before, self.calls)

    def test_utf16_unit_counter_is_total_for_lone_surrogates(self) -> None:
        self.assertEqual(1, _utf16_units("\ud800"))
        self.assertEqual(1, _utf16_units("\udfff"))
        self.assertEqual(2, _utf16_units("😀"))

    def test_utf16_bounds_match_the_webview_contract(self) -> None:
        base = self.presenter.view()
        emoji_title = replace(base, title="😀" * 240)
        with patch.object(self.presenter, "view", return_value=emoji_title):
            snapshot = self.projection.snapshot()
        heading = snapshot["game"]["heading"]
        self.assertEqual(120, len(heading))
        self.assertEqual(240, len(heading.encode("utf-16-le")) // 2)

        before = list(self.calls)
        with self.assertRaisesRegex(ValueError, "comment text is invalid"):
            self.projection.edit_comment("😀" * 4001)
        self.assertEqual(before, self.calls)

        accepted = "😀" * 4000
        self.projection.edit_comment(accepted)
        self.assertEqual(accepted, self.calls[-1][1]["text"])

        bounded_calls = (
            (lambda text: self.projection.search(text), 2048),
            (lambda text: self.projection.append_moves(text), 4096),
            (lambda text: self.projection.edit_tag("Event", text), 180),
            (lambda text: self.projection.edit_nags(text), 256),
            (lambda text: self.projection.add_variation(text), 4096),
        )
        for call, emoji_limit in bounded_calls:
            with self.subTest(emoji_limit=emoji_limit):
                before = list(self.calls)
                with self.assertRaises(ValueError):
                    call("😀" * (emoji_limit + 1))
                self.assertEqual(before, self.calls)
                call("😀" * emoji_limit)
                self.assertEqual("😀" * emoji_limit, self.calls[-1][1]["text"] if "text" in self.calls[-1][1] else self.calls[-1][1]["value"])

        with patch.object(
            self.projection,
            "search",
            side_effect=AssertionError("bridge must reject UTF-16 overflow first"),
        ) as search:
            result = self.bridge.dispatch("pgn.search", {"text": "😀" * 2049})
        self.assertEqual("error", result.kind)
        search.assert_not_called()

        result = self.bridge.dispatch("pgn.search", {"text": "😀" * 2048})
        self.assertEqual("delegated", result.kind)
        self.assertEqual("😀" * 2048, self.calls[-1][1]["text"])

    def test_comment_input_is_bounded_and_nul_rejected_before_dispatch(self) -> None:
        before = list(self.calls)
        with self.assertRaises(ValueError):
            self.projection.edit_comment("x" * 8001)
        with self.assertRaises(ValueError):
            self.projection.edit_comment("bad\x00comment")
        self.assertEqual(before, self.calls)


    def test_failed_selection_publication_restores_nvda_cursor_and_retry_commits(self) -> None:
        before = self.projection.snapshot()
        before_selected = self.presenter.selected_node_id
        target = self.presenter.items()[1].node_id
        self.assertNotEqual(before_selected, target)

        with patch.object(
            self.projection,
            "snapshot",
            side_effect=RuntimeError("candidate selection render rejected"),
        ):
            with self.assertRaisesRegex(RuntimeError, "candidate selection render rejected"):
                self.projection.select(target)

        self.assertEqual(before_selected, self.presenter.selected_node_id)
        self.assertEqual(before, self.projection.snapshot())

        committed = self.projection.select(target)
        self.assertEqual(target, self.presenter.selected_node_id)
        self.assertEqual(
            target,
            next(
                item["node_id"]
                for item in committed.payload["snapshot"]["tree"]
                if item["selected"]
            ),
        )

    def test_failed_game_publication_restores_game_tree_selection_and_retry_commits(self) -> None:
        before = self.projection.snapshot()
        before_items = self.presenter.items()
        before_selected = self.presenter.selected_node_id
        self.assertEqual(0, self.presenter.game_index)

        with patch.object(
            self.projection,
            "snapshot",
            side_effect=RuntimeError("candidate game render rejected"),
        ):
            with self.assertRaisesRegex(RuntimeError, "candidate game render rejected"):
                self.projection.next_game()

        self.assertEqual(0, self.presenter.game_index)
        self.assertIs(before_items, self.presenter.items())
        self.assertEqual(before_selected, self.presenter.selected_node_id)
        self.assertEqual(before, self.projection.snapshot())

        committed = self.projection.next_game()
        self.assertEqual(1, self.presenter.game_index)
        self.assertEqual(1, committed.payload["snapshot"]["game"]["index"])

    def test_abort_during_selection_publication_rolls_back_and_safe_call_sanitizes(self) -> None:
        class AbortSignal(BaseException):
            pass

        target = self.presenter.items()[1].node_id
        before_selected = self.presenter.selected_node_id
        with patch.object(
            self.projection,
            "snapshot",
            side_effect=AbortSignal("private render abort C:/Users/private/secret.pgn"),
        ):
            event = self.projection.safe_call(lambda: self.projection.select(target))

        self.assertEqual("error", event.kind)
        self.assertEqual(before_selected, self.presenter.selected_node_id)
        self.assertEqual(
            "The action could not be completed.",
            event.payload["message"],
        )
        self.assertNotIn("private", repr(event))
        self.assertNotIn("secret.pgn", repr(event))

    def test_abort_during_locale_publication_restores_presenter_and_projection_language(self) -> None:
        class AbortSignal(BaseException):
            pass

        before = self.projection.snapshot()
        with patch.object(
            self.projection,
            "snapshot",
            side_effect=AbortSignal("private locale publication abort"),
        ):
            with self.assertRaises(AbortSignal):
                self.projection.set_language(UILanguage.UA)

        self.assertIs(UILanguage.EN, self.projection.language)
        self.assertEqual(before, self.projection.snapshot())
        committed = self.projection.set_language(UILanguage.UA)
        self.assertEqual("uk", committed.payload["document"]["lang"])


if __name__ == "__main__":
    unittest.main()
