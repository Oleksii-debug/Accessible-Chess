from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Stage1P0SemanticSelectionBackportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        cls.release = (ROOT / "acs" / "stage1_release_ui.py").read_text(encoding="utf-8")
        cls.runtime = (ROOT / "web" / "p0_accessibility_runtime.js").read_text(encoding="utf-8")

    def test_stage1_shipping_window_keeps_native_text_selection(self) -> None:
        self.assertIn("text_select=True", self.release)
        self.assertNotRegex(self.index, r"(?i)user-select\s*:\s*none")

    def test_plain_ctrl_c_and_existing_selection_return_before_keymap_dispatch(self) -> None:
        start = self.index.index("document.addEventListener('keydown',async e=>{if(capture)return;")
        end = self.index.index("\nel('move-submit').addEventListener", start)
        handler = self.index[start:end]
        ctrl_c = "if(e.ctrlKey&&!e.altKey&&!e.shiftKey&&String(e.key).toLowerCase()==='c')return;"
        selection = (
            "const selection=window.getSelection&&window.getSelection();"
            "if(e.ctrlKey&&!e.altKey&&selection&&selection.toString())return;"
        )
        resolve = "const chord=eventChord(e);"
        prevent = "if(a){e.preventDefault();executeAction(a.actionId)}"
        self.assertLess(handler.index(ctrl_c), handler.index(selection))
        self.assertLess(handler.index(selection), handler.index(resolve))
        self.assertLess(handler.index(resolve), handler.index(prevent))
        self.assertNotIn("preventDefault", handler[: handler.index(ctrl_c)])

    def test_backport_is_the_accepted_shared_runtime_not_a_second_clipboard_system(self) -> None:
        self.assertIn('new global.MutationObserver', self.runtime)
        self.assertIn('documentRef.addEventListener("selectionchange", rememberSelection)', self.runtime)
        self.assertIn('restoreSemanticSelection(retainedSelection)', self.runtime)
        self.assertIn('return current && current.id ? String(current.id) : "stage1";', self.runtime)
        self.assertNotIn("navigator.clipboard", self.runtime)
        self.assertNotIn("execCommand", self.runtime)
        self.assertNotIn("Node.prototype", self.runtime)
        self.assertNotIn("Element.prototype.replaceChildren =", self.runtime)

    def test_stage1_composes_shared_runtime_last(self) -> None:
        bootstrap = "window.evaluate_js(bootstrap_source)"
        board = "window.evaluate_js(board_bridge_source)"
        p0 = "window.evaluate_js(p0_accessibility_source)"
        self.assertIn('p0_accessibility = _asset_root() / "web" / "p0_accessibility_runtime.js"', self.release)
        self.assertLess(self.release.index(bootstrap), self.release.index(board))
        self.assertLess(self.release.index(board), self.release.index(p0))

    def test_actual_refresh_analysis_preserves_surviving_selection(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is unavailable")
        script = ROOT / "tests" / "js" / "stage1_p0_dynamic_selection_runtime_test.js"
        subprocess.run(
            [node, "--check", str(ROOT / "web" / "p0_accessibility_runtime.js")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        completed = subprocess.run(
            [node, str(script)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("P0_STAGE1_REFRESH_SELECTION_SURVIVES=PASS", completed.stdout)
        self.assertIn("P0_STAGE1_DYNAMIC_SELECTION_EXECUTABLE_ORACLE=PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
