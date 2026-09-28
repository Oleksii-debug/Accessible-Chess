from __future__ import annotations

import unittest
from pathlib import Path


class EpubApplicationReachabilityWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "epub-application-reachability.yml"
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

    def test_integrated_epub_owner_must_exist_in_product(self) -> None:
        self.assertIn(
            "minimum_epub_owner='be3a1a4a0e5561756337d46c54ea12ba6a463b4e'",
            self.workflow,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$minimum_epub_owner" "$product"',
            self.workflow,
        )

    def test_historical_exact_five_path_delta_is_not_required(self) -> None:
        self.assertNotIn('test "${actual[*]}" = "${wanted[*]}"', self.workflow)
        self.assertNotIn("mapfile -t actual < <(git diff --name-only", self.workflow)
        self.assertNotIn("STACKED_RECOVERY_PARENT", self.workflow)

    def test_parser_and_epub_acceptance_oracles_remain_locked_to_product(self) -> None:
        protected = (
            "acs/book_epub_import.py",
            "tests/test_v2_book_epub_import.py",
            "tests/test_version2_epub_application_reachability.py",
        )
        marker = "protected_paths=("
        start = self.workflow.index(marker)
        end = self.workflow.index("\n          )", start)
        block = self.workflow[start:end]
        for path in protected:
            with self.subTest(path=path):
                self.assertIn(f"'{path}'", block)

        self.assertIn('product_blob="$(git rev-parse "$product:$path")"', self.workflow)
        self.assertIn('candidate_blob="$(git rev-parse "HEAD:$path")"', self.workflow)
        self.assertIn(
            "EPUB authority drift requires a dedicated successor gate",
            self.workflow,
        )

    def test_shared_application_seams_are_behavior_regressed_not_blob_frozen(self) -> None:
        marker = "protected_paths=("
        start = self.workflow.index(marker)
        end = self.workflow.index("\n          )", start)
        block = self.workflow[start:end]

        for path in (
            "acs/version2_application.py",
            "acs/version2_windows_native_dialog_ownership.py",
            "tests/test_v2_native_dialog_language.py",
        ):
            with self.subTest(path=path):
                self.assertNotIn(path, block)
                self.assertIn(path, self.workflow)

        self.assertIn("tests.test_version2_application", self.workflow)
        self.assertIn("tests.test_v2_native_dialog_language", self.workflow)
        self.assertIn("tests.test_v2_book_progress_store", self.workflow)
        self.assertIn("tests.test_v2_book_progress_store_production", self.workflow)

    def test_scope_and_whitespace_still_fail_closed(self) -> None:
        self.assertIn('git diff --check "$product" HEAD', self.workflow)
        self.assertIn("set -euo pipefail", self.workflow)


if __name__ == "__main__":
    unittest.main()
