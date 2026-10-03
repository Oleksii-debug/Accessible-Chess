from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "v2-markdown-semantic-lists-convergence.yml"
STAGE1_FILES = (
    "acs/stage1_release_ui_core.py",
    "acs/webapp_keymap_core.py",
)


class V2MarkdownSemanticListsWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_windows_rematerializes_current_head_bytes_without_historical_blob_pin(self) -> None:
        restore = "git checkout-index --force -- acs/stage1_release_ui_core.py acs/webapp_keymap_core.py"
        self.assertGreaterEqual(self.workflow.count(restore), 2)
        self.assertNotIn("b8586a26b9ab20c3d3ec0b0a3dbbbd53e38e94e6", self.workflow)
        for path in STAGE1_FILES:
            with self.subTest(path=path):
                self.assertIn(
                    f'test "$(git hash-object --no-filters {path})" = "$(git rev-parse HEAD:{path})"',
                    self.workflow,
                )

    def test_regression_is_triggered_compiled_and_executed(self) -> None:
        test_path = "tests/test_v2_markdown_semantic_lists_workflow.py"
        self.assertIn(test_path, self.workflow)
        self.assertIn(
            "python -m py_compile acs/book_text_import.py tests/test_v2_book_text_import.py "
            "tests/test_v2_markdown_semantic_lists.py tests/test_v2_markdown_semantic_lists_workflow.py",
            self.workflow,
        )
        self.assertIn(
            "python -m unittest -v tests.test_v2_markdown_semantic_lists_workflow",
            self.workflow,
        )

    def test_markdown_semantic_and_broad_qualification_remain_fail_closed(self) -> None:
        required = (
            "tests.test_v2_book_text_import",
            "tests.test_v2_markdown_semantic_lists",
            "tests.test_bookdocument",
            "tests.test_book_index",
            "tests.test_bookreader",
            "tests.test_v2_accessible_book_core",
            "python -m unittest discover -s tests -v",
            "python -m pytest -q tests",
            "python -m acs.selftest",
            "python run_accessible_chess.py --diagnostic",
            "python run_accessible_chess_v2.py --diagnostic",
            "os: [ubuntu-22.04, windows-2025]",
        )
        for item in required:
            with self.subTest(item=item):
                self.assertIn(item, self.workflow)


if __name__ == "__main__":
    unittest.main()
