from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.version2_release_app import _share_v2_action_registry
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI
from tests.test_version2_release_ui import _Application


class Version2RemappedKeyboardRoutingTests(unittest.TestCase):
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

        self.assertTrue(result.get("ok"))
        self.assertEqual(self.application.shell.current_route.route_id, "library")

    def test_release_key_handler_resolves_v2_contexts_and_uses_v2_dispatch(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
        bootstrap = (Path(__file__).resolve().parents[1] / "web" / "version2_release_bootstrap.js").read_text(encoding="utf-8")
        self.assertIn("keymap_resolve_binding", source)
        self.assertIn("dispatch_action", source)
        self.assertIn("v2_browser_command", source)
        self.assertIn("accessibleChessV2KeymapContext", bootstrap)

        has_v2_context = any(
            f"resolveBinding(chord,'{context}'" in source
            for context in ("global", "database", "book_reader")
        )
        self.assertTrue(has_v2_context)


if __name__ == "__main__":
    unittest.main()
