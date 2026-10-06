from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class P0DynamicSelectionPartialReplacementTests(unittest.TestCase):
    def test_real_education_partial_replacement_preserves_selection(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is unavailable")
        script = ROOT / "tests" / "js" / "p0_accessibility_partial_replacement_test.js"
        subprocess.run(
            [node, "--check", str(script)],
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
        self.assertIn(
            "P0_DYNAMIC_SELECTION_V2_EDUCATION_PARTIAL=PASS",
            completed.stdout,
        )


if __name__ == "__main__":
    unittest.main()
