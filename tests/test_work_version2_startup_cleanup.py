from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI, run_version2_release_window
from tests.test_version2_release_ui import _Application


class _CreateWindowFailureWebView:
    def create_window(self, *_args, **_kwargs):
        raise RuntimeError("synthetic native window creation failure")

    def start(self, **_kwargs):
        raise AssertionError("start must not run after create_window failure")


class _Runtime:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class Version2StartupCleanupEvidenceTests(unittest.TestCase):
    """Release lifecycle must close owned state even before WebView start succeeds."""

    def test_create_window_failure_closes_application_and_engine_runtime(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        api = Version2ReleaseAccessibleChessAPI(keymap_path=Path(temp.name) / "keymap.json")
        application = _Application()
        runtime = _Runtime()

        with self.assertRaisesRegex(RuntimeError, "synthetic native window creation failure"):
            run_version2_release_window(
                api,
                application,
                runtime,
                webview_module=_CreateWindowFailureWebView(),
                menu_installer=lambda *_: True,
            )

        self.assertTrue(
            application.closed,
            "V2 create_window failure escaped before application.shutdown(), leaving shared state open",
        )
        self.assertEqual(
            runtime.closed,
            1,
            "V2 create_window failure escaped before the owned engine runtime was closed",
        )


if __name__ == "__main__":
    unittest.main()
