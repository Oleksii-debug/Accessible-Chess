from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "d06-file-ingress-nag-normalization.yml"
CURRENT_PRODUCT_BRANCH = "work/full-product-teacher-education-reachability-20260911"


class D06FileIngressNagNormalizationWorkflowTests(unittest.TestCase):
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
            "tests/test_d06_file_ingress_nag_normalization.py",
            "tests/test_d06_file_ingress_nag_normalization_workflow.py",
            ".github/workflows/d06-file-ingress-nag-normalization.yml",
        )
        for block in (push, pull):
            self.assertIn("paths:", block)
            for path in required:
                with self.subTest(path=path):
                    self.assertIn(path, block)

    def test_historical_owner_scope_is_not_used_as_candidate_geometry(self) -> None:
        self.assertNotIn("D06_INGRESS_BASE", self.workflow)
        self.assertNotIn("d706eb93b9a4df3c6e99ab1af584a9cfe6b6f5ea", self.workflow)
        self.assertNotIn('changed="$(git diff --name-only', self.workflow)
        self.assertNotIn('test "$changed" = "$expected"', self.workflow)
        self.assertNotIn("Prove exact base and narrow scope", self.workflow)

    def test_live_pr_base_and_exact_push_geometry_are_required(self) -> None:
        self.assertIn("fetch-depth: 0", self.workflow)
        self.assertIn(
            "ref: ${{ github.event.pull_request.head.sha || github.sha }}",
            self.workflow,
        )
        self.assertIn(
            "PR_BASE_REF: ${{ github.event.pull_request.base.ref }}",
            self.workflow,
        )
        self.assertIn(
            "PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            self.workflow,
        )
        self.assertIn("PUSH_BASE_SHA: ${{ github.event.before }}", self.workflow)
        self.assertIn('if test -n "${PR_BASE_REF:-}"; then', self.workflow)
        self.assertIn(
            'git fetch --no-tags origin "+refs/heads/$PR_BASE_REF:refs/remotes/origin/$PR_BASE_REF"',
            self.workflow,
        )
        self.assertIn(
            'live_base="$(git rev-parse "refs/remotes/origin/$PR_BASE_REF")"',
            self.workflow,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$live_base" HEAD',
            self.workflow,
        )
        self.assertIn('base="$live_base"', self.workflow)
        self.assertIn('base="$PR_BASE_SHA"', self.workflow)
        self.assertIn('base="${PUSH_BASE_SHA:-}"', self.workflow)
        self.assertIn('base="$(git rev-parse HEAD^)"', self.workflow)
        self.assertIn('git cat-file -e "$base^{commit}"', self.workflow)
        self.assertIn('git merge-base --is-ancestor "$base" HEAD', self.workflow)
        self.assertIn('test "$(git merge-base "$base" HEAD)" = "$base"', self.workflow)
        self.assertIn('git diff --check "$base" HEAD', self.workflow)
        self.assertIn("PR head is stale against live base", self.workflow)

    def test_non_ingress_semantic_surfaces_remain_fenced_from_candidate_delta(self) -> None:
        fence = 'git diff --quiet "$base" HEAD -- ' + "\\\n"
        self.assertIn(fence, self.workflow)
        for path in (
            "acs/gametree.py",
            "acs/pgn_roundtrip.py",
            "acs/pgn_document.py",
            "web",
            "run_accessible_chess.py",
        ):
            with self.subTest(path=path):
                self.assertIn(path, self.workflow)

    def test_frozen_stage1_and_dual_os_fences_remain_exact(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.workflow)
        self.assertIn("b8586a26b9ab20c3d3ec0b0a3dbbbd53e38e94e6", self.workflow)
        self.assertIn("0ba06f548d39dad7372e0339b3e121fd1717cc05", self.workflow)
        self.assertIn("pytest==8.4.2", self.workflow)

    def test_nag_adjacent_full_suite_and_diagnostics_remain_required(self) -> None:
        required = (
            "tests.test_d06_file_ingress_nag_normalization",
            "tests.test_d06_file_ingress_nag_normalization_workflow",
            "tests.test_d06_pgn_roundtrip",
            "tests.test_pgn_service",
            "tests.test_pgn_document",
            "tests.test_pgn_workspace",
            "tests.test_dev4_pgn_resource_security",
            "tests.test_dev4_pgn_encoding_quality",
            "tests.test_dev4_pgn_truncation_quality",
            "tests.test_dev4_pgn_export_path_security",
            "tests.test_dev4_pgn_export_concurrency_security",
            "tests.test_dev4_pgn_export_failure_recovery",
            "tests.test_dev4_pgn_postcommit_cleanup_atomicity",
        )
        for suite in required:
            with self.subTest(suite=suite):
                self.assertIn(suite, self.workflow)
        self.assertIn("python -m unittest discover -s tests", self.workflow)
        self.assertIn("python -m pytest -q tests", self.workflow)
        self.assertIn("python -m acs.selftest", self.workflow)
        self.assertIn("python run_accessible_chess.py --diagnostic", self.workflow)


if __name__ == "__main__":
    unittest.main()
