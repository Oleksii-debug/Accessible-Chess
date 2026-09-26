from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class P0DynamicSelectionActionDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = (ROOT / "web" / "p0_accessibility_runtime.js").read_text(encoding="utf-8")
        cls.index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        cls.final_release = (ROOT / "acs" / "version2_education_mutation_release.py").read_text(encoding="utf-8")

    def test_shipping_final_product_loads_p0_runtime_last(self) -> None:
        bootstrap_marker = '("V2 final-product bootstrap", root / "version2_final_product_bootstrap.js")'
        runtime_marker = '("P0 accessibility runtime", root / "p0_accessibility_runtime.js")'
        self.assertIn(bootstrap_marker, self.final_release)
        self.assertIn(runtime_marker, self.final_release)
        self.assertGreater(self.final_release.index(runtime_marker), self.final_release.index(bootstrap_marker))

    def test_dynamic_selection_guard_is_route_and_text_bounded(self) -> None:
        self.assertIn('new global.MutationObserver', self.runtime)
        self.assertIn('retainedSelection.route !== routeToken()', self.runtime)
        self.assertIn('indexOf(retainedSelection.text) < 0', self.runtime)
        self.assertIn('rootForNode(range.startContainer)', self.runtime)
        self.assertIn('rootForNode(range.endContainer) !== root', self.runtime)
        self.assertIn('restoreSemanticSelection(retainedSelection)', self.runtime)
        self.assertNotIn('Node.prototype', self.runtime)
        self.assertNotIn('Element.prototype.replaceChildren', self.runtime)
        self.assertNotIn('navigator.clipboard', self.runtime)
        self.assertNotIn('execCommand', self.runtime)

    def test_stage1_polling_and_v2_local_mutations_share_the_runtime_guard(self) -> None:
        self.assertIn("setInterval(refreshAnalysis,700)", self.index)
        self.assertIn("setText('engine-status',s.engineStatus)", self.index)
        self.assertIn('observer.observe(main, { subtree: true, childList: true, characterData: true })', self.runtime)
        self.assertIn('observer.observe(workspace, { subtree: true, childList: true, characterData: true })', self.runtime)

    def test_action_result_delivery_reuses_single_existing_live_region(self) -> None:
        self.assertIn('documentRef.getElementById("live")', self.runtime)
        self.assertNotIn('createElement("div")', self.runtime)
        self.assertIn('const announcementQueue = []', self.runtime)
        self.assertIn('const rememberedDispatchMessages = new Set()', self.runtime)
        self.assertIn('const recentPassiveAnnouncements = new Map()', self.runtime)
        self.assertIn('const MAX_REMEMBERED_DISPATCH_MESSAGES = 256', self.runtime)
        self.assertIn('const MAX_REMEMBERED_PASSIVE_ANNOUNCEMENTS = 256', self.runtime)
        self.assertIn('const dispatchId = "surface:" + String(++dispatchCounter)', self.runtime)
        self.assertIn('const dispatchId = "api:" + String(++dispatchCounter)', self.runtime)
        self.assertIn('if (rememberDispatchMessage(dispatch, text)) return false', self.runtime)

    def _run_node_oracle(self, node: str, script: Path, pass_marker: str) -> None:
        completed = subprocess.run(
            [node, str(script)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=(
                f"Node oracle failed: {script.name}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            ),
        )
        self.assertIn(pass_marker, completed.stdout)

    def test_runtime_parses_and_repeated_action_oracle_passes(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is unavailable")
        syntax = subprocess.run(
            [node, "--check", str(ROOT / "web" / "p0_accessibility_runtime.js")],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            syntax.returncode,
            0,
            msg=f"P0 runtime syntax check failed:\n{syntax.stdout}\n{syntax.stderr}",
        )
        self._run_node_oracle(
            node,
            ROOT / "tests" / "js" / "p0_accessibility_runtime_test.js",
            "P0_ACCESSIBILITY_RUNTIME_ACTION_DELIVERY=PASS",
        )
        self._run_node_oracle(
            node,
            ROOT / "tests" / "js" / "p0_dynamic_selection_runtime_test.js",
            "P0_DYNAMIC_SELECTION_EXECUTABLE_ORACLE=PASS",
        )


if __name__ == "__main__":
    unittest.main()
