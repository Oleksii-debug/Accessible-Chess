from __future__ import annotations

from types import SimpleNamespace
import unittest

from acs.webview2_accessibility import (
    FORCE_RENDERER_ACCESSIBILITY,
    WEBVIEW2_BROWSER_ARGUMENTS_ENV,
    enable_webview2_renderer_accessibility,
    install_pywebview_accessibility_host_patch,
)


class WebViewBridgeSecurityTests(unittest.TestCase):
    def test_benign_browser_arguments_survive_and_accessibility_flag_is_idempotent(self) -> None:
        env = {
            WEBVIEW2_BROWSER_ARGUMENTS_ENV:
                "--disable-features=ElasticOverscroll --foo=bar"
        }
        first = enable_webview2_renderer_accessibility(env)
        second = enable_webview2_renderer_accessibility(env)
        self.assertIn("--disable-features=ElasticOverscroll", first)
        self.assertIn("--foo=bar", first)
        self.assertEqual(first.count(FORCE_RENDERER_ACCESSIBILITY), 1)
        self.assertEqual(second, first)

    def test_remote_debugging_and_security_disable_switches_are_removed(self) -> None:
        env = {
            WEBVIEW2_BROWSER_ARGUMENTS_ENV: (
                "--remote-debugging-port=9222 "
                "--remote-debugging-address 0.0.0.0 "
                "--remote-allow-origins=* "
                "--disable-web-security "
                "--allow-running-insecure-content "
                "--allow-file-access-from-files "
                "--allow-universal-access-from-files "
                "--ignore-certificate-errors "
                "--no-sandbox "
                "--disable-site-isolation-trials "
                "--foo=bar"
            )
        }
        value = enable_webview2_renderer_accessibility(env)
        self.assertNotIn("remote-debugging", value)
        self.assertNotIn("remote-allow-origins", value)
        self.assertNotIn("0.0.0.0", value)
        self.assertNotIn("--disable-web-security", value)
        self.assertNotIn("--allow-running-insecure-content", value)
        self.assertNotIn("--allow-file-access-from-files", value)
        self.assertNotIn("--allow-universal-access-from-files", value)
        self.assertNotIn("--ignore-certificate-errors", value)
        self.assertNotIn("--no-sandbox", value)
        self.assertNotIn("--disable-site-isolation-trials", value)
        self.assertIn("--foo=bar", value)
        self.assertIn(FORCE_RENDERER_ACCESSIBILITY, value)

    def test_split_remote_debugging_port_does_not_leave_orphan_scalar(self) -> None:
        env = {WEBVIEW2_BROWSER_ARGUMENTS_ENV: "--remote-debugging-port 9222 --foo=bar"}
        value = enable_webview2_renderer_accessibility(env)
        self.assertNotIn("remote-debugging-port", value)
        self.assertNotIn("9222", value)
        self.assertIn("--foo=bar", value)

    def test_incompatible_edge_runtime_without_ready_callback_fails_closed(self) -> None:
        class EdgeChrome:
            pass

        module = SimpleNamespace(EdgeChrome=EdgeChrome)
        self.assertFalse(install_pywebview_accessibility_host_patch(module))
        self.assertFalse(hasattr(EdgeChrome, "_acs_stage1_accessibility_host_patched"))


if __name__ == "__main__":
    unittest.main()
