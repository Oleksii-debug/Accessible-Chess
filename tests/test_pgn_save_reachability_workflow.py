from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PgnSaveReachabilityWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (
            ROOT / ".github" / "workflows" / "v2-windows-pgn-save-action-reachability.yml"
        ).read_text(encoding="utf-8")

    def test_live_product_is_push_and_pull_request_authority(self) -> None:
        current = "work/full-product-teacher-education-reachability-20260911"
        self.assertGreaterEqual(self.workflow.count(current), 3)
        self.assertNotIn("work/v2-windows-format-ui-dev29-20260831", self.workflow)
        self.assertNotIn("work/v2-windows-nvda-ui-20260828", self.workflow)
        self.assertNotIn("dc7427cb89a0b6a997cae467f82265778ea78168", self.workflow)

    def test_exact_pr_identity_uses_live_product_not_stale_event_base(self) -> None:
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
        self.assertIn('git cat-file -e "$live_base^{commit}"', self.workflow)
        self.assertIn(
            'git merge-base --is-ancestor "$event_base" "$live_base"',
            self.workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$live_base" HEAD', self.workflow)
        self.assertIn(
            'test "$(git merge-base "$live_base" HEAD)" = "$live_base"',
            self.workflow,
        )
        self.assertIn('git diff --check "$live_base" HEAD', self.workflow)
        self.assertNotIn('git merge-base --is-ancestor "$event_base" HEAD', self.workflow)
        self.assertNotIn('git diff --check "$event_base" HEAD', self.workflow)

    def test_trigger_covers_action_menu_host_and_composition_seams(self) -> None:
        for path in (
            "acs/full_product_actions.py",
            "acs/full_product_native_menu.py",
            "acs/full_product_ui_shell.py",
            "acs/version2_release_app.py",
            "acs/version2_windows_file_workflows.py",
            "acs/version2_windows_host_runtime.py",
            "tests/test_v2_windows_pgn_save_action_reachability.py",
            "tests/test_pgn_save_reachability_workflow.py",
        ):
            self.assertGreaterEqual(self.workflow.count(path), 2, path)

    def test_dual_os_and_full_qualification_remain(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.workflow)
        self.assertIn("tests.test_v2_windows_pgn_save_action_reachability", self.workflow)
        self.assertIn("tests.test_v2_windows_host_runtime", self.workflow)
        self.assertIn("tests.test_pgn_document", self.workflow)
        self.assertIn("tests.test_pgn_service", self.workflow)
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)
        self.assertIn("python -m pytest -q tests", self.workflow)
        self.assertIn("python -m acs.selftest", self.workflow)
        self.assertIn("python run_accessible_chess.py --diagnostic", self.workflow)


if __name__ == "__main__":
    unittest.main()
