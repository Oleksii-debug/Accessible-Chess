from __future__ import annotations

import unittest
from pathlib import Path


class ChessBaseMetadataCurrentStackWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "v2-chessbase-metadata-d07-successor.yml"
        ).read_text(encoding="utf-8")

    def test_exact_candidate_and_d09_parent_are_late_bound(self) -> None:
        self.assertNotIn("V2_METADATA_BASE_SHA", self.workflow)
        self.assertNotIn("9e62392c4d9168e32345928ba590e4a3dcffcedb", self.workflow)
        self.assertIn(
            "work/v2-dev09-cbh-annotations-variations-20260831",
            self.workflow,
        )
        self.assertGreaterEqual(
            self.workflow.count(
                "expected='${{ github.event.pull_request.head.sha || github.sha }}'"
            ),
            2,
        )
        self.assertGreaterEqual(
            self.workflow.count('git merge-base --is-ancestor "$parent" HEAD'),
            2,
        )
        self.assertGreaterEqual(
            self.workflow.count('test "$(git merge-base "$parent" HEAD)" = "$parent"'),
            2,
        )

    def test_six_path_metadata_scope_fails_closed(self) -> None:
        for path in (
            ".github/workflows/v2-chessbase-metadata-d07-successor.yml",
            "acs/chessbase_metadata.py",
            "tests/test_v2_chessbase_metadata_current_stack_workflow.py",
            "tests/test_v2_chessbase_metadata.py",
            "tests/v2_chessbase_metadata_probe.py",
            "tools/optional/libcbh_json_bridge.cpp",
        ):
            with self.subTest(path=path):
                self.assertGreaterEqual(self.workflow.count(f"'{path}'"), 2)
        self.assertGreaterEqual(self.workflow.count('git diff --check "$parent" HEAD'), 2)

    def test_external_actions_and_backends_are_pinned(self) -> None:
        self.assertNotIn("actions/checkout@v4", self.workflow)
        self.assertNotIn("actions/setup-python@v5", self.workflow)
        self.assertNotIn("actions/upload-artifact@v4", self.workflow)
        self.assertIn(
            "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
            self.workflow,
        )
        self.assertIn(
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
            self.workflow,
        )
        self.assertIn(
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
            self.workflow,
        )
        self.assertIn("LIBCBH_COMMIT: 9641c5c3949d8fb210b17dd9aa54455645843696", self.workflow)
        self.assertIn("UNCBV_COMMIT: 3c18e8a7c6a30c21f945a1ab5462521c306dca57", self.workflow)

    def test_combined_bridge_real_d09_proof_is_mandatory(self) -> None:
        self.assertIn(
            "tests.test_v2_dev09_cbh_annotations_variations",
            self.workflow,
        )
        self.assertIn("LIBCBH_ANNOTATION_DIR:", self.workflow)
        self.assertIn("LIBCBH_VARIATION_DIR:", self.workflow)
        self.assertIn("LIBCBH_UNUSUAL_DIR:", self.workflow)


if __name__ == "__main__":
    unittest.main()
