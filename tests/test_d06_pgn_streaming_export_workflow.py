from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "d06-pgn-streaming-export.yml"
CURRENT_PRODUCT_BRANCH = "work/full-product-teacher-education-reachability-20260911"


class D06PgnStreamingExportWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def _trigger_blocks(self) -> tuple[str, str]:
        push_start = self.workflow.index("  push:\n")
        pull_start = self.workflow.index("  pull_request:\n")
        dispatch_start = self.workflow.index("  workflow_dispatch:\n", pull_start)
        return (
            self.workflow[push_start:pull_start],
            self.workflow[pull_start:dispatch_start],
        )

    def test_current_product_push_and_stacked_prs_are_qualified(self) -> None:
        push, pull = self._trigger_blocks()
        self.assertIn(CURRENT_PRODUCT_BRANCH, push)
        self.assertNotIn("branches:", pull)
        required = (
            "acs/pgn_service.py",
            "tests/test_v2_pgn_streaming_export.py",
            "tests/test_d06_pgn_streaming_export_workflow.py",
            ".github/workflows/d06-pgn-streaming-export.yml",
        )
        for block in (push, pull):
            self.assertIn("paths:", block)
            for path in required:
                with self.subTest(path=path):
                    self.assertIn(path, block)

    def test_historical_authority_and_whole_descendant_allowlist_are_removed(self) -> None:
        self.assertNotIn("V2_AUTHORITY:", self.workflow)
        self.assertNotIn("575ec0088982d2f90adb47c040a5714d68186b0e", self.workflow)
        self.assertNotIn('changed="$(git diff --name-only', self.workflow)
        self.assertNotIn('test "$changed" = "$expected"', self.workflow)

    def test_exact_event_geometry_and_checkout_are_required(self) -> None:
        self.assertIn("fetch-depth: 0", self.workflow)
        self.assertIn(
            "ref: ${{ github.event.pull_request.head.sha || github.sha }}",
            self.workflow,
        )
        self.assertIn(
            "PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            self.workflow,
        )
        self.assertIn("PUSH_BASE_SHA: ${{ github.event.before }}", self.workflow)
        self.assertIn('base="${PR_BASE_SHA:-}"', self.workflow)
        self.assertIn('base="${PUSH_BASE_SHA:-}"', self.workflow)
        self.assertIn('base="$(git rev-parse HEAD^)"', self.workflow)
        self.assertIn('git cat-file -e "$base^{commit}"', self.workflow)
        self.assertIn('git merge-base --is-ancestor "$base" HEAD', self.workflow)
        self.assertIn('test "$(git merge-base "$base" HEAD)" = "$base"', self.workflow)
        self.assertIn('git diff --check "$base" HEAD', self.workflow)

    def test_stage1_and_release_contamination_fence_uses_event_base(self) -> None:
        self.assertIn('git diff --name-only "$base" HEAD', self.workflow)
        self.assertIn("(^|/)tools/qa/", self.workflow)
        self.assertIn("windows-stage1", self.workflow)
        self.assertIn("release_preflight", self.workflow)
        self.assertIn("stage1_release", self.workflow)
        self.assertIn("Stage1 or release contamination detected in candidate delta", self.workflow)

    def test_dual_os_and_export_regressions_remain_required(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.workflow)
        required = (
            "tests.test_v2_pgn_streaming_export",
            "tests.test_d06_pgn_streaming_export_workflow",
            "tests.test_pgn_service",
            "tests.test_pgn_concurrent_save",
            "tests.test_dev4_pgn_export_path_security",
            "tests.test_dev4_pgn_export_concurrency_security",
            "tests.test_dev4_pgn_export_failure_recovery",
            "tests.test_dev4_pgn_postcommit_cleanup_atomicity",
            "tests.test_dev4_pgn_resource_security",
        )
        for suite in required:
            with self.subTest(suite=suite):
                self.assertIn(suite, self.workflow)


if __name__ == "__main__":
    unittest.main()
