from __future__ import annotations

import unittest
from pathlib import Path


class Dev09CbhCurrentProductWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "v2-dev09-cbh-annotations-variations.yml"
        ).read_text(encoding="utf-8")

    def test_late_binds_exact_current_full_product(self) -> None:
        self.assertNotIn("V2_AUTHORITY_SHA", self.workflow)
        self.assertNotIn("575ec0088982d2f90adb47c040a5714d68186b0e", self.workflow)
        self.assertGreaterEqual(
            self.workflow.count('git merge-base --is-ancestor "$product" HEAD'),
            2,
        )
        self.assertGreaterEqual(
            self.workflow.count('test "$(git merge-base "$product" HEAD)" = "$product"'),
            2,
        )
        self.assertIn(
            "work/full-product-teacher-education-reachability-20260911",
            self.workflow,
        )

    def test_current_candidate_identity_and_scope_fail_closed(self) -> None:
        self.assertGreaterEqual(
            self.workflow.count(
                "expected='${{ github.event.pull_request.head.sha || github.sha }}'"
            ),
            2,
        )
        self.assertGreaterEqual(
            self.workflow.count('test "$(git rev-parse HEAD)" = "$expected"'),
            2,
        )
        self.assertGreaterEqual(
            self.workflow.count('git diff --check "$product" HEAD'),
            2,
        )
        for path in (
            ".github/workflows/v2-dev09-cbh-annotations-variations.yml",
            "docs/automation/V2_CBH_ANNOTATION_CAPABILITY.json",
            "tests/test_v2_dev09_cbh_annotations_variations.py",
            "tests/test_v2_dev09_cbh_current_product_workflow.py",
            "tools/optional/libcbh_json_bridge.cpp",
        ):
            with self.subTest(path=path):
                self.assertGreaterEqual(self.workflow.count(f"'{path}'"), 3)

    def test_supply_chain_actions_are_commit_pinned(self) -> None:
        self.assertNotIn("actions/checkout@v4", self.workflow)
        self.assertNotIn("actions/setup-python@v5", self.workflow)
        self.assertIn(
            "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
            self.workflow,
        )
        self.assertIn(
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
            self.workflow,
        )

    def test_external_backend_remains_pinned(self) -> None:
        self.assertIn(
            "LIBCBH_COMMIT: 9641c5c3949d8fb210b17dd9aa54455645843696",
            self.workflow,
        )
        self.assertIn("repository: rolandlo/libcbh", self.workflow)
        self.assertIn(
            "ref: 9641c5c3949d8fb210b17dd9aa54455645843696",
            self.workflow,
        )


if __name__ == "__main__":
    unittest.main()
