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

    def test_current_product_is_exact_candidate_ancestor(self) -> None:
        self.assertIn(
            'git merge-base --is-ancestor "$product" HEAD',
            self.workflow,
        )
        self.assertIn(
            'test "$(git merge-base "$product" HEAD)" = "$product"',
            self.workflow,
        )
        self.assertIn('git diff --check "$product" HEAD', self.workflow)

    def test_historical_exact_five_file_delta_is_not_required_of_descendants(self) -> None:
        self.assertNotIn("expected_paths=(", self.workflow)
        self.assertNotIn('test "${actual[*]}" = "${wanted[*]}"', self.workflow)
        self.assertNotIn("STACKED_RECOVERY_PARENT", self.workflow)
        self.assertNotIn(
            "fix/book-progress-backup-recovery-20260927",
            self.workflow,
        )

    def test_epub_exclusive_parser_authority_is_locked_to_product(self) -> None:
        marker = "protected_paths=("
        start = self.workflow.index(marker)
        end = self.workflow.index("\n          )", start)
        protected_block = self.workflow[start:end]
        self.assertIn("'acs/book_epub_import.py'", protected_block)
        self.assertIn(
            'product_blob="$(git rev-parse "$product:$path")"',
            self.workflow,
        )
        self.assertIn(
            'candidate_blob="$(git rev-parse "HEAD:$path")"',
            self.workflow,
        )
        self.assertIn(
            "EPUB authority drift requires a dedicated successor gate",
            self.workflow,
        )

    def test_shared_application_and_dialog_files_are_regressed_not_blob_frozen(self) -> None:
        marker = "protected_paths=("
        start = self.workflow.index(marker)
        end = self.workflow.index("\n          )", start)
        protected_block = self.workflow[start:end]
        for path in (
            "acs/version2_application.py",
            "acs/version2_windows_native_dialog_ownership.py",
        ):
            with self.subTest(path=path):
                self.assertNotIn(path, protected_block)
                self.assertIn(path, self.workflow)

        for suite in (
            "tests.test_version2_epub_application_reachability",
            "tests.test_v2_book_epub_import",
            "tests.test_v2_native_dialog_language",
            "tests.test_version2_application",
        ):
            with self.subTest(suite=suite):
                self.assertIn(suite, self.workflow)

    def test_contract_test_is_part_of_trigger_compile_and_focused_gate(self) -> None:
        self.assertGreaterEqual(
            self.workflow.count("tests/test_epub_application_reachability_workflow.py"),
            2,
        )
        self.assertIn(
            "tests.test_epub_application_reachability_workflow",
            self.workflow,
        )

    def test_no_historical_product_sha_is_pinned(self) -> None:
        self.assertNotIn(
            "be3a1a4a0e5561756337d46c54ea12ba6a463b4e",
            self.workflow,
        )
        self.assertNotIn(
            "508bb18db2b12407388be06c577d2eb6e48a38ae",
            self.workflow,
        )


if __name__ == "__main__":
    unittest.main()
