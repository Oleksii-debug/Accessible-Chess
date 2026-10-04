from __future__ import annotations

from types import SimpleNamespace
import unittest

from acs.full_product_actions import FullProductActionRouter
from acs.full_product_ui_shell import AccessibleShellState, UILanguage
from acs.gametree import parse_games
from acs.gametree_navigation import GameTreeCursor, VariationStep
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
        self._content_digest = "b" * 64
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
            game_count=self.game_count,
            selected_game_index=self.selected_game_index,
            cursor=self.cursor,
            dirty=False,
            content_revision=self.content_revision,
            content_digest=self._content_digest,
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
        self.dispatch_entry_cursor_calls: list[int] = []

        def dispatch(action_id: str, payload):
            trusted = dict(payload)
            self.dispatch_entry_cursor_calls.append(len(self.workspace.set_cursor_calls))
            self.calls.append((action_id, trusted))
            if action_id in {
                "pgn.select_item",
                "pgn.previous_item",
                "pgn.next_item",
                "pgn.parent_variation",
            }:
                path = tuple(VariationStep(*item) for item in trusted["line_path"])
                move_index = trusted["move_index"]
                cursor = GameTreeCursor(path, 0 if move_index is None else move_index + 1)
                self.workspace.set_cursor(cursor)
            elif action_id == "pgn.previous_game":
                self.workspace.previous_game()
            elif action_id == "pgn.next_game":
                self.workspace.next_game()
            return {"private": "C:/Users/private/export.pgn", "token": "SECRET"}

        self.router = FullProductActionRouter(
            AccessibleShellState(language=UILanguage.EN),
            dispatch,
        )
        self.projection = PgnWorkspaceWebViewProjection(
            self.workspace,
            self.router,
            language=UILanguage.EN,
        )
        self.bridge = PgnWebViewBridge(self.projection)

    def test_snapshot_is_canonical_workspace_synchronized_without_private_authority(self) -> None:
        snapshot = self.projection.snapshot()
        self.assertEqual(2, snapshot["game"]["count"])
        self.assertFalse(snapshot["workspace"]["dirty"])
        serialized = repr(snapshot)
        self.assertNotIn("content_revision", serialized)
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
        self.assertEqual("pgn.select_item", self.calls[-1][0])
        self.assertEqual(0, self.dispatch_entry_cursor_calls[-1])

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

    def test_keyboard_and_parent_navigation_cross_real_registry_exactly_once(self) -> None:
        self.projection.snapshot()
        down = self.bridge.dispatch("pgn.move", {"delta": 1})
        self.assertEqual("selection", down.kind)
        self.assertEqual("pgn.next_item", self.calls[-1][0])
        self.assertEqual(1, sum(action == "pgn.next_item" for action, _ in self.calls))

        variation = next(
            item for item in self.projection.snapshot()["tree"] if item["kind"] == "variation"
        )
        self.bridge.dispatch("pgn.select", {"node_id": variation["node_id"]})
        parent = self.bridge.dispatch("pgn.parent", {})
        self.assertEqual("selection", parent.kind)
        self.assertEqual("pgn.parent_variation", self.calls[-1][0])
        self.assertEqual(1, sum(action == "pgn.parent_variation" for action, _ in self.calls))

    def test_game_navigation_is_owned_by_workspace_not_presenter_copy(self) -> None:
        event = self.bridge.dispatch("pgn.next_game", {})
        self.assertEqual("selection", event.kind)
        self.assertEqual(1, self.workspace.selected_game_index)
        self.assertEqual(1, event.payload["snapshot"]["game"]["index"])
        back = self.bridge.dispatch("pgn.previous_game", {})
        self.assertEqual(0, self.workspace.selected_game_index)
        self.assertEqual(0, back.payload["snapshot"]["game"]["index"])
        self.assertEqual(
            ["pgn.next_game", "pgn.previous_game"],
            [action for action, _ in self.calls[-2:]],
        )

    def test_forged_browser_node_fails_closed_without_cursor_mutation(self) -> None:
        before = self.workspace.cursor
        event = self.bridge.dispatch("pgn.select", {"node_id": "g0:main/m999999"})
        self.assertEqual("error", event.kind)
        self.assertEqual(before, self.workspace.cursor)
        self.assertEqual([], self.workspace.set_cursor_calls)

    def test_browser_authority_fields_cannot_override_trusted_workspace_identity(self) -> None:
        node_id = self.projection.snapshot()["tree"][0]["node_id"]
        self.bridge.dispatch("pgn.select", {"node_id": node_id})
        call_count = len(self.calls)
        with self.assertRaises(ValueError):
            self.projection._trusted_dispatch(
                "pgn.comment_edit",
                {
                    "node_id": node_id,
                    "text": "safe",
                    "content_revision": 999,
                },
            )
        self.assertEqual(call_count, len(self.calls))

    def test_workspace_drift_during_snapshot_fails_closed(self) -> None:
        class MutatingWorkspace(_Workspace):
            def games(self):
                games = super().games()
                self._revision += 1
                return games

        workspace = MutatingWorkspace()
        router = FullProductActionRouter(AccessibleShellState(), lambda _action, _payload: None)
        with self.assertRaisesRegex(ValueError, "changed while creating"):
            PgnWorkspaceWebViewProjection(workspace, router, language=UILanguage.EN)

    def test_full_document_digest_drift_during_snapshot_fails_closed(self) -> None:
        class MutatingWorkspace(_Workspace):
            def games(self):
                games = super().games()
                self._content_digest = "c" * 64
                return games

        workspace = MutatingWorkspace()
        router = FullProductActionRouter(AccessibleShellState(), lambda _action, _payload: None)
        with self.assertRaisesRegex(ValueError, "changed while creating"):
            PgnWorkspaceWebViewProjection(workspace, router, language=UILanguage.EN)


if __name__ == "__main__":
    unittest.main()
