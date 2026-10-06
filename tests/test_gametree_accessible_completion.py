from __future__ import annotations

from pathlib import Path
import unittest

from acs.full_product_presenters import PgnTreePresenter
from acs.full_product_ui_shell import UILanguage
from acs.gametree import parse_games
from acs.gametree_navigation import GameTreeCursor, VariationStep, resolve_line
from acs.pgn_document import PgnDocumentSession
from acs.pgn_workspace import MAX_PGN_EDIT_TAG_NAME_CHARS, MAX_PGN_EDIT_TAG_VALUE_CHARS
from acs.pgn_webview_bridge import PgnWebViewBridge
from acs.pgn_webview_projection import PgnWebViewProjection
from acs.version2_pgn_commands import Version2PgnCommands


DOCUMENT = """[Event "Tree"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 (1... c5 2. Nf3) (1... c6 2. d4) (1... d5 2. exd5) 2. Nf3 Nc6 *
"""


def command_target(session: PgnDocumentSession) -> dict[str, object]:
    view = session.workspace.view()
    cursor = session.workspace.cursor
    return {
        "game_index": view.selected_game_index,
        "line_path": tuple(
            (step.parent_move_index, step.variation_index)
            for step in cursor.line_path
        ),
        "move_index": cursor.next_move_index - 1 if cursor.next_move_index else None,
        "expected_record_digest": view.current_record_digest,
        "expected_content_digest": view.content_digest,
        "content_revision": view.content_revision,
    }


class AccessibleGameTreeCompletionTests(unittest.TestCase):
    def test_variation_can_move_down_and_up_without_changing_content(self):
        session = PgnDocumentSession.from_text(DOCUMENT)
        workspace = session.workspace
        commands = Version2PgnCommands(lambda: session)

        middle_path = (VariationStep(1, 1),)
        workspace.set_cursor(GameTreeCursor(middle_path, 0))
        payload = {
            **command_target(session),
            "parent_path": (),
            "parent_move_index": 1,
            "variation_index": 1,
        }

        commands("pgn.variation_move_down", payload)
        game = workspace.current_game()
        self.assertEqual(
            [
                resolve_line(game, (VariationStep(1, index),)).moves[0].san
                for index in range(3)
            ],
            ["c5", "d5", "c6"],
        )
        self.assertEqual(workspace.cursor, GameTreeCursor((VariationStep(1, 2),), 0))

        payload = {
            **command_target(session),
            "parent_path": (),
            "parent_move_index": 1,
            "variation_index": 2,
        }
        commands("pgn.variation_move_up", payload)
        game = workspace.current_game()
        self.assertEqual(
            [
                resolve_line(game, (VariationStep(1, index),)).moves[0].san
                for index in range(3)
            ],
            ["c5", "c6", "d5"],
        )
        self.assertEqual(workspace.cursor, GameTreeCursor((VariationStep(1, 1),), 0))
        self.assertTrue(workspace.dirty)

    def test_reorder_boundary_fails_atomically(self):
        session = PgnDocumentSession.from_text(DOCUMENT)
        workspace = session.workspace
        commands = Version2PgnCommands(lambda: session)
        workspace.set_cursor(GameTreeCursor((VariationStep(1, 0),), 0))
        before = workspace.to_text()
        before_revision = workspace.content_revision

        with self.assertRaises(ValueError):
            commands(
                "pgn.variation_move_up",
                {
                    **command_target(session),
                    "parent_path": (),
                    "parent_move_index": 1,
                    "variation_index": 0,
                },
            )

        self.assertEqual(workspace.to_text(), before)
        self.assertEqual(workspace.content_revision, before_revision)
        self.assertEqual(workspace.cursor, GameTreeCursor((VariationStep(1, 0),), 0))

    def test_projection_preserves_current_tag_edit_contract(self):
        games = tuple(parse_games(DOCUMENT))
        presenter = PgnTreePresenter(games, language=UILanguage.EN)
        projection = PgnWebViewProjection(
            presenter,
            lambda _action, _payload: None,
            lambda: 1,
            language=UILanguage.EN,
        )

        snapshot = projection.snapshot()
        self.assertEqual(
            snapshot["edit_contract"]["tag_name_max_chars"],
            MAX_PGN_EDIT_TAG_NAME_CHARS,
        )
        self.assertEqual(
            snapshot["edit_contract"]["tag_value_max_chars"],
            MAX_PGN_EDIT_TAG_VALUE_CHARS,
        )

    def test_projection_reports_mainline_context_and_alternative_count(self):
        games = tuple(parse_games(DOCUMENT))
        presenter = PgnTreePresenter(games, language=UILanguage.EN)
        move = next(item for item in presenter.items() if item.node_id.endswith("/m1"))
        presenter.select(move.node_id)
        projection = PgnWebViewProjection(
            presenter,
            lambda _action, _payload: None,
            lambda: 1,
            language=UILanguage.EN,
        )

        snapshot = projection.snapshot()
        context = snapshot["selection_context"]
        self.assertIn("Main line", context)
        self.assertIn("Alternatives to this move: 3", context)
        self.assertIn("Line continues", context)

    def test_projection_reports_variation_depth_sibling_position_and_parent(self):
        games = tuple(parse_games(DOCUMENT))
        presenter = PgnTreePresenter(games, language=UILanguage.EN)
        middle = next(
            item
            for item in presenter.items()
            if item.kind == "variation" and item.node_id.endswith("/m1/v1")
        )
        presenter.select(middle.node_id)
        projection = PgnWebViewProjection(
            presenter,
            lambda _action, _payload: None,
            lambda: 1,
            language=UILanguage.EN,
        )

        snapshot = projection.snapshot()
        self.assertIn("Variation depth: 1", snapshot["selection_context"])
        self.assertIn("Alternative 2 of 3", snapshot["selection_context"])
        self.assertIn("parent position", snapshot["selection_context"].lower())
        actions = {item["action"]: item for item in snapshot["actions"]}
        self.assertTrue(actions["pgn.variation_move_up"]["enabled"])
        self.assertTrue(actions["pgn.variation_move_down"]["enabled"])

    def test_reorder_buttons_disable_at_sibling_boundaries(self):
        games = tuple(parse_games(DOCUMENT))
        presenter = PgnTreePresenter(games, language=UILanguage.EN)
        projection = PgnWebViewProjection(
            presenter,
            lambda _action, _payload: None,
            lambda: 1,
            language=UILanguage.EN,
        )

        first = next(
            item
            for item in presenter.items()
            if item.kind == "variation" and item.node_id.endswith("/m1/v0")
        )
        presenter.select(first.node_id)
        actions = {item["action"]: item for item in projection.snapshot()["actions"]}
        self.assertFalse(actions["pgn.variation_move_up"]["enabled"])
        self.assertTrue(actions["pgn.variation_move_down"]["enabled"])

        last = next(
            item
            for item in presenter.items()
            if item.kind == "variation" and item.node_id.endswith("/m1/v2")
        )
        presenter.select(last.node_id)
        actions = {item["action"]: item for item in projection.snapshot()["actions"]}
        self.assertTrue(actions["pgn.variation_move_up"]["enabled"])
        self.assertFalse(actions["pgn.variation_move_down"]["enabled"])

    def test_bridge_exposes_reorder_commands_without_browser_authority_fields(self):
        games = tuple(parse_games(DOCUMENT))
        presenter = PgnTreePresenter(games, language=UILanguage.EN)
        calls: list[tuple[str, dict[str, object]]] = []

        def dispatch(action: str, payload):
            calls.append((action, dict(payload)))

        projection = PgnWebViewProjection(
            presenter,
            dispatch,
            lambda: 1,
            language=UILanguage.EN,
        )
        middle = next(
            item
            for item in presenter.items()
            if item.kind == "variation" and item.node_id.endswith("/m1/v1")
        )
        projection.select(middle.node_id)
        bridge = PgnWebViewBridge(projection)

        down = bridge.dispatch("pgn.variation_move_down", {})
        self.assertEqual(down.kind, "delegated")
        self.assertEqual(calls[-1][0], "pgn.variation_move_down")
        self.assertEqual(set(calls[-1][1]), {"game_index", "node_id"})

    def test_bridge_rejects_malformed_unicode_tag_payload_without_dispatch(self):
        games = tuple(parse_games(DOCUMENT))
        presenter = PgnTreePresenter(games, language=UILanguage.EN)
        calls: list[tuple[str, dict[str, object]]] = []

        def dispatch(action: str, payload):
            calls.append((action, dict(payload)))

        projection = PgnWebViewProjection(
            presenter,
            dispatch,
            lambda: 1,
            language=UILanguage.EN,
        )
        bridge = PgnWebViewBridge(projection)

        for value in ("lone-high-\ud800", "lone-low-\udfff"):
            with self.subTest(value=repr(value)):
                result = bridge.dispatch(
                    "pgn.tag_edit",
                    {"name": "Event", "value": value},
                )
                self.assertEqual(result.kind, "error")
                self.assertEqual(
                    result.payload.get("message"),
                    "The action could not be completed.",
                )
                self.assertEqual(calls, [])

    def test_browser_surface_describes_selected_treeitem_with_structural_context(self):
        js = (
            Path(__file__).resolve().parents[1] / "web" / "full_product_pgn.js"
        ).read_text(encoding="utf-8")
        for marker in (
            '"pgn.variation_move_up"',
            '"pgn.variation_move_down"',
            '"PGN selection context"',
            '"pgn-selection-context"',
            'treeItem.setAttribute("aria-describedby", "pgn-selection-context")',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, js)


if __name__ == "__main__":
    unittest.main()
