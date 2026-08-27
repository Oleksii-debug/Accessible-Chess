from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import acs.stage1_release_ui as release_ui
import acs.stage1_release_ui_core as release_core
import acs.webapp_keymap as keymap_ui
import acs.webapp_keymap_core as keymap_core
from acs.release_app import ReleaseAccessibleChessAPI


ROOT = Path(__file__).resolve().parents[1]


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


class _Event:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self) -> None:
        for handler in tuple(self.handlers):
            handler()


class _FakeWindow:
    def __init__(self) -> None:
        self.events = types.SimpleNamespace(before_show=_Event(), loaded=_Event())
        self.evaluated: list[str] = []

    def evaluate_js(self, source: str) -> None:
        self.evaluated.append(source)


class _FakeWebview(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("webview")
        self.window = _FakeWindow()
        self.start_calls: list[tuple[str, bool]] = []
        self.create_calls = []

    def create_window(self, *args, **kwargs):
        self.create_calls.append((args, kwargs))
        return self.window

    def start(self, *, gui: str, private_mode: bool) -> None:
        self.start_calls.append((gui, private_mode))
        self.window.events.before_show.fire()
        self.window.events.loaded.fire()


class _Api:
    def __init__(self) -> None:
        self.closed = 0

    def close_analysis(self):
        self.closed += 1
        return {"ok": True}


class _Runtime:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class Stage1SaturationRefactorContractTests(unittest.TestCase):
    def test_extracted_core_files_are_byte_identical_to_frozen_git_blobs(self) -> None:
        self.assertEqual(
            _git_blob_sha(ROOT / "acs" / "stage1_release_ui_core.py"),
            "b8586a26b9ab20c3d3ec0b0a3dbbbd53e38e94e6",
        )
        self.assertEqual(
            _git_blob_sha(ROOT / "acs" / "webapp_keymap_core.py"),
            "0ba06f548d39dad7372e0339b3e121fd1717cc05",
        )

    def test_facades_preserve_frozen_public_import_surface(self) -> None:
        for facade, core in ((release_ui, release_core), (keymap_ui, keymap_core)):
            with self.subTest(facade=facade.__name__):
                public_core = {name for name in vars(core) if not name.startswith("_")}
                missing = sorted(public_core - set(vars(facade)))
                self.assertEqual(missing, [])

        self.assertIs(ReleaseAccessibleChessAPI, release_ui.Stage1ReleaseAccessibleChessAPI)
        self.assertIs(release_ui._asset_root, release_core._asset_root)
        self.assertIs(release_ui._shared_spoken_san, release_core._shared_spoken_san)
        self.assertIs(keymap_ui._asset_root, keymap_core._asset_root)
        self.assertIs(keymap_ui._shared_spoken_san, keymap_core._shared_spoken_san)

    def test_private_symbols_imported_by_product_or_tests_still_exist(self) -> None:
        module_map = {
            "acs.stage1_release_ui": release_ui,
            "acs.webapp_keymap": keymap_ui,
        }
        missing: list[str] = []
        for root in (ROOT / "acs", ROOT / "tests"):
            for path in root.rglob("*.py"):
                if path.name in {"stage1_release_ui.py", "webapp_keymap.py"}:
                    continue
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if not isinstance(node, ast.ImportFrom) or node.module not in module_map:
                        continue
                    for alias in node.names:
                        if alias.name.startswith("_") and not hasattr(module_map[node.module], alias.name):
                            missing.append(f"{path.relative_to(ROOT)}:{node.module}.{alias.name}")
        self.assertEqual(missing, [])

    def test_subclass_mro_is_single_linear_chain_with_saturation_before_frozen_core(self) -> None:
        release_mro = release_ui.Stage1ReleaseAccessibleChessAPI.__mro__
        self.assertEqual(release_mro[1], release_core.Stage1ReleaseAccessibleChessAPI)
        self.assertLess(release_mro.index(keymap_ui.KeymapAwareAccessibleChessAPI), release_mro.index(keymap_core.KeymapAwareAccessibleChessAPI))
        self.assertEqual(
            keymap_ui.KeymapAwareAccessibleChessAPI.__mro__[1],
            keymap_core.KeymapAwareAccessibleChessAPI,
        )
        self.assertEqual(len(release_mro), len(set(release_mro)))
        self.assertEqual(len(keymap_ui.KeymapAwareAccessibleChessAPI.__mro__), len(set(keymap_ui.KeymapAwareAccessibleChessAPI.__mro__)))

    def test_affected_modules_cold_import_in_fresh_processes(self) -> None:
        orders = (
            ("acs.stage1_release_ui", "acs.webapp_keymap"),
            ("acs.webapp_keymap", "acs.stage1_release_ui"),
            ("acs.stage1_release_ui_core", "acs.stage1_release_ui"),
            ("acs.webapp_keymap_core", "acs.webapp_keymap"),
            ("acs.release_app", "acs.stage1_release_ui", "acs.webapp_keymap"),
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        for order in orders:
            code = ";".join(f"import {name}" for name in order)
            code += ";from acs.release_app import ReleaseAccessibleChessAPI;from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI;assert ReleaseAccessibleChessAPI is Stage1ReleaseAccessibleChessAPI"
            with self.subTest(order=order):
                run = subprocess.run(
                    [sys.executable, "-c", code],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_core_modules_are_static_imports_visible_to_packager(self) -> None:
        release_source = (ROOT / "acs" / "stage1_release_ui.py").read_text(encoding="utf-8")
        keymap_source = (ROOT / "acs" / "webapp_keymap.py").read_text(encoding="utf-8")
        launcher = (ROOT / "run_accessible_chess.py").read_text(encoding="utf-8")
        composition = (ROOT / "acs" / "release_app.py").read_text(encoding="utf-8")
        self.assertIn("from . import stage1_release_ui_core as _core", release_source)
        self.assertIn("from . import webapp_keymap_core as _core", keymap_source)
        self.assertNotIn("importlib.import_module", release_source + keymap_source)
        self.assertNotIn("__import__(", release_source + keymap_source)
        self.assertIn("from acs.stage1_release_ui import main", launcher)
        self.assertIn("from .stage1_release_ui import Stage1ReleaseAccessibleChessAPI", composition)

    def test_run_release_window_executes_real_bootstrap_then_board_bridge(self) -> None:
        fake_webview = _FakeWebview()
        api = _Api()
        runtime = _Runtime()
        with mock.patch.dict(sys.modules, {"webview": fake_webview}):
            with mock.patch.object(release_ui, "install_windows_native_menu", return_value=True):
                release_ui.run_release_window(api, runtime)

        self.assertEqual(fake_webview.start_calls, [("edgechromium", True)])
        self.assertEqual(len(fake_webview.window.evaluated), 2)
        self.assertIn("__accessibleChessStage1ReleaseBootstrap", fake_webview.window.evaluated[0])
        self.assertIn("__accessibleChessStage1BoardActions", fake_webview.window.evaluated[1])
        self.assertEqual(api.closed, 1)
        self.assertEqual(runtime.closed, 1)

    def test_missing_board_bridge_fails_before_window_creation_and_closes_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "web").mkdir()
            (root / "web" / "index.html").write_text("<html></html>", encoding="utf-8")
            (root / "web" / "stage1_release_bootstrap.js").write_text("(() => {})();", encoding="utf-8")
            fake_webview = _FakeWebview()
            api = _Api()
            runtime = _Runtime()
            with mock.patch.dict(sys.modules, {"webview": fake_webview}):
                with mock.patch.object(release_ui, "_asset_root", return_value=root):
                    with self.assertRaisesRegex(RuntimeError, "Stage 1 board action bridge not found"):
                        release_ui.run_release_window(api, runtime)
            self.assertEqual(fake_webview.create_calls, [])
            self.assertEqual(api.closed, 0)
            self.assertEqual(runtime.closed, 1)


if __name__ == "__main__":
    unittest.main()
