from __future__ import annotations

import unittest
from unittest.mock import patch

from acs.full_product_actions import FullProductActionRouter
from acs.full_product_ui_shell import AccessibleShellState, UILanguage
from acs.pgn_document import PgnDocumentSession
from acs.pgn_webview_bridge import PgnWebViewBridge
from acs.pgn_workspace_webview_adapter import PgnWorkspaceWebViewProjection
from acs.version2_pgn_commands import Version2PgnCommands


DOCUMENT = '''[Event "One"]
[Result "*"]

1. e4 e5 *

[Event "Two"]
[Result "*"]

1. d4 d5 *
'''


class CurrentPgnPostCommitPresentationRecoveryTests(unittest.TestCase):
    def _surface(self):
        session = PgnDocumentSession.from_text(DOCUMENT)
        commands = Version2PgnCommands(lambda: session)
        router = FullProductActionRouter(
            AccessibleShellState(language=UILanguage.EN),
            commands,
        )
        projection = PgnWorkspaceWebViewProjection(
            session.workspace,
            router,
            language=UILanguage.EN,
        )
        return session, projection, PgnWebViewBridge(projection)

    @staticmethod
    def _fail_after_preflight(projection):
        real_capture = projection._capture_presenter
        calls = {"count": 0}

        def capture(language):
            calls["count"] += 1
            if calls["count"] == 1:
                return real_capture(language)
            raise ValueError("C:/Users/private/post-commit-refresh.pgn")

        return capture

    def test_committed_game_navigation_clears_stale_tree_then_refreshes_truthfully(self):
        session, projection, bridge = self._surface()
        visible = projection.snapshot()
        self.assertEqual(0, visible["game"]["index"])
        presentation_token = visible["presentation_token"]

        with patch.object(
            projection,
            "_capture_presenter",
            side_effect=self._fail_after_preflight(projection),
        ):
            unavailable = bridge.dispatch(
                "pgn.next_game",
                {"presentation_token": presentation_token},
            )

        self.assertEqual(1, session.workspace.selected_game_index)
        self.assertEqual("selection", unavailable.kind)
        snapshot = unavailable.payload["snapshot"]
        self.assertEqual("unavailable", snapshot["status"])
        self.assertEqual("pgn-refresh-view", snapshot["focus_target"])
        self.assertEqual((), snapshot["tree"])
        self.assertEqual((), snapshot["actions"])
        self.assertNotIn("post-commit-refresh", repr(unavailable.payload))
        self.assertNotIn("C:/Users/private", repr(unavailable.payload))

        # The browser can have a delayed command already queued against the lease
        # it rendered before the canonical commit. Even though the failed capture
        # left that old presenter identity in memory, the adapter must compare the
        # live workspace before mutation, resync, and reject the stale intent.
        rejected_stale = bridge.dispatch(
            "pgn.previous_game",
            {"presentation_token": presentation_token},
        )
        self.assertEqual(1, session.workspace.selected_game_index)
        self.assertEqual("selection", rejected_stale.kind)
        self.assertEqual("ready", rejected_stale.payload["snapshot"]["status"])
        self.assertEqual(1, rejected_stale.payload["snapshot"]["game"]["index"])
        self.assertNotEqual(
            presentation_token,
            rejected_stale.payload["snapshot"]["presentation_token"],
        )

        recovered = bridge.dispatch("pgn.refresh", {})
        self.assertEqual("selection", recovered.kind)
        self.assertEqual("ready", recovered.payload["snapshot"]["status"])
        self.assertEqual(1, recovered.payload["snapshot"]["game"]["index"])

    def test_committed_comment_survives_failed_render_and_refreshes_exact_text(self):
        session, projection, bridge = self._surface()
        visible = projection.snapshot()
        first = visible["tree"][0]
        selected = bridge.dispatch(
            "pgn.select",
            {
                "node_id": first["node_id"],
                "presentation_token": visible["presentation_token"],
            },
        )
        self.assertEqual("selection", selected.kind)
        selected_token = selected.payload["snapshot"]["presentation_token"]
        before_revision = session.workspace.content_revision

        with patch.object(
            projection,
            "_capture_presenter",
            side_effect=self._fail_after_preflight(projection),
        ):
            unavailable = bridge.dispatch(
                "pgn.comment_edit",
                {
                    "text": "Durable canonical note",
                    "presentation_token": selected_token,
                },
            )

        self.assertEqual(before_revision + 1, session.workspace.content_revision)
        self.assertIn("Durable canonical note", session.workspace.to_text())
        self.assertEqual("selection", unavailable.kind)
        self.assertEqual("unavailable", unavailable.payload["snapshot"]["status"])
        self.assertEqual((), unavailable.payload["snapshot"]["tree"])

        recovered = bridge.dispatch("pgn.refresh", {})
        self.assertEqual("selection", recovered.kind)
        self.assertEqual("ready", recovered.payload["snapshot"]["status"])
        self.assertEqual(
            "Durable canonical note",
            recovered.payload["snapshot"]["comment_editor"]["value"],
        )

    def test_preflight_capture_failure_never_mutates_canonical_game(self):
        session, projection, bridge = self._surface()
        visible = projection.snapshot()
        before = session.workspace.view()

        with patch.object(
            projection,
            "_capture_presenter",
            side_effect=ValueError("preflight drift"),
        ):
            unavailable = bridge.dispatch(
                "pgn.next_game",
                {"presentation_token": visible["presentation_token"]},
            )

        self.assertEqual(before, session.workspace.view())
        self.assertEqual("selection", unavailable.kind)
        self.assertEqual("unavailable", unavailable.payload["snapshot"]["status"])


if __name__ == "__main__":
    unittest.main()
