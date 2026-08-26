from __future__ import annotations

from types import SimpleNamespace
import unittest

from acs.full_product_ui_shell import UILanguage
from acs.gametree import parse_games
from acs.gametree_navigation import GameTreeCursor
from acs.pgn_webview_bridge import PgnWebViewBridge
from acs.pgn_workspace_webview_adapter import PgnWorkspaceWebViewProjection


DOCUMENT = '''[Event "One"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 e5 (1... c5 {Sicilian} 2. Nf3) 2. Nf3 Nc6 1-0

[Event "Two"]
[White "Gamma"]
[Black "Delta"]
[Result "1/2-1/2"]

1. d4 d5 1/2-1/2
'''


class _Workspace:
    def __init__(self) -> None:
        self._games = tuple(parse_games(DOCUMENT))
        self._selected = 0
        self._cursor = GameTreeCursor()
        self._revision = 7
        self.set_cursor_calls: list[GameTreeCursor] = []

    @property
    def game_count(self) -> int:
        return len(self._games)

    @property
    def selected_game_index(self) -> int:
        return self._selected

    @property
    def cursor(self) -> GameTreeCursor:
        return self._cursor

    @property
    def content_revision(self) -> int:
        return self._revision

    def games(self):
        return self._games

    def view(self):
        return SimpleNamespace(
            dirty=False,
            current_record_digest="a" * 64,
        )

    def set_cursor(self, cursor: GameTreeCursor):
        self._cursor = cursor
        self.set_cursor_calls.append(cursor)
        return self.view()

    def previous_game(self):
        if self._selected == 0:
            raise ValueError("first game")
        self._selected -= 1
        self._cursor = GameTreeCursor()
        return self.view()

    def next_game(self):
        if self._selected + 1 >= len(self._games):
            raise ValueError("last game")
        self._selected += 1
        self._cursor = GameTreeCursor()
        return self.view()


class PgnWorkspaceWebViewAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = _Workspace()
        self.calls: list[tuple[str, dict[str, object]]] = []

        def dispatch(action_id: str, payload):
            self.calls.append((action_id, dict(payload)))
            return {"private": "C:/Users/private/export.pgn", "token": "SECRET"}

        self.projection = PgnWorkspaceWebViewProjection(
            self.workspace,
            dispatch,
            language=UILanguage.EN,
        )
        self.bridge = PgnWebViewBridge(self.projection)

    def test_snapshot_is_canonical_workspace_synchronized_without_private_authority(self) -> None:
        snapshot = self.projection.snapshot()
        self.assertEqual(2, snapshot["game"]["count"])
        self.assertEqual(7, snapshot["workspace"]["content_revision"])
        self.assertFalse(snapshot["workspace"]["dirty"])
        serialized = repr(snapshot)
        self.assertNotIn("current_record_digest", serialized)
        self.assertNotIn("line_path", serialized)
        self.assertNotIn("expected_record_digest", serialized)

    def test_browser_selection_updates_canonical_workspace_cursor(self) -> None:
        snapshot = self.projection.snapshot()
        second = snapshot["tree"][1]
        event = self.bridge.dispatch("pgn.select", {"node_id": second["node_id"]})
        self.assertEqual("selection", event.kind)
        self.assertEqual(2, self.workspace.cursor.next_move_index)
        self.assertEqual((), self.workspace.cursor.line_path)
        self.assertEqual(self.workspace.cursor, self.workspace.set_cursor_calls[-1])

    def test_variation_action_gets_trusted_workspace_target_but_browser_does_not(self) -> None:
        variation = next(item for item in self.projection.snapshot()["tree"] if item["kind"] == "variation")
        selected = self.bridge.dispatch("pgn.select", {"node_id": variation["node_id"]})
        self.assertEqual("selection", selected.kind)
        event = self.bridge.dispatch("pgn.variation_promote", {})
        self.assertEqual("selection", event.kind)
        action_id, payload = self.calls[-1]
        self.assertEqual("pgn.variation_promote", action_id)
        self.assertEqual("a" * 64, payload["expected_record_digest"])
        self.assertEqual(7, payload["content_revision"])
        self.assertEqual(0, payload["variation_index"])
        self.assertEqual(1, payload["parent_move_index"])
        browser_payload = repr(event.payload)
        self.assertNotIn("expected_record_digest", browser_payload)
        self.assertNotIn("line_path", browser_payload)
        self.assertNotIn("SECRET", browser_payload)
        self.assertNotIn("C:/Users/private", browser_payload)

    def test_comment_text_is_only_browser_edit_payload_and_host_target_is_enriched(self) -> None:
        first = self.projection.snapshot()["tree"][0]
        self.bridge.dispatch("pgn.select", {"node_id": first["node_id"]})
        event = self.bridge.dispatch("pgn.comment_edit", {"text": "Accessible note"})
        self.assertEqual("selection", event.kind)
        action_id, payload = self.calls[-1]
        self.assertEqual("pgn.comment_edit", action_id)
        self.assertEqual("Accessible note", payload["text"])
        self.assertEqual(0, payload["move_index"])
        self.assertEqual((), payload["line_path"])
        self.assertEqual("a" * 64, payload["expected_record_digest"])

    def test_game_navigation_is_owned_by_workspace_not_presenter_copy(self) -> None:
        event = self.bridge.dispatch("pgn.next_game", {})
        self.assertEqual("selection", event.kind)
        self.assertEqual(1, self.workspace.selected_game_index)
        self.assertEqual(1, event.payload["snapshot"]["game"]["index"])
        back = self.bridge.dispatch("pgn.previous_game", {})
        self.assertEqual(0, self.workspace.selected_game_index)
        self.assertEqual(0, back.payload["snapshot"]["game"]["index"])

    def test_forged_browser_node_fails_closed_without_cursor_mutation(self) -> None:
        before = self.workspace.cursor
        event = self.bridge.dispatch("pgn.select", {"node_id": "g0:main/m999999"})
        self.assertEqual("error", event.kind)
        self.assertEqual(before, self.workspace.cursor)
        self.assertEqual([], self.workspace.set_cursor_calls)


if __name__ == "__main__":
    unittest.main()
