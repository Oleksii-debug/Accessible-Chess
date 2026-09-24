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

    def test_action_result_delivery_reuses_single_existing_live_region(self) -> None:
        self.assertIn('documentRef.getElementById("live")', self.runtime)
        self.assertNotIn('createElement("div")', self.runtime)
        self.assertIn('const announcementQueue = []', self.runtime)
        self.assertIn('dispatchId = ++dispatchCounter', self.runtime)
        self.assertIn('dispatch === lastAnnouncementDispatch', self.runtime)

    def test_runtime_parses_and_repeated_action_oracle_passes(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is unavailable")
        subprocess.run(
            [node, "--check", str(ROOT / "web" / "p0_accessibility_runtime.js")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        completed = subprocess.run(
            [node, str(ROOT / "tests" / "js" / "p0_accessibility_runtime_test.js")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("P0_ACCESSIBILITY_RUNTIME_ACTION_DELIVERY=PASS", completed.stdout)

    def test_dynamic_selection_mutation_oracle_passes(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is unavailable")
        completed = subprocess.run(
            [node, str(ROOT / "tests" / "js" / "p0_dynamic_selection_preservation_test.js")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("P0_DYNAMIC_SELECTION_PRESERVATION=PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
