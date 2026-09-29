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
        marker = "protected_paths=("
        start = self.workflow.index(marker)
        end = self.workflow.index("\n          )", start)
        protected = self.workflow[start:end]
        for path in (
            ".github/workflows/v2-book-progress-production-repair.yml",
            "acs/book_progress_store.py",
        ):
            with self.subTest(path=path):
                self.assertIn(f"'{path}'", protected)
        self.assertNotIn(
            "'.github/workflows/v2-composition-publication-boundary.yml'",
            protected,
        )
        self.assertIn('product_blob="$(git rev-parse "$product:$path")"', self.workflow)
        self.assertIn('candidate_blob="$(git rev-parse "HEAD:$path")"', self.workflow)
        self.assertIn(
            "Recovery authority drift requires a dedicated successor gate",
            self.workflow,
        )

    def test_publication_authority_is_an_exact_atomic_pair(self) -> None:
        self.assertIn(
            "publication_path='.github/workflows/v2-composition-publication-boundary.yml'",
            self.workflow,
        )
        self.assertIn(
            "publication_contract='tests/test_composition_publication_boundary_workflow.py'",
            self.workflow,
        )
        self.assertIn(
            "successor_publication='653d4c8a252a258f580900b7f6f470f14e2899ed'",
            self.workflow,
        )
        self.assertIn(
            "successor_contract='cee4f2de715b26bee6d3b5a1b511927ee42207fc'",
            self.workflow,
        )
        self.assertIn(
            'test "$candidate_publication" = "$product_publication"',
            self.workflow,
        )
        self.assertIn(
            'test "$candidate_contract" = "$product_contract"',
            self.workflow,
        )
        self.assertIn(
            'test "$candidate_publication" = "$successor_publication"',
            self.workflow,
        )
        self.assertIn(
            'test "$candidate_contract" = "$successor_contract"',
            self.workflow,
        )
        self.assertIn(
            "Publication authority pair drift requires an exact reviewed successor",
            self.workflow,
        )
        self.assertIn(
            "BOOKS_RECOVERY_PUBLICATION_SUCCESSOR=EXACT",
            self.workflow,
        )

    def test_missing_publication_contract_sentinel_is_deterministic(self) -> None:
        self.assertIn("blob_or_missing() {", self.workflow)
        self.assertIn(
            'object_type="$(git cat-file -t "$spec" 2>/dev/null || true)"',
            self.workflow,
        )
        self.assertIn(
            "elif test \"$object_type\" = 'blob'; then",
            self.workflow,
        )
        self.assertIn(
            'product_contract="$(blob_or_missing "$product:$publication_contract")"',
            self.workflow,
        )
        self.assertIn(
            'candidate_contract="$(blob_or_missing "HEAD:$publication_contract")"',
            self.workflow,
        )
        self.assertIn(
            "Publication authority path must resolve to a blob",
            self.workflow,
        )
        self.assertNotIn(
            'git rev-parse "$product:$publication_contract" 2>/dev/null || printf',
            self.workflow,
        )
        self.assertNotIn(
            'git rev-parse "HEAD:$publication_contract" 2>/dev/null || printf',
            self.workflow,
        )

    def test_publication_contract_is_a_trigger(self) -> None:
        self.assertIn(
            "- 'tests/test_composition_publication_boundary_workflow.py'",
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
