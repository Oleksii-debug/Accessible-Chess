from __future__ import annotations

from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/windows-unicode-path-portability.yml")
HISTORICAL_PRODUCT_BRANCH = "work/full-product-teacher-education-reachability-20260911"
CANONICAL_ORACLE_BLOB = "23e6397082d4133726c35f9dedff76a32e0c83f9"


class WindowsUnicodePathPortabilityWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_no_historical_product_branch_trigger_lock(self) -> None:
        self.assertNotIn(HISTORICAL_PRODUCT_BRANCH, self.text)
        self.assertNotIn("CURRENT_PRODUCT_BASE", self.text)
        self.assertNotIn("PRODUCT_BASE:", self.text)

    def test_pull_request_uses_event_and_live_base_ancestry(self) -> None:
        required = (
            "github.event.pull_request.base.sha",
            "github.event.pull_request.base.ref",
            'git fetch --no-tags origin "$base_ref"',
            'git merge-base --is-ancestor "$event_base" "$live_base"',
            'git merge-base --is-ancestor "$live_base" HEAD',
            'git merge-base "$live_base" HEAD',
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_converged_owner_can_requalify_without_reopening_product_scope(self) -> None:
        required = (
            "FOCUSED_BASE_REF: converge/books-training-owner-current-20261004-zftrkmo",
            "INTEGRATED_HEAD: d1560f918c266a6dc8c603f977855beabc48391a",
            'git merge-base --is-ancestor "$INTEGRATED_HEAD" HEAD',
            "WINDOWS_PATH_PORTABILITY_SCOPE=CONVERGED_SUCCESSOR",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_gate_remains_evidence_only_and_binds_canonical_oracle(self) -> None:
        required = (
            "tests/test_windows_unicode_path_portability.py",
            "tests/test_windows_unicode_path_portability_workflow.py",
            "git diff --quiet",
            "-- acs web packaging run_accessible_chess.py",
            "git hash-object tests/test_windows_unicode_path_portability.py",
            CANONICAL_ORACLE_BLOB,
            "WINDOWS_PATH_PORTABILITY_SCOPE=TEST_WORKFLOW_ONLY",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_dual_os_and_real_oracle_execution_remain_required(self) -> None:
        self.assertIn("matrix:", self.text)
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.text)
        self.assertIn("tests.test_windows_unicode_path_portability", self.text)
        self.assertIn("tests.test_windows_unicode_path_portability_workflow", self.text)
        self.assertIn("python -m acs.selftest", self.text)
        self.assertIn("python run_accessible_chess.py --diagnostic", self.text)


if __name__ == "__main__":
    unittest.main()
