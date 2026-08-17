from __future__ import annotations

import unittest
from pathlib import Path

from acs.webview2_accessibility import (
    FORCE_RENDERER_ACCESSIBILITY,
    WEBVIEW2_BROWSER_ARGUMENTS_ENV,
    enable_webview2_renderer_accessibility,
)


class Stage1WebView2AccessibilityBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def test_force_renderer_accessibility_is_added_once_and_preserves_existing_arguments(self) -> None:
        env = {WEBVIEW2_BROWSER_ARGUMENTS_ENV: "--disable-features=ElasticOverscroll --foo=bar"}
        first = enable_webview2_renderer_accessibility(env)
        second = enable_webview2_renderer_accessibility(env)
        self.assertIn("--disable-features=ElasticOverscroll", first)
        self.assertIn("--foo=bar", first)
        self.assertEqual(first.count(FORCE_RENDERER_ACCESSIBILITY), 1)
        self.assertEqual(second, first)

    def test_existing_force_renderer_accessibility_variant_is_not_duplicated(self) -> None:
        env = {WEBVIEW2_BROWSER_ARGUMENTS_ENV: "--force-renderer-accessibility=complete --foo=bar"}
        result = enable_webview2_renderer_accessibility(env)
        self.assertEqual(result, "--force-renderer-accessibility=complete --foo=bar")

    def test_packaged_launcher_enables_accessibility_before_importing_stage1_webview_entrypoint(self) -> None:
        launcher = (self.root / "run_accessible_chess.py").read_text(encoding="utf-8")
        enable_index = launcher.index("enable_webview2_renderer_accessibility()")
        stage1_import_index = launcher.index("from acs.stage1_release_ui import main")
        self.assertLess(enable_index, stage1_import_index)
        self.assertNotIn("import webview", launcher[:enable_index])

    def test_boundary_does_not_create_native_or_hidden_proxy_move_controls(self) -> None:
        boundary = (self.root / "acs" / "webview2_accessibility.py").read_text(encoding="utf-8")
        launcher = (self.root / "run_accessible_chess.py").read_text(encoding="utf-8")
        text = boundary + "\n" + launcher
        self.assertNotIn("TextBox(", text)
        self.assertNotIn("CreateWindow", text)
        self.assertNotIn("move-input-proxy", text)
        self.assertNotIn("aria-hidden", text)


if __name__ == "__main__":
    unittest.main()
