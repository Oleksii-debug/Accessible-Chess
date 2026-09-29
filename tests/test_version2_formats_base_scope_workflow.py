from __future__ import annotations

from pathlib import Path
import unittest


class Version2FormatsBaseScopeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "version2-formats-integration.yml"
        ).read_text(encoding="utf-8")

    def test_pull_request_uses_exact_github_base_and_head(self) -> None:
        self.assertIn(
            "expected='${{ github.event.pull_request.head.sha || github.sha }}'",
            self.workflow,
        )
        self.assertIn(
            'test "$(git rev-parse HEAD)" = "$expected"',
            self.workflow,
        )
        self.assertIn(
            "if [ '${{ github.event_name }}' = 'pull_request' ]; then",
            self.workflow,
        )
        self.assertIn(
            "BASE_SHA='${{ github.event.pull_request.base.sha }}'",
            self.workflow,
        )

    def test_push_retains_first_parent_fallback_only_inside_event_branch(self) -> None:
        marker = "if [ '${{ github.event_name }}' = 'pull_request' ]; then"
        start = self.workflow.index(marker)
        end = self.workflow.index("\n          fi", start)
        branch = self.workflow[start:end]
        self.assertIn("else", branch)
        self.assertIn('BASE_SHA="$(git rev-parse HEAD^1)"', branch)
        self.assertEqual(self.workflow.count('BASE_SHA="$(git rev-parse HEAD^1)"'), 1)

    def test_full_pr_geometry_requires_exact_base_ancestry(self) -> None:
        self.assertIn('git merge-base --is-ancestor "$BASE_SHA" HEAD', self.workflow)
        self.assertIn(
            'test "$(git merge-base "$BASE_SHA" HEAD)" = "$BASE_SHA"',
            self.workflow,
        )
        self.assertIn('git diff --check "$BASE_SHA" HEAD', self.workflow)
        self.assertIn(
            'changed="$(git diff --name-only "$BASE_SHA" HEAD | sort)"',
            self.workflow,
        )

    def test_existing_release_seam_and_nullmove_authorities_remain(self) -> None:
        self.assertIn("CANONICAL_NULLMOVE_CHESSCORE_BLOB:", self.workflow)
        self.assertIn("CANONICAL_NULLMOVE_DECODER_BLOB:", self.workflow)
        self.assertIn("Unreviewed chesscore drift in Formats candidate", self.workflow)
        self.assertIn("Protected release seam drift:", self.workflow)
        self.assertIn("acs/stage1_release_ui.py", self.workflow)
        self.assertIn("web/stage1_release_bootstrap.js", self.workflow)

    def test_contract_test_is_triggered_and_executed(self) -> None:
        self.assertIn(
            "- 'tests/test_version2_formats_base_scope_workflow.py'",
            self.workflow,
        )
        self.assertIn(
            "tests.test_version2_formats_base_scope_workflow",
            self.workflow,
        )

    def test_dual_os_full_suite_and_real_evidence_remain(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.workflow)
        self.assertIn("real-pinned-chessbase:", self.workflow)
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)
        self.assertIn("python -m pytest -q tests", self.workflow)
        self.assertIn("python -m acs.selftest", self.workflow)
        self.assertIn("python run_accessible_chess.py --diagnostic", self.workflow)


if __name__ == "__main__":
    unittest.main()
