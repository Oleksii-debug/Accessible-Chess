from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Version2AccessibilityConvergenceTests(unittest.TestCase):
    """Behavioral DOM convergence across the #462 -> #543 -> #560 W4 stack."""

    def _run_node_oracle(self, relative_path: str) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for Version 2 behavioral DOM acceptance")
        script = ROOT / relative_path
        completed = subprocess.run(
            [node, str(script)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            f"{relative_path} failed.\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )

    def test_broad_focus_landmark_and_incremental_event_contract(self) -> None:
        self._run_node_oracle("tests/js/version2_release_bootstrap_dom_test.js")

    def test_library_open_refreshes_to_canonical_pgn_surface(self) -> None:
        self._run_node_oracle("tests/js/version2_library_open_route_refresh_dom_test.js")

    def test_library_progress_preserves_typed_filters_and_focus(self) -> None:
        self._run_node_oracle("tests/js/version2_library_progress_filter_preservation_dom_test.js")


if __name__ == "__main__":
    unittest.main()
