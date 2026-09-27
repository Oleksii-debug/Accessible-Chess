from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class P0PollingTextStabilityTests(unittest.TestCase):
    def test_shipping_analysis_poll_keeps_unchanged_text_nodes(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is unavailable")
        completed = subprocess.run(
            [node, str(ROOT / "tests" / "js" / "p0_polling_text_stability_test.js")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("P0_POLLING_TEXT_NODES_STABLE=PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
