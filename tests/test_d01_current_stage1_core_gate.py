from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "d01-pgn-workspace-webview.yml"


class D01CurrentStage1CoreGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_stage1_core_acceptance_is_exact_blob_based_not_branch_named(self) -> None:
        self.assertIn(
            "b8586a26b9ab20c3d3ec0b0a3dbbbd53e38e94e6|"
            "b579ca0f59ba20f6b69b3a4b7d89589256d54852",
            self.workflow,
        )
        self.assertIn(
            "Protected blob mismatch: acs/stage1_release_ui_core.py",
            self.workflow,
        )
        self.assertNotIn(
            "integration/clock-engine-serial-intake-20261002",
            self.workflow,
        )
        self.assertNotIn(
            "github.event.pull_request.head.ref",
            self.workflow,
        )

    def test_regression_is_triggered_and_runs_in_focused_gate(self) -> None:
        self.assertIn(
            "- 'tests/test_d01_current_stage1_core_gate.py'",
            self.workflow,
        )
        self.assertIn(
            "tests.test_d01_current_stage1_core_gate",
            self.workflow,
        )


if __name__ == "__main__":
    unittest.main()
