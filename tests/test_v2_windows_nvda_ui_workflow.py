from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "v2-windows-nvda-ui.yml"
CURRENT_PRODUCT_BRANCH = "work/full-product-teacher-education-reachability-20260911"


class WindowsNvdaUiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def _trigger_blocks(self) -> tuple[str, str]:
        push_start = self.workflow.index("  push:\n")
        pull_start = self.workflow.index("  pull_request:\n")
        permissions = self.workflow.index("\npermissions:", pull_start)
        return (
            self.workflow[push_start:pull_start],
            self.workflow[pull_start:permissions],
        )

    def test_live_full_product_is_push_and_pull_request_authority(self) -> None:
        for block in self._trigger_blocks():
            self.assertIn(CURRENT_PRODUCT_BRANCH, block)
        self.assertNotIn("work/v2-windows-nvda-ui-20260828", self.workflow)
        self.assertNotIn("work/version2-integration-formats-20260827", self.workflow)
        self.assertNotIn("V2_UI_BASE", self.workflow)
        self.assertNotIn("575ec0088982d2f90adb47c040a5714d68186b0e", self.workflow)

    def test_trigger_covers_current_windows_runtime_and_shipping_composition(self) -> None:
        required = (
            "acs/version2_windows_file_workflows.py",
            "acs/version2_windows_pgn_export.py",
            "acs/version2_windows_import_event_mailbox.py",
            "acs/version2_windows_import_ui_pump.py",
            "acs/version2_windows_native_dialog_ownership.py",
            "acs/version2_windows_host_runtime.py",
            "acs/version2_windows_pgn_streaming_host.py",
            "acs/version2_release_ui.py",
            "acs/version2_release_app.py",
            "acs/version2_education_mutation_release.py",
            "acs/version2_application.py",
            "tests/test_v2_windows_nvda_file_workflows.py",
            "tests/test_v2_windows_pgn_export.py",
            "tests/test_v2_windows_import_event_mailbox.py",
            "tests/test_v2_windows_import_ui_pump.py",
            "tests/test_v2_windows_native_dialog_ownership.py",
            "tests/test_v2_windows_host_runtime.py",
            "tests/test_v2_windows_pgn_streaming_host_lifecycle.py",
            "tests/test_version2_release_ui.py",
            "tests/test_version2_release_app.py",
            "tests/test_v2_windows_nvda_ui_workflow.py",
            ".github/workflows/v2-windows-nvda-ui.yml",
        )
        for block in self._trigger_blocks():
            self.assertIn("paths:", block)
            for path in required:
                with self.subTest(path=path):
                    self.assertIn(path, block)

    def test_checkout_and_geometry_bind_exact_candidate(self) -> None:
        self.assertIn("fetch-depth: 0", self.workflow)
        self.assertIn(
            "ref: ${{ github.event.pull_request.head.sha || github.sha }}",
            self.workflow,
        )
        self.assertIn(
            "PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            self.workflow,
        )
        self.assertIn('base="${PR_BASE_SHA:-}"', self.workflow)
        self.assertIn('git cat-file -e "$base^{commit}"', self.workflow)
        self.assertIn('git merge-base --is-ancestor "$base" HEAD', self.workflow)
        self.assertIn('test "$(git merge-base "$base" HEAD)" = "$base"', self.workflow)
        self.assertIn('git diff --check "$base" HEAD', self.workflow)
        self.assertIn('parent="$(git rev-parse HEAD^)"', self.workflow)
        self.assertIn('git diff --check "$parent" HEAD', self.workflow)

    def test_dual_os_and_real_winforms_ownership_smoke_remain_required(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.workflow)
        self.assertIn("pytest==8.4.2", self.workflow)
        self.assertIn("pythonnet==3.0.5", self.workflow)
        self.assertIn("Version2WindowsFileDialogs._load_forms()", self.workflow)
        self.assertIn("Version2WindowsPgnExportDialogs._load_forms()", self.workflow)
        self.assertIn("Version2WinFormsUiPoster(owner)", self.workflow)
        self.assertIn("Version2WindowsFileWorkflowRuntime(", self.workflow)
        self.assertIn("owned_files.dialog_owner.resolve() is owner", self.workflow)
        self.assertIn("owned_export.dialog_owner.resolve() is owner", self.workflow)
        self.assertIn("runtime.file_dialogs.dialog_owner.resolve() is owner", self.workflow)
        self.assertIn("runtime.export_dialogs.dialog_owner.resolve() is owner", self.workflow)
        self.assertIn("WINDOWS WINFORMS OWNER RUNTIME + UI POST COMPOSITION PASS", self.workflow)

    def test_focused_and_broad_qualification_remain_fail_closed(self) -> None:
        focused = (
            "tests.test_v2_windows_nvda_file_workflows",
            "tests.test_v2_windows_host_runtime",
            "tests.test_v2_windows_pgn_streaming_host_lifecycle",
            "tests.test_v2_windows_nvda_ui_workflow",
            "tests.test_version2_release_ui",
            "tests.test_version2_release_app",
            "tests.test_v2_windows_import_event_mailbox",
            "tests.test_v2_windows_import_ui_pump",
            "tests.test_v2_windows_native_dialog_ownership",
            "tests.test_v2_windows_pgn_export",
            "tests.test_d06_file_ingress_nag_normalization",
            "tests.test_pgn_document",
            "tests.test_dev1_pgn_workspace_webview_adapter",
            "tests.test_dev1_full_product_accessible_shell",
            "tests.test_dev1_full_product_ui_packages",
            "tests.test_dev1_full_product_webview_adapter",
            "tests.test_library_import_ui_integration",
            "tests.test_version2_formats_integration",
        )
        for suite in focused:
            with self.subTest(suite=suite):
                self.assertIn(suite, self.workflow)
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)
        self.assertIn("python -m pytest -q tests", self.workflow)
        self.assertIn("python -m acs.selftest", self.workflow)
        self.assertIn("python run_accessible_chess.py --diagnostic", self.workflow)


if __name__ == "__main__":
    unittest.main()
