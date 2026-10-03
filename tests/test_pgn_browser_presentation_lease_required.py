from __future__ import annotations

import unittest

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


class PgnBrowserPresentationLeaseRequiredTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = PgnDocumentSession.from_text(DOCUMENT)
        commands = Version2PgnCommands(lambda: self.session)
        router = FullProductActionRouter(
            AccessibleShellState(language=UILanguage.EN),
            commands,
        )
        self.projection = PgnWorkspaceWebViewProjection(
            self.session.workspace,
            router,
            language=UILanguage.EN,
        )
        self.bridge = PgnWebViewBridge(self.projection)

    def test_missing_lease_rejects_current_browser_navigation(self) -> None:
        visible = self.projection.snapshot()
        self.assertEqual(0, self.session.workspace.selected_game_index)

        rejected = self.bridge.dispatch("pgn.next_game", {})

        self.assertEqual("selection", rejected.kind)
        self.assertEqual(0, self.session.workspace.selected_game_index)
        snapshot = rejected.payload["snapshot"]
        self.assertEqual(0, snapshot["game"]["index"])
        self.assertEqual(snapshot["error_message"], rejected.payload["announcement"])
        self.assertEqual(visible["presentation_token"], snapshot["presentation_token"])

    def test_hidden_host_snapshot_does_not_make_tokenless_stale_intent_authoritative(self) -> None:
        visible = self.projection.snapshot()
        old_token = visible["presentation_token"]

        # A host-side path changes canonical state and refreshes the projection,
        # but the old WebView DOM has not rendered this newer presentation.
        self.session.workspace.next_game()
        hidden = self.projection.snapshot()
        self.assertEqual(1, hidden["game"]["index"])
        self.assertNotEqual(old_token, hidden["presentation_token"])

        rejected = self.bridge.dispatch("pgn.previous_game", {})

        self.assertEqual("selection", rejected.kind)
        self.assertEqual(1, self.session.workspace.selected_game_index)
        snapshot = rejected.payload["snapshot"]
        self.assertEqual(1, snapshot["game"]["index"])
        self.assertEqual(snapshot["error_message"], rejected.payload["announcement"])

    def test_matching_rendered_lease_still_allows_navigation(self) -> None:
        visible = self.projection.snapshot()

        accepted = self.bridge.dispatch(
            "pgn.next_game",
            {"presentation_token": visible["presentation_token"]},
        )

        self.assertEqual("selection", accepted.kind)
        self.assertEqual(1, self.session.workspace.selected_game_index)
        self.assertEqual(1, accepted.payload["snapshot"]["game"]["index"])

    def test_refresh_remains_token_free_recovery_path(self) -> None:
        refreshed = self.bridge.dispatch("pgn.refresh", {})

        self.assertEqual("selection", refreshed.kind)
        self.assertEqual("ready", refreshed.payload["snapshot"]["status"])
        self.assertEqual(0, self.session.workspace.selected_game_index)
        self.assertRegex(
            refreshed.payload["snapshot"]["presentation_token"],
            r"^[0-9a-f]{64}$",
        )


if __name__ == "__main__":
    unittest.main()
