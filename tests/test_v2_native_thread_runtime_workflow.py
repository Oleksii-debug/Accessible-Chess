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

    def test_live_full_product_is_push_and_pull_request_authority(self) -> None:
        current = "work/full-product-teacher-education-reachability-20260911"
        for block in self._trigger_blocks():
            self.assertIn(current, block)
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

    def test_pr_geometry_uses_exact_event_base(self) -> None:
        self.assertIn(
            "PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            self.workflow,
        )
        self.assertIn('base="${PR_BASE_SHA:-}"'.replace("\\$", "$"), self.workflow)
        self.assertIn('git cat-file -e "$base^{commit}"', self.workflow)
        self.assertIn('git merge-base --is-ancestor "$base" HEAD', self.workflow)
        self.assertIn('test "$(git merge-base "$base" HEAD)" = "$base"', self.workflow)
        self.assertIn('git diff --check "$base" HEAD', self.workflow)
        self.assertIn("fetch-depth: 0", self.workflow)

    def test_real_windows_oracle_and_focused_thread_suites_remain_required(self) -> None:
        self.assertIn("runs-on: windows-2025", self.workflow)
        self.assertIn("python -m scripts.v2_native_thread_oracle", self.workflow)
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
