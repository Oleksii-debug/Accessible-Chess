from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "v2-windows-library-import-observer.yml"
CURRENT_PRODUCT_BRANCH = "work/full-product-teacher-education-reachability-20260911"


class WindowsLibraryImportObserverWorkflowTests(unittest.TestCase):
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

    def test_live_full_product_is_push_and_pull_request_authority(self) -> None:
        for block in self._trigger_blocks():
            self.assertIn(CURRENT_PRODUCT_BRANCH, block)
        self.assertNotIn(
            "work/v2-windows-library-canonical-observer-20260831",
            self.workflow,
        )
        self.assertNotIn("work/v2-windows-nvda-ui-20260828", self.workflow)
        self.assertNotIn("HOST_BASE", self.workflow)
        self.assertNotIn("dc7427cb89a0b6a997cae467f82265778ea78168", self.workflow)

    def test_triggers_cover_observer_host_application_and_projection_seams(self) -> None:
        required = (
            "acs/version2_windows_library_import_observer.py",
            "acs/version2_windows_file_workflows.py",
            "acs/version2_windows_host_runtime.py",
            "acs/version2_windows_import_event_mailbox.py",
            "acs/version2_windows_import_ui_pump.py",
            "acs/library_import_service.py",
            "acs/library_webview_projection.py",
            "acs/version2_application.py",
            "tests/test_v2_windows_library_import_observer.py",
            "tests/test_v2_windows_nvda_file_workflows.py",
            "tests/test_v2_windows_host_runtime.py",
            "tests/test_v2_windows_import_event_mailbox.py",
            "tests/test_v2_windows_import_ui_pump.py",
            "tests/test_library_import_ui_integration.py",
            "tests/test_dev1_library_webview_projection.py",
            "tests/test_d07_library_import_service.py",
            "tests/test_v2_windows_library_import_observer_workflow.py",
            ".github/workflows/v2-windows-library-import-observer.yml",
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
        self.assertNotIn("Prove exact stacked scope and owner isolation", self.workflow)

    def test_dual_os_and_current_observer_contracts_remain_required(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.workflow)
        self.assertIn("pytest==8.4.2", self.workflow)
        focused = (
            "tests.test_v2_windows_library_import_observer",
            "tests.test_v2_windows_library_import_observer_workflow",
            "tests.test_v2_windows_nvda_file_workflows",
            "tests.test_v2_windows_host_runtime",
            "tests.test_v2_windows_import_event_mailbox",
            "tests.test_v2_windows_import_ui_pump",
            "tests.test_library_import_ui_integration",
            "tests.test_dev1_library_webview_projection",
            "tests.test_d07_library_import_service",
        )
        for suite in focused:
            with self.subTest(suite=suite):
                self.assertIn(suite, self.workflow)

    def test_broad_qualification_and_diagnostics_remain_fail_closed(self) -> None:
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)
        self.assertIn("python -m pytest -q tests", self.workflow)
        self.assertIn("python -m acs.selftest", self.workflow)
        self.assertIn("python run_accessible_chess.py --diagnostic", self.workflow)


if __name__ == "__main__":
    unittest.main()
