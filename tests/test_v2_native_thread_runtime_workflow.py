from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NativeThreadRuntimeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (
            ROOT / ".github" / "workflows" / "v2-native-thread-runtime.yml"
        ).read_text(encoding="utf-8")

    def _trigger_blocks(self) -> tuple[str, str]:
        push_start = self.workflow.index("  push:\n")
        pull_start = self.workflow.index("  pull_request:\n")
        permissions = self.workflow.index("\npermissions:", pull_start)
        return (
            self.workflow[push_start:pull_start],
            self.workflow[pull_start:permissions],
        )

    def test_product_push_and_main_reconverged_pr_authorities(self) -> None:
        push, pull = self._trigger_blocks()
        self.assertIn(
            "work/full-product-teacher-education-reachability-20260911", push
        )
        self.assertIn(
            "integration/current-main-windows-apex-reconvergence-20261004-sol",
            pull,
        )
        self.assertNotIn("codex/v2-runtime-completion-20260907", self.workflow)

    def test_trigger_covers_thread_runtime_authorities_and_regressions(self) -> None:
        required = (
            "acs/version2_release_ui.py",
            "acs/version2_release_app.py",
            "acs/version2_windows_host_runtime.py",
            "acs/version2_windows_file_workflows.py",
            "acs/version2_windows_import_event_mailbox.py",
            "acs/version2_windows_import_ui_pump.py",
            "acs/version2_windows_pgn_streaming_host.py",
            "scripts/v2_native_thread_oracle.py",
            "tests/test_v2_native_thread_runtime_workflow.py",
            "tests/test_v2_windows_host_runtime.py",
            "tests/test_v2_windows_import_event_mailbox.py",
            "tests/test_v2_windows_import_ui_pump.py",
            "tests/test_version2_api_thread_dispatch.py",
            "tests/test_version2_release_app.py",
            "tests/test_version2_release_ui.py",
            "tests/test_version2_shutdown.py",
            "tests/test_w3_windows_file_action_ui_thread_affinity.py",
        )
        for block in self._trigger_blocks():
            self.assertIn("paths:", block)
            for path in required:
                with self.subTest(path=path):
                    self.assertIn(path, block)

    def test_pr_geometry_late_binds_live_base_and_exact_four_path_scope(self) -> None:
        required = (
            "PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            "PR_BASE_REF: ${{ github.event.pull_request.base.ref }}",
            "PR_HEAD_SHA: ${{ github.event.pull_request.head.sha }}",
            'git fetch --no-tags origin "$PR_BASE_REF"',
            'live_base="$(git rev-parse "origin/$PR_BASE_REF")"',
            'git merge-base --is-ancestor "$PR_BASE_SHA" "$live_base"',
            'git merge-base --is-ancestor "$live_base" HEAD',
            'test "$(git merge-base "$live_base" HEAD)" = "$live_base"',
            'git diff --check "$live_base" HEAD',
            "'.github/workflows/v2-native-thread-runtime.yml'",
            "'.github/workflows/v2-windows-book-board-adapter.yml'",
            "'tests/test_v2_native_thread_runtime_workflow.py'",
            "'tests/test_v2_windows_book_board_adapter_workflow.py'",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.workflow)
        self.assertIn("fetch-depth: 0", self.workflow)

    def test_qualification_only_gate_pins_reconverged_runtime_as_inherited(self) -> None:
        self.assertIn('git diff --quiet "$live_base" HEAD --', self.workflow)
        for path in (
            "acs/version2_release_ui.py",
            "acs/version2_release_app.py",
            "acs/version2_windows_host_runtime.py",
            "acs/version2_windows_file_workflows.py",
            "acs/version2_windows_import_event_mailbox.py",
            "acs/version2_windows_import_ui_pump.py",
            "acs/version2_windows_pgn_streaming_host.py",
            "acs/version2_application.py",
            "scripts/v2_native_thread_oracle.py",
        ):
            with self.subTest(path=path):
                self.assertIn(path, self.workflow)

    def test_real_windows_oracle_and_focused_thread_suites_remain_required(self) -> None:
        self.assertIn("runs-on: windows-2025", self.workflow)
        self.assertIn("python -m scripts.v2_native_thread_oracle", self.workflow)
        self.assertIn("pytest==8.4.2", self.workflow)
        self.assertIn("pywebview==6.2.1", self.workflow)
        self.assertIn("zstandard==0.23.0", self.workflow)
        for suite in (
            "tests/test_version2_api_thread_dispatch.py",
            "tests/test_w3_windows_file_action_ui_thread_affinity.py",
            "tests/test_version2_release_ui.py",
            "tests/test_version2_release_app.py",
            "tests/test_version2_shutdown.py",
            "tests/test_v2_windows_host_runtime.py",
            "tests/test_v2_windows_import_event_mailbox.py",
            "tests/test_v2_windows_import_ui_pump.py",
            "tests/test_v2_native_thread_runtime_workflow.py",
        ):
            with self.subTest(suite=suite):
                self.assertIn(suite, self.workflow)


if __name__ == "__main__":
    unittest.main()
