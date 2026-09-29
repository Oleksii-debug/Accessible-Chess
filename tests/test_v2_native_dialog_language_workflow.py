from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NativeDialogLanguageWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (
            ROOT / ".github" / "workflows" / "v2-native-dialog-language.yml"
        ).read_text(encoding="utf-8")

    def test_pull_requests_target_current_full_product(self) -> None:
        marker = "  pull_request:\n"
        start = self.workflow.index(marker)
        end = self.workflow.index("\npermissions:", start)
        pull_request_block = self.workflow[start:end]
        self.assertIn(
            "work/full-product-teacher-education-reachability-20260911",
            pull_request_block,
        )
        self.assertNotIn("codex/v2-runtime-completion-20260907", pull_request_block)

    def test_exact_pull_request_base_drives_geometry_check(self) -> None:
        self.assertIn(
            "PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            self.workflow,
        )
        self.assertIn('base="${PR_BASE_SHA:-}"', self.workflow)
        self.assertIn('git cat-file -e "$base^{commit}"', self.workflow)
        self.assertIn('git merge-base --is-ancestor "$base" HEAD', self.workflow)
        self.assertIn(
            'test "$(git merge-base "$base" HEAD)" = "$base"',
            self.workflow,
        )
        self.assertIn('git diff --check "$base" HEAD', self.workflow)

    def test_historical_candidate_shape_is_not_required_of_descendants(self) -> None:
        self.assertNotIn("candidate_mode=false", self.workflow)
        self.assertNotIn("Unexpected current-runtime native-dialog owner delta", self.workflow)
        self.assertNotIn("NATIVE_DIALOG_PREDECESSOR", self.workflow)

    def test_contract_test_is_registered_in_trigger_compile_and_focused_gate(self) -> None:
        self.assertGreaterEqual(
            self.workflow.count("tests/test_v2_native_dialog_language_workflow.py"),
            2,
        )
        self.assertIn(
            "tests.test_v2_native_dialog_language_workflow",
            self.workflow,
        )

    def test_dual_os_and_existing_runtime_regressions_remain_required(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.workflow)
        for suite in (
            "tests.test_v2_native_dialog_language",
            "tests.test_v2_library_export_dialog_language",
            "tests.test_v2_windows_native_dialog_ownership",
            "tests.test_v2_windows_host_runtime",
            "tests.test_v2_windows_pgn_export",
            "tests.test_v2_windows_library_export",
            "tests.test_version2_release_app",
            "tests.test_w6_v2_language_owner_current",
        ):
            with self.subTest(suite=suite):
                self.assertIn(suite, self.workflow)
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)
        self.assertIn("python -m pytest -q tests", self.workflow)
        self.assertIn("python -m acs.selftest", self.workflow)
        self.assertIn("python run_accessible_chess_v2.py --diagnostic", self.workflow)


if __name__ == "__main__":
    unittest.main()
