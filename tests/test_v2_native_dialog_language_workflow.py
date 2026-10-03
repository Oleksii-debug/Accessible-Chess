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

    def test_current_full_product_is_push_and_pull_request_authority(self) -> None:
        current = "work/full-product-teacher-education-reachability-20260911"
        push_start = self.workflow.index("  push:\n")
        pull_start = self.workflow.index("  pull_request:\n")
        permissions = self.workflow.index("\npermissions:", pull_start)
        push_block = self.workflow[push_start:pull_start]
        pull_request_block = self.workflow[pull_start:permissions]
        self.assertIn(current, push_block)
        self.assertIn(current, pull_request_block)
        self.assertNotIn("work/v2-native-dialog-language-20260907", self.workflow)
        self.assertNotIn("codex/v2-runtime-completion-20260907", self.workflow)
        for block in (push_block, pull_request_block):
            with self.subTest(block=block.splitlines()[0]):
                self.assertIn("paths:", block)
                self.assertIn("tests/test_v2_native_dialog_language_workflow.py", block)

    def test_trigger_covers_dialog_implementations_and_language_owners(self) -> None:
        push_start = self.workflow.index("  push:\n")
        pull_start = self.workflow.index("  pull_request:\n")
        permissions = self.workflow.index("\npermissions:", pull_start)
        blocks = (
            self.workflow[push_start:pull_start],
            self.workflow[pull_start:permissions],
        )
        required_paths = (
            "acs/full_product_ui_shell.py",
            "acs/settings.py",
            "acs/version2_application.py",
            "acs/version2_release_app.py",
            "acs/version2_windows_file_workflows.py",
            "acs/version2_windows_host_runtime.py",
            "acs/version2_windows_library_export.py",
            "acs/version2_windows_native_dialog_ownership.py",
            "acs/version2_windows_pgn_export.py",
            "tests/test_v2_library_export_dialog_language.py",
            "tests/test_v2_native_dialog_language.py",
            "tests/test_v2_native_dialog_language_workflow.py",
            "tests/test_v2_windows_host_runtime.py",
            "tests/test_v2_windows_library_export.py",
            "tests/test_v2_windows_native_dialog_ownership.py",
            "tests/test_v2_windows_pgn_export.py",
            "tests/test_version2_release_app.py",
            "tests/test_w6_v2_language_owner_current.py",
        )
        for block in blocks:
            for path in required_paths:
                with self.subTest(block=block.splitlines()[0], path=path):
                    self.assertIn(path, block)

    def test_live_product_drives_pull_request_geometry(self) -> None:
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
        self.assertIn('test "$(git rev-parse HEAD)" = "$PR_HEAD_SHA"', self.workflow)

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
