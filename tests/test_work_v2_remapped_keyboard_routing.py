from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.version2_release_app import _share_v2_action_registry
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI
from tests.test_version2_release_ui import _Application


class Version2RemappedKeyboardRoutingEvidenceTests(unittest.TestCase):
    """The one V2 ActionRegistry must remain executable from keyboard resolution."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.api = Version2ReleaseAccessibleChessAPI(
            keymap_path=Path(self.temp.name) / "keymap.json"
        )
        self.application = _Application()
        _share_v2_action_registry(self.api, self.application)
        self.api.bind_version2_application(self.application)

    def test_remapped_v2_global_action_executes_through_same_application_router(self) -> None:
        registry = self.application.adapter.registry
        registry.set_binding("screen.library", "Ctrl+Alt+L", allow_warnings=True)
        resolved = self.api.keymap_resolve_binding("global", "Ctrl+Alt+L")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["actionId"], "screen.library")
        self.assertEqual(self.application.shell.current_route.route_id, "board")

        result = self.api.dispatch_action(resolved["actionId"])

        self.assertTrue(
            result.get("ok"),
            "The shared V2 keymap resolved a real V2 action, but the keyboard fallback "
            "sent it to the Stage1-only dispatch_action path and returned unavailable",
        )
        self.assertEqual(
            self.application.shell.current_route.route_id,
            "library",
            "A remapped V2 route shortcut must converge on the same V2 application router as UI/native menu actions",
        )

    def test_stage1_document_key_handler_routes_unhandled_actions_to_v2_not_stage1_only_dispatch(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("keymap_resolve_binding", source)
        self.assertIn("dispatch_action", source)
        self.assertIn("v2_browser_command", (Path(__file__).resolve().parents[1] / "web" / "version2_release_bootstrap.js").read_text(encoding="utf-8"))

        # A V2 release key handler must include the V2 registry contexts or hand the
        # resolved action back to the V2 router. The inherited Stage1 handler only
        # resolves analysis/history/document and then calls Stage1 dispatch_action.
        has_v2_context = any(
            f"resolveBinding(chord,'{context}'" in source
            for context in ("global", "database", "book_reader")
        )
        has_v2_keyboard_dispatch = "v2_browser_command" in source
        self.assertTrue(
            has_v2_context and has_v2_keyboard_dispatch,
            "Version 2 publishes remappable global/database/book actions but the inherited keyboard handler neither resolves their contexts nor dispatches them through the V2 router",
        )


if __name__ == "__main__":
    unittest.main()
