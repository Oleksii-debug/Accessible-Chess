from __future__ import annotations

from pathlib import Path
import unittest


class D06RealCorpusRecoveryWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "d06-real-corpus-recovery.yml"
        ).read_text(encoding="utf-8")

    def test_live_product_is_scope_authority_and_event_base_is_ancestry_witness(self) -> None:
        self.assertIn(
            "branches:\n      - work/full-product-teacher-education-reachability-20260911",
            self.workflow,
        )
        self.assertIn(
            "PRODUCT_BRANCH: work/full-product-teacher-education-reachability-20260911",
            self.workflow,
        )
        self.assertIn(
            "PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            self.workflow,
        )
        self.assertIn(
            "PR_HEAD_SHA: ${{ github.event.pull_request.head.sha }}",
            self.workflow,
        )
        self.assertIn('git fetch --no-tags origin "$PRODUCT_BRANCH"', self.workflow)
        self.assertIn('live_product="$(git rev-parse FETCH_HEAD)"', self.workflow)
        self.assertIn(
            'git merge-base --is-ancestor "$PR_BASE_SHA" "$live_product"',
            self.workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$live_product" HEAD', self.workflow)
        self.assertIn(
            'test "$(git merge-base "$live_product" HEAD)" = "$live_product"',
            self.workflow,
        )
        self.assertIn('git diff --check "$live_product" HEAD', self.workflow)

    def test_historical_recovery_base_and_exact_delta_are_not_descendant_authority(self) -> None:
        self.assertNotIn(
            "6567f3d35ffefaa85ae7e8b87d9fcc0d188e7cac",
            self.workflow,
        )
        self.assertNotIn("RECOVERY_BASE:", self.workflow)
        self.assertNotIn('test "$changed" = "$expected"', self.workflow)
        self.assertNotIn('expected="$(printf', self.workflow)

    def test_real_corpus_oracle_remains_byte_locked(self) -> None:
        self.assertIn(
            "oracle='tests/test_d06_real_corpus_recovery.py'",
            self.workflow,
        )
        self.assertIn(
            'base_oracle="$(git rev-parse "$live_product:$oracle")"',
            self.workflow,
        )
        self.assertIn(
            'candidate_oracle="$(git rev-parse "HEAD:$oracle")"',
            self.workflow,
        )
        self.assertIn(
            "D06 recovery oracle drift requires a dedicated successor",
            self.workflow,
        )

    def test_exact_head_and_release_contamination_fence_remain_fail_closed(self) -> None:
        self.assertIn(
            "ref: ${{ github.event.pull_request.head.sha }}",
            self.workflow,
        )
        self.assertIn(
            'test "$(git rev-parse HEAD)" = "$PR_HEAD_SHA"',
            self.workflow,
        )
        self.assertIn(
            "Frozen Stage 1 / strict-release contamination detected",
            self.workflow,
        )

    def test_contract_test_is_triggered_compiled_and_run(self) -> None:
        self.assertGreaterEqual(
            self.workflow.count("tests/test_d06_real_corpus_recovery_workflow.py"),
            2,
        )
        self.assertIn(
            "tests.test_d06_real_corpus_recovery_workflow",
            self.workflow,
        )

    def test_dual_os_recovery_and_full_product_gates_remain(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.workflow)
        self.assertIn("tests.test_d06_real_corpus_recovery", self.workflow)
        self.assertIn("tests.test_pgn_document", self.workflow)
        self.assertIn("tests.test_pgn_workspace", self.workflow)
        self.assertIn("python -m unittest discover -s tests", self.workflow)
        self.assertIn("python -m pytest -q tests", self.workflow)
        self.assertIn("python -m acs.selftest", self.workflow)
        self.assertIn("python run_accessible_chess.py --diagnostic", self.workflow)


if __name__ == "__main__":
    unittest.main()
