from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import acs.stage1_release_ui as release_ui


class _Runtime:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class Stage1ResourceErrorPrivacyTests(unittest.TestCase):
    def test_missing_packaged_html_does_not_expose_local_resource_path(self) -> None:
        runtime = _Runtime()
        fake_webview = types.ModuleType("webview")
        with tempfile.TemporaryDirectory(prefix="oleksii-private-build-") as td:
            root = Path(td) / "user profile" / "Accessible Chess"
            root.mkdir(parents=True)
            with mock.patch.dict(sys.modules, {"webview": fake_webview}):
                with mock.patch.object(release_ui, "_asset_root", return_value=root):
                    with self.assertRaises(RuntimeError) as caught:
                        release_ui.run_release_window(object(), runtime)
            message = str(caught.exception)
            self.assertEqual(message, "Accessible HTML UI not found in packaged resources.")
            self.assertNotIn(str(root), message)
            self.assertNotIn(td, message)
        self.assertEqual(runtime.closed, 1)

    def test_missing_board_bridge_keeps_resource_failure_path_private(self) -> None:
        runtime = _Runtime()
        fake_webview = types.ModuleType("webview")
        with tempfile.TemporaryDirectory(prefix="secret-build-root-") as td:
            root = Path(td)
            (root / "web").mkdir()
            (root / "web" / "index.html").write_text("<html></html>", encoding="utf-8")
            (root / "web" / "stage1_release_bootstrap.js").write_text("(() => {})();", encoding="utf-8")
            with mock.patch.dict(sys.modules, {"webview": fake_webview}):
                with mock.patch.object(release_ui, "_asset_root", return_value=root):
                    with self.assertRaises(RuntimeError) as caught:
                        release_ui.run_release_window(object(), runtime)
            message = str(caught.exception)
            self.assertEqual(message, "Stage 1 board action bridge not found in packaged resources.")
            self.assertNotIn(str(root), message)
            self.assertNotIn(td, message)
        self.assertEqual(runtime.closed, 1)


if __name__ == "__main__":
    unittest.main()
