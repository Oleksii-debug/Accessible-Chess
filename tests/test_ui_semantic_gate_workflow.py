from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UiSemanticGateWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (
            ROOT / ".github" / "workflows" / "ui-semantic-gate.yml"
        ).read_text(encoding="utf-8")

    def _trigger_blocks(self) -> tuple[str, str]:
        push_start = self.workflow.index("  push:\n")
        pull_start = self.workflow.index("  pull_request:\n")
        dispatch = self.workflow.index("  workflow_dispatch:", pull_start)
        return (
            self.workflow[push_start:pull_start],
            self.workflow[pull_start:dispatch],
        )

    def test_live_full_product_is_push_and_pull_request_authority(self) -> None:
        current = "work/full-product-teacher-education-reachability-20260911"
        for block in self._trigger_blocks():
            self.assertIn(current, block)
        for stale in (
            "dev/stage1-nvda-userflow-0.4.0",
            "dev/stage1-nvda-userflow-0.4.0-r9",
            "integration/accessible-chess-next",
            "integration/version2-final-formats-20260831",
            "codex/v2-formats-completion-20260907",
            "codex/v2-runtime-completion-20260907",
            "automation/w4-v2-ui-semantic-gate-20260907",
        ):
            self.assertNotIn(stale, self.workflow)

    def test_trigger_covers_current_semantic_composition_surfaces(self) -> None:
        required = (
            "web/**",
            "run_accessible_chess_v2.py",
            "acs/full_product_actions.py",
            "acs/full_product_native_menu.py",
            "acs/full_product_presenters.py",
            "acs/full_product_ui_shell.py",
            "acs/full_product_webview_adapter.py",
            "acs/stage1_release_ui.py",
            "acs/stage1_release_ui_core.py",
            "acs/ui_analysis_adapter.py",
            "acs/ui_keymap_adapter.py",
            "acs/ui_keymap_editor.py",
            "acs/ui_keymap_service.py",
            "acs/ui_native_menu.py",
            "acs/ui_review_adapter.py",
            "acs/webapp_keymap.py",
            "acs/webapp_keymap_core.py",
            "acs/version2_application.py",
            "acs/version2_education_mutation_release.py",
            "acs/version2_release_ui.py",
            "acs/version2_release_app.py",
            "acs/version2_upgrade_status_release.py",
            "acs/version2_final_product_profile.py",
            "acs/version2_release_diagnostics.py",
            "acs/webview2_accessibility.py",
            "acs/version2_windows_*.py",
            "tests/test_dev1_full_product_accessible_shell.py",
            "tests/test_dev1_full_product_ui_packages.py",
            "tests/test_dev1_full_product_webview_adapter.py",
            "tests/test_full_product_native_menu.py",
            "tests/test_stage1_native_menu_action_routing.py",
            "tests/test_ui_analysis_adapter.py",
            "tests/test_ui_keymap_adapter.py",
            "tests/test_ui_keymap_editor.py",
            "tests/test_ui_keymap_service.py",
            "tests/test_ui_native_menu_recovery.py",
            "tests/test_ui_review_adapter.py",
            "tests/test_webapp_keymap_api.py",
            "tests/test_webview_keymap_bridge_contract.py",
            "tests/test_windows_native_menu_smoke_contract.py",
            "tests/test_p0_dynamic_selection_action_delivery.py",
            "tests/test_p0_semantic_document_copy.py",
            "tests/test_version2_release_accessibility_contract.py",
            "tests/js/version2_release_bootstrap_dom_test.js",
            "tests/test_ui_semantic_gate_workflow.py",
        )
        for block in self._trigger_blocks():
            self.assertIn("paths:", block)
            for path in required:
                with self.subTest(path=path):
                    self.assertIn(path, block)

    def test_checkout_and_geometry_bind_exact_live_product_identity(self) -> None:
        self.assertIn("fetch-depth: 0", self.workflow)
        self.assertIn("ref: ${{ github.event.pull_request.head.sha || github.sha }}", self.workflow)
        self.assertIn("PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}", self.workflow)
        self.assertIn(
            "PRODUCT_BRANCH: work/full-product-teacher-education-reachability-20260911",
            self.workflow,
        )
        self.assertIn('event_base="${PR_BASE_SHA:-}"', self.workflow)
        self.assertIn('git cat-file -e "$event_base^{commit}"', self.workflow)
        self.assertIn(
            'git fetch --no-tags origin "+refs/heads/$PRODUCT_BRANCH:refs/remotes/origin/$PRODUCT_BRANCH"',
            self.workflow,
        )
        self.assertIn(
            'live_base="$(git rev-parse "refs/remotes/origin/$PRODUCT_BRANCH")"',
            self.workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$event_base" "$live_base"', self.workflow)
        self.assertIn('git merge-base --is-ancestor "$live_base" HEAD', self.workflow)
        self.assertIn('test "$(git merge-base "$live_base" HEAD)" = "$live_base"', self.workflow)
        self.assertIn('git diff --check "$live_base" HEAD', self.workflow)
        self.assertNotIn('git diff --check "$event_base" HEAD', self.workflow)

    def test_accessibility_regressions_and_dual_os_gate_remain(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.workflow)
        for suite in (
            "tests.test_accessible_webui",
            "tests.test_dev1_full_product_accessible_shell",
            "tests.test_dev1_full_product_ui_packages",
            "tests.test_dev1_full_product_webview_adapter",
            "tests.test_full_product_native_menu",
            "tests.test_stage1_native_menu_action_routing",
            "tests.test_nvda_p0_contract",
            "tests.test_stage1_complete_user_flow",
            "tests.test_stage1_release_composition_ui",
            "tests.test_stage1_packaged_focus_origin_contract",
            "tests.test_stage1_webview2_accessibility_boundary",
            "tests.test_p0_dynamic_selection_action_delivery",
            "tests.test_p0_semantic_document_copy",
            "tests.test_version2_release_accessibility_contract",
        ):
            with self.subTest(suite=suite):
                self.assertIn(suite, self.workflow)
        for path in (
            "tests/test_dev1_full_product_accessible_shell.py",
            "tests/test_dev1_full_product_ui_packages.py",
            "tests/test_dev1_full_product_webview_adapter.py",
            "tests/test_full_product_native_menu.py",
            "tests/test_ui_keymap_service.py",
            "tests/test_ui_native_menu_recovery.py",
            "tests/test_webapp_keymap_api.py",
        ):
            self.assertIn(path, self.workflow)
        self.assertIn("tests/test_p0_dynamic_selection_action_delivery.py", self.workflow)
        self.assertIn("tests/test_p0_semantic_document_copy.py", self.workflow)
        self.assertIn("tests/test_v2_windows_*.py", self.workflow)
        self.assertIn("tests/test_ui_semantic_gate_workflow.py", self.workflow)
        self.assertIn("node tests/js/version2_release_bootstrap_dom_test.js", self.workflow)
        self.assertIn("python run_accessible_chess.py --diagnostic", self.workflow)
        self.assertIn("python run_accessible_chess_v2.py --diagnostic", self.workflow)
        self.assertIn(
            "group: ui-semantic-gate-${{ github.event.pull_request.number || github.ref }}",
            self.workflow,
        )
        self.assertIn("cancel-in-progress: true", self.workflow)


if __name__ == "__main__":
    unittest.main()
