from __future__ import annotations

import unittest
from pathlib import Path


class BooksProgressBackupRecoveryWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "books-progress-backup-recovery.yml"
        ).read_text(encoding="utf-8")

    def test_current_product_must_be_exact_candidate_ancestor(self) -> None:
        self.assertIn(
            'git merge-base --is-ancestor "$product" HEAD',
            self.workflow,
        )
        self.assertIn(
            'test "$(git merge-base "$product" HEAD)" = "$product"',
            self.workflow,
        )

    def test_historical_exact_nine_file_delta_is_not_required_of_descendants(self) -> None:
        self.assertNotIn('test "${actual[*]}" = "${wanted[*]}"', self.workflow)
        self.assertNotIn("mapfile -t actual < <(git diff --name-only", self.workflow)

    def test_recovery_exclusive_authorities_remain_locked_to_product(self) -> None:
        protected = (
            ".github/workflows/v2-book-progress-production-repair.yml",
            ".github/workflows/v2-composition-publication-boundary.yml",
            "acs/book_progress_store.py",
        )
        for path in protected:
            with self.subTest(path=path):
                self.assertIn(f"'{path}'", self.workflow)

        self.assertIn('product_blob="$(git rev-parse "$product:$path")"', self.workflow)
        self.assertIn('candidate_blob="$(git rev-parse "HEAD:$path")"', self.workflow)
        self.assertIn(
            "Recovery authority drift requires a dedicated successor gate",
            self.workflow,
        )

    def test_shared_composition_files_are_regressed_not_blob_frozen(self) -> None:
        marker = "protected_paths=("
        start = self.workflow.index(marker)
        end = self.workflow.index("\n          )", start)
        protected_block = self.workflow[start:end]
        for path in (
            "acs/version2_application.py",
            "acs/version2_release_app.py",
            "acs/version2_windows_native_dialog_ownership.py",
        ):
            with self.subTest(path=path):
                self.assertNotIn(path, protected_block)
                self.assertIn(path, self.workflow)

        self.assertIn("tests.test_version2_application", self.workflow)
        self.assertIn("tests.test_v2_native_dialog_language", self.workflow)
        self.assertIn("tests.test_v2_book_progress_store", self.workflow)
        self.assertIn("tests.test_v2_book_progress_store_production", self.workflow)
        self.assertIn("tests.test_book_board_progress_failure_exact", self.workflow)

    def test_scope_and_whitespace_still_fail_closed(self) -> None:
        self.assertIn('git diff --check "$product" HEAD', self.workflow)
        self.assertIn("set -euo pipefail", self.workflow)


if __name__ == "__main__":
    unittest.main()
