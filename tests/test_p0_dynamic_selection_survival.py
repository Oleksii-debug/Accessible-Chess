from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class P0DynamicSelectionSurvivalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = (ROOT / "web" / "p0_accessibility_runtime.js").read_text(encoding="utf-8")
        cls.stage1 = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        cls.pgn = (ROOT / "web" / "full_product_pgn.js").read_text(encoding="utf-8")
        cls.teacher = (ROOT / "web" / "full_product_teacher.js").read_text(encoding="utf-8")
        cls.release = (ROOT / "acs" / "version2_education_mutation_release.py").read_text(
            encoding="utf-8"
        )

    def test_stage1_shipping_polling_uses_dynamic_text_mutation(self) -> None:
        self.assertIn("function refreshAnalysis()", self.stage1)
        self.assertIn("setInterval(refreshAnalysis,700)", self.stage1)
        self.assertIn("function setText(id,text)", self.stage1)
        self.assertIn(".textContent", self.stage1)

    def test_shipping_v2_local_replacement_paths_are_observed(self) -> None:
        self.assertIn("root.replaceChildren", self.pgn)
        self.assertIn("previous.replaceWith(replacement)", self.teacher)
        self.assertIn('observer.observe(main, { subtree: true, childList: true, characterData: true })', self.runtime)
        self.assertIn(
            'observer.observe(workspace, { subtree: true, childList: true, characterData: true })',
            self.runtime,
        )

    def test_shipping_composition_loads_preservation_runtime_after_bootstrap(self) -> None:
        bootstrap = '("V2 final-product bootstrap", root / "version2_final_product_bootstrap.js")'
        runtime = '("P0 accessibility runtime", root / "p0_accessibility_runtime.js")'
        self.assertIn(bootstrap, self.release)
        self.assertIn(runtime, self.release)
        self.assertGreater(self.release.index(runtime), self.release.index(bootstrap))

    def test_executable_dynamic_selection_oracle_passes(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is unavailable")
        subprocess.run(
            [node, "--check", str(ROOT / "tests" / "js" / "p0_dynamic_selection_survival_test.js")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        completed = subprocess.run(
            [node, str(ROOT / "tests" / "js" / "p0_dynamic_selection_survival_test.js")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("P0_DYNAMIC_SELECTION_SURVIVAL=PASS", completed.stdout)

    def test_preservation_runtime_does_not_replace_native_clipboard(self) -> None:
        self.assertNotIn("navigator.clipboard", self.runtime)
        self.assertNotIn("execCommand", self.runtime)
        self.assertNotIn("preventDefault", self.runtime)


if __name__ == "__main__":
    unittest.main()
