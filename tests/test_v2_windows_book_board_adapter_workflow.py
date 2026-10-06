from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BookBoardAdapterWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (
            ROOT / ".github" / "workflows" / "v2-windows-book-board-adapter.yml"
        ).read_text(encoding="utf-8")

    def _trigger_blocks(self) -> tuple[str, str]:
        push_start = self.workflow.index("  push:\n")
        pull_start = self.workflow.index("  pull_request:\n")
        dispatch = self.workflow.index("  workflow_dispatch:", pull_start)
        return (
            self.workflow[push_start:pull_start],
            self.workflow[pull_start:dispatch],
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
        self.assertNotIn("work/v2-windows-book-board-adapter-20260831", self.workflow)
        self.assertNotIn("work/v2-book-board-workflow-20260831", self.workflow)

    def test_live_stacked_geometry_and_exact_four_path_scope(self) -> None:
        for fragment in (
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
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.workflow)
        self.assertIn("fetch-depth: 0", self.workflow)

    def test_trigger_covers_adapter_and_inherited_application_seams(self) -> None:
        required = (
            "run_accessible_chess_v2.py",
            "acs/version2_windows_book_board_adapter.py",
            "acs/book_board_workflow.py",
            "acs/book_webview_projection.py",
            "acs/book_webview_bridge.py",
            "acs/full_product_presenters.py",
            "acs/full_product_actions.py",
            "acs/version2_application.py",
            "tests/test_v2_windows_book_board_adapter.py",
            "tests/test_v2_book_board_workflow.py",
            "tests/test_v2_windows_book_board_adapter_workflow.py",
        )
        for block in self._trigger_blocks():
            self.assertIn("paths:", block)
            for path in required:
                with self.subTest(path=path):
                    self.assertIn(path, block)

    def test_qualification_only_gate_keeps_reconverged_authorities_inherited(self) -> None:
        self.assertIn('git diff --quiet "$live_base" HEAD --', self.workflow)
        for path in (
            "run_accessible_chess.py",
            "run_accessible_chess_v2.py",
            "acs/version2_windows_book_board_adapter.py",
            "acs/book_board_workflow.py",
            "acs/book_webview_projection.py",
            "acs/book_webview_bridge.py",
            "acs/full_product_presenters.py",
            "acs/full_product_actions.py",
            "acs/version2_application.py",
            "acs/version2_windows_file_workflows.py",
        ):
            with self.subTest(path=path):
                self.assertIn(path, self.workflow)

    def test_non_bookboard_current_apex_successors_use_application_compatibility_mode(self) -> None:
        self.assertIn("BOOK_BOARD_TOPOLOGY=EXACT_NARROW_SUCCESSOR", self.workflow)
        self.assertIn("BOOK_BOARD_TOPOLOGY=APPLICATION_COMPATIBILITY", self.workflow)
        compatibility = self.workflow.split(
            "Other current-apex successors may legitimately change the", 1
        )[1].split("BOOK_BOARD_TOPOLOGY=APPLICATION_COMPATIBILITY", 1)[0]
        for path in (
            "run_accessible_chess.py",
            "run_accessible_chess_v2.py",
            "acs/version2_windows_book_board_adapter.py",
            "acs/book_board_workflow.py",
            "acs/book_webview_projection.py",
            "acs/book_webview_bridge.py",
            "acs/full_product_presenters.py",
            "acs/full_product_actions.py",
            "acs/version2_windows_file_workflows.py",
        ):
            with self.subTest(path=path):
                self.assertIn(path, compatibility)
        self.assertNotIn("acs/version2_application.py", compatibility)

    def test_dual_os_and_complete_qualification_remain(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.workflow)
        self.assertIn("pytest==8.4.2", self.workflow)
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)
        self.assertIn("python -m pytest -q tests", self.workflow)
        self.assertIn("python -m acs.selftest", self.workflow)
        self.assertIn("python run_accessible_chess.py --diagnostic", self.workflow)
        self.assertIn("python run_accessible_chess_v2.py --diagnostic", self.workflow)
        self.assertIn("tests.test_v2_windows_book_board_adapter_workflow", self.workflow)
        self.assertIn("tests.test_v2_windows_book_board_adapter", self.workflow)
        self.assertIn("tests.test_v2_book_board_workflow", self.workflow)


if __name__ == "__main__":
    unittest.main()
