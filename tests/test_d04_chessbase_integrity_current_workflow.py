from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "d04-chessbase-integrity-handle-identity.yml"
CURRENT_PRODUCT_BRANCH = "work/full-product-teacher-education-reachability-20260911"
INTEGRITY_BLOB = "c08f0869f996d4ec428a90c64e9846374a720562"


class D04ChessbaseIntegrityCurrentWorkflowTests(unittest.TestCase):
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
            ".github/workflows/d04-chessbase-integrity-handle-identity.yml",
            "acs/chessbase_integrity.py",
            "acs/import_contract.py",
            "tests/test_d04_chessbase_integrity_handle_identity.py",
            "tests/test_dev4_chessbase_integrity_atomicity.py",
            "tests/test_dev4_chessbase_integrity_io_observability.py",
            "tests/test_d04_chessbase_integrity_current_workflow.py",
        )
        for block in (push, pull):
            self.assertIn("paths:", block)
            for path in required:
                with self.subTest(path=path):
                    self.assertIn(path, block)

    def test_historical_dependency_and_test_blob_pins_are_not_candidate_geometry(self) -> None:
        self.assertNotIn("D04_OWNER:", self.workflow)
        self.assertNotIn("IMPORT_CONTRACT_BLOB:", self.workflow)
        self.assertNotIn("HANDLE_IDENTITY_TEST_BLOB:", self.workflow)
        self.assertNotIn("ATOMICITY_TEST_BLOB:", self.workflow)
        self.assertNotIn("IO_OBSERVABILITY_TEST_BLOB:", self.workflow)
        self.assertNotIn(
            'test "$(git merge-base HEAD "$D04_OWNER")" = "$D04_OWNER"',
            self.workflow,
        )

    def test_retained_d04_integrity_source_fence_remains_exact(self) -> None:
        self.assertIn(f"INTEGRITY_BLOB: {INTEGRITY_BLOB}", self.workflow)
        self.assertIn(
            'test "$(git rev-parse HEAD:acs/chessbase_integrity.py)" = "$INTEGRITY_BLOB"',
            self.workflow,
        )
        self.assertIn("D04_INTEGRITY_SOURCE_BLOB=$INTEGRITY_BLOB", self.workflow)

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

    def test_dual_os_and_pinned_verification_remain_required(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.workflow)
        self.assertIn("pytest==8.4.2", self.workflow)
        self.assertIn("python-version: '3.12'", self.workflow)

    def test_integrity_regressions_full_suite_and_diagnostics_remain_required(self) -> None:
        required = (
            "tests.test_d04_chessbase_integrity_handle_identity",
            "tests.test_dev4_chessbase_integrity_atomicity",
            "tests.test_dev4_chessbase_integrity_io_observability",
            "tests.test_d04_chessbase_integrity_current_workflow",
            "tests.test_chessbase_integrity",
            "tests.test_import_contract",
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
