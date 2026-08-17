from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from acs.webview2_accessibility import (
    FORCE_RENDERER_ACCESSIBILITY,
    WEBVIEW2_BROWSER_ARGUMENTS_ENV,
    enable_webview2_renderer_accessibility,
    install_pywebview_accessibility_host_patch,
    repair_edgechromium_accessibility_host,
)


class _Event:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class _Controller:
    def __init__(self) -> None:
        self.notifications = 0

    def NotifyParentWindowPositionChanged(self) -> None:
        self.notifications += 1


class _Host:
    def __init__(self) -> None:
        self.LocationChanged = _Event()
        self.SizeChanged = _Event()


class _Control:
    def __init__(self, host) -> None:
        self._host = host
        self.TabStop = False

    def FindForm(self):
        return self._host


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

    def test_host_repair_targets_actual_find_form_and_notifies_controller(self) -> None:
        host = _Host()
        control = _Control(host)
        controller = _Controller()
        edge = SimpleNamespace(form=host, webview=control)
        with patch("acs.webview2_accessibility._find_core_controller", return_value=controller):
            state = repair_edgechromium_accessibility_host(edge)
        self.assertTrue(state["same_host"])
        self.assertTrue(state["controller"])
        self.assertTrue(state["notified"])
        self.assertTrue(control.TabStop)
        self.assertEqual(controller.notifications, 1)
        self.assertEqual(len(host.LocationChanged.handlers), 1)
        self.assertEqual(len(host.SizeChanged.handlers), 1)
        host.LocationChanged.handlers[0]()
        self.assertEqual(controller.notifications, 2)

    def test_host_repair_fails_closed_for_detached_webview(self) -> None:
        host = _Host()
        control = _Control(_Host())
        edge = SimpleNamespace(form=host, webview=control)
        state = repair_edgechromium_accessibility_host(edge)
        self.assertFalse(state["same_host"])
        self.assertFalse(state["controller"])

    def test_pywebview_patch_runs_after_real_edge_ready_callback(self) -> None:
        calls = []

        class EdgeChrome:
            def on_webview_ready(self, sender, args):
                calls.append("original")

        module = SimpleNamespace(EdgeChrome=EdgeChrome)
        with patch("acs.webview2_accessibility.repair_edgechromium_accessibility_host", return_value={"notified": True}) as repair:
            self.assertTrue(install_pywebview_accessibility_host_patch(module))
            edge = EdgeChrome()
            edge.on_webview_ready(None, None)
        self.assertEqual(calls, ["original"])
        repair.assert_called_once_with(edge)
        self.assertEqual(edge._acs_stage1_accessibility_host_state, {"notified": True})

    def test_packaged_launcher_installs_host_patch_before_stage1_entrypoint(self) -> None:
        launcher = (self.root / "run_accessible_chess.py").read_text(encoding="utf-8")
        enable_index = launcher.index("enable_webview2_renderer_accessibility()")
        patch_index = launcher.index("install_pywebview_accessibility_host_patch()")
        stage1_import_index = launcher.index("from acs.stage1_release_ui import main")
        self.assertLess(enable_index, patch_index)
        self.assertLess(patch_index, stage1_import_index)

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
