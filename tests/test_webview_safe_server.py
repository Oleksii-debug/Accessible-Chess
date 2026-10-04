from __future__ import annotations

import unittest
from pathlib import Path

from acs.webview_safe_server import (
    CHROMIUM_RESTRICTED_PORTS,
    STAGE1_WEBVIEW_SAFE_PORTS,
    choose_chromium_safe_loopback_port,
    install_pywebview_safe_local_server_port,
    validate_chromium_safe_port,
)


class _FakeWebview:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def start(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return "started"


class WebViewSafeServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def test_observed_chromium_blocked_port_6666_is_rejected(self) -> None:
        self.assertIn(6666, CHROMIUM_RESTRICTED_PORTS)
        with self.assertRaises(ValueError):
            validate_chromium_safe_port(6666)

    def test_stage1_vetted_ports_are_all_chromium_safe(self) -> None:
        self.assertGreaterEqual(len(STAGE1_WEBVIEW_SAFE_PORTS), 8)
        self.assertEqual(STAGE1_WEBVIEW_SAFE_PORTS[0], 42001)
        for port in STAGE1_WEBVIEW_SAFE_PORTS:
            self.assertEqual(validate_chromium_safe_port(port), port)
            self.assertNotIn(port, CHROMIUM_RESTRICTED_PORTS)

    def test_selector_skips_forced_blocked_port_and_uses_first_safe_available(self) -> None:
        chosen = choose_chromium_safe_loopback_port(
            (6666, 42001, 42002),
            availability_probe=lambda port: True,
        )
        self.assertEqual(chosen, 42001)

    def test_selector_skips_busy_safe_port_without_random_fallback(self) -> None:
        chosen = choose_chromium_safe_loopback_port(
            (42001, 42002, 42003),
            availability_probe=lambda port: port == 42003,
        )
        self.assertEqual(chosen, 42003)

    def test_selector_fails_closed_when_no_vetted_port_is_available(self) -> None:
        with self.assertRaises(RuntimeError):
            choose_chromium_safe_loopback_port(
                (6666, 42001),
                availability_probe=lambda port: False,
            )

    def test_installed_guard_overrides_keyword_unsafe_port(self) -> None:
        fake = _FakeWebview()
        self.assertTrue(
            install_pywebview_safe_local_server_port(
                fake,
                port_selector=lambda: 42001,
            )
        )
        self.assertEqual(fake.start(gui="edgechromium", private_mode=True, http_port=6666), "started")
        _args, kwargs = fake.calls[-1]
        self.assertEqual(kwargs["http_port"], 42001)
        self.assertNotEqual(kwargs["http_port"], 6666)

    def test_installed_guard_overrides_positional_unsafe_port(self) -> None:
        fake = _FakeWebview()
        install_pywebview_safe_local_server_port(fake, port_selector=lambda: 42002)
        fake.start(None, None, {}, "edgechromium", False, False, 6666)
        args, kwargs = fake.calls[-1]
        self.assertEqual(args[6], 42002)
        self.assertNotIn("http_port", kwargs)

    def test_install_is_idempotent_and_does_not_stack_wrappers(self) -> None:
        fake = _FakeWebview()
        install_pywebview_safe_local_server_port(fake, port_selector=lambda: 42001)
        first_wrapper = fake.start
        self.assertTrue(install_pywebview_safe_local_server_port(fake, port_selector=lambda: 42002))
        self.assertIs(fake.start, first_wrapper)
        fake.start(gui="edgechromium")
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0][1]["http_port"], 42001)

    def test_packaged_launcher_installs_safe_server_before_stage1_main(self) -> None:
        launcher = (self.root / "run_accessible_chess.py").read_text(encoding="utf-8")
        install_import = "from acs.webview_safe_server import install_pywebview_safe_local_server_port"
        install_call = "install_pywebview_safe_local_server_port()"
        main_import = "from acs.stage1_release_ui import main"
        self.assertIn(install_import, launcher)
        self.assertIn(install_call, launcher)
        self.assertIn(main_import, launcher)
        self.assertLess(launcher.index(install_call), launcher.index(main_import))
        self.assertNotIn("explicitly-allowed-ports", launcher)
        self.assertNotIn("ERR_UNSAFE_PORT", launcher)


if __name__ == "__main__":
    unittest.main()
