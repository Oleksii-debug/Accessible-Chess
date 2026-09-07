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

    @staticmethod
    def _script_has_v2_keyboard_bridge(source: str) -> bool:
        """Accept a real JS keyboard bridge without prescribing its exact layout."""
        return (
            "keydown" in source
            and "keymap_resolve_binding" in source
            and "v2_browser_command" in source
        )

    def test_remapped_v2_global_action_has_an_executable_keyboard_bridge(self) -> None:
        registry = self.application.adapter.registry
        registry.set_binding("screen.library", "Ctrl+Alt+L", allow_warnings=True)
        resolved = self.api.keymap_resolve_binding("global", "Ctrl+Alt+L")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["actionId"], "screen.library")
        self.assertEqual(self.application.shell.current_route.route_id, "board")

        # Two architectures are valid and keep one command authority:
        # 1. the inherited keyboard fallback reaches an API-level V2 bridge; or
        # 2. the V2 release script intercepts the resolved binding and invokes the
        #    existing V2 browser-command bridge.  The evidence must not force one.
        api_bridge = False
        try:
            result = self.api.dispatch_action(resolved["actionId"])
            api_bridge = bool(result.get("ok")) and self.application.shell.current_route.route_id == "library"
        except Exception:
            api_bridge = False

        root = Path(__file__).resolve().parents[1]
        index_source = (root / "web" / "index.html").read_text(encoding="utf-8")
        v2_source = (root / "web" / "version2_release_bootstrap.js").read_text(encoding="utf-8")
        js_bridge = self._script_has_v2_keyboard_bridge(index_source) or self._script_has_v2_keyboard_bridge(v2_source)

        self.assertTrue(
            api_bridge or js_bridge,
            "The shared V2 keymap can resolve a real V2 action, but the release has no "
            "executable keyboard bridge from that binding to the V2 application router",
        )

    def test_v2_only_binding_context_is_not_left_outside_the_keyboard_path(self) -> None:
        root = Path(__file__).resolve().parents[1]
        index_source = (root / "web" / "index.html").read_text(encoding="utf-8")
        v2_source = (root / "web" / "version2_release_bootstrap.js").read_text(encoding="utf-8")

        # An API-level V2 bridge may let the inherited handler stay small, but in
        # that architecture the handler still needs to resolve the V2-only GLOBAL
        # context.  A dedicated V2 JS keyboard bridge may instead own both context
        # resolution and dispatch.  Either is acceptable.
        explicit_v2_script_bridge = self._script_has_v2_keyboard_bridge(v2_source)
        inherited_script_extended = (
            "'global'" in index_source or '"global"' in index_source
        ) and "keymap_resolve_binding" in index_source

        self.assertTrue(
            explicit_v2_script_bridge or inherited_script_extended,
            "Version 2 publishes remappable GLOBAL actions, but no active release keyboard "
            "path resolves that V2-only binding context",
        )


if __name__ == "__main__":
    unittest.main()
