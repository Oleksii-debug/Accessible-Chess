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

    def test_current_full_product_is_push_and_pull_request_authority(self) -> None:
        current = "work/full-product-teacher-education-reachability-20260911"
        for block in self._trigger_blocks():
            self.assertIn(current, block)
        self.assertNotIn("work/v2-windows-book-board-adapter-20260831", self.workflow)
        self.assertNotIn("work/v2-book-board-workflow-20260831", self.workflow)

    def test_historical_fixed_base_is_removed(self) -> None:
        legacy_base_keys = [
            line
            for line in self.workflow.splitlines()
            if line.strip().startswith("BASE_SHA:")
        ]
        self.assertEqual(legacy_base_keys, [])
        self.assertNotIn("f4594e48a7689ca5cc6c5a9ca467adbbc98c95f3", self.workflow)
        self.assertIn("PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}", self.workflow)
        self.assertIn('base="${PR_BASE_SHA:-}"'.replace("\\$", "$"), self.workflow)
        self.assertIn('git merge-base --is-ancestor "$base" HEAD', self.workflow)
        self.assertIn('test "$(git merge-base "$base" HEAD)" = "$base"', self.workflow)
        self.assertIn('git diff --check "$base" HEAD', self.workflow)

    def test_trigger_covers_adapter_and_inherited_application_seams(self) -> None:
        required = (
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

    def test_dual_os_and_existing_qualification_remain(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.workflow)
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)
        self.assertIn("python -m pytest -q tests", self.workflow)
        self.assertIn("python -m acs.selftest", self.workflow)
        self.assertIn("python run_accessible_chess.py --diagnostic", self.workflow)
        self.assertIn("tests.test_v2_windows_book_board_adapter_workflow", self.workflow)
        self.assertIn("tests.test_v2_windows_book_board_adapter", self.workflow)
        self.assertIn("tests.test_v2_book_board_workflow", self.workflow)


if __name__ == "__main__":
    unittest.main()
