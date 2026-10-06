"""Regression contract for retained architecture workflow supersession."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "architecture-dynamic-import-gate.yml",
    ROOT / ".github" / "workflows" / "architecture-dynamic-import-alias-gate.yml",
    ROOT / ".github" / "workflows" / "architecture-dynamic-infrastructure-import-gate.yml",
)
CONCURRENCY_BLOCK = """concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.head.repo.full_name || github.repository }}-${{ github.head_ref || github.ref_name }}
  cancel-in-progress: true
"""
TRIGGER_PATH = "      - 'tests/test_architecture_workflow_concurrency.py'"
TEST_MODULE = "tests.test_architecture_workflow_concurrency"


class ArchitectureWorkflowConcurrencyTests(unittest.TestCase):
    def test_retained_architecture_workflows_cancel_superseded_runs(self) -> None:
        for workflow in WORKFLOWS:
            with self.subTest(workflow=workflow.name):
                text = workflow.read_text(encoding="utf-8")
                self.assertIn(CONCURRENCY_BLOCK, text)
                self.assertEqual(text.count(TRIGGER_PATH), 2)
                self.assertIn(TEST_MODULE, text)

    def test_concurrency_group_isolated_by_workflow_repository_and_head(self) -> None:
        for workflow in WORKFLOWS:
            with self.subTest(workflow=workflow.name):
                text = workflow.read_text(encoding="utf-8")
                self.assertIn("${{ github.workflow }}", text)
                self.assertIn(
                    "${{ github.event.pull_request.head.repo.full_name || github.repository }}",
                    text,
                )
                self.assertIn("${{ github.head_ref || github.ref_name }}", text)
                self.assertIn("cancel-in-progress: true", text)


if __name__ == "__main__":
    unittest.main()
