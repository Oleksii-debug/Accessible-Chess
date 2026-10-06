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

    def test_pull_request_geometry_binds_exact_event_base(self) -> None:
        self.assertIn("event_name='${{ github.event_name }}'", self.workflow)
        self.assertIn(
            "pr_base='${{ github.event.pull_request.base.sha }}'",
            self.workflow,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$product" "$pr_base"',
            self.workflow,
        )
        self.assertIn(
            'test "$(git merge-base "$product" "$pr_base")" = "$product"',
            self.workflow,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$pr_base" HEAD',
            self.workflow,
        )
        self.assertIn(
            'test "$(git merge-base "$pr_base" HEAD)" = "$pr_base"',
            self.workflow,
        )
        self.assertIn('git diff --check "$pr_base" HEAD', self.workflow)
        self.assertIn('EPUB_REACHABILITY_PR_BASE=$pr_base', self.workflow)

    def test_historical_exact_five_file_delta_is_not_required_of_descendants(self) -> None:
        self.assertNotIn("expected_paths=(", self.workflow)
        self.assertNotIn('test "${actual[*]}" = "${wanted[*]}"', self.workflow)
        self.assertNotIn("STACKED_RECOVERY_PARENT", self.workflow)
        self.assertNotIn(
            "fix/book-progress-backup-recovery-20260927",
            self.workflow,
        )

    def test_epub_parser_successor_is_exact_hardening_set_and_application_oracle_stays_locked(self) -> None:
        self.assertIn("parser_path='acs/book_epub_import.py'", self.workflow)
        self.assertIn("parser_test_path='tests/test_v2_book_epub_import.py'", self.workflow)
        self.assertIn(
            "package_contract_test_path='tests/test_v2_book_epub_package_contract.py'",
            self.workflow,
        )
        self.assertIn(
            "package_identity_successor_parser='13d304826900d5ab25586fa7a0de0ee73c25a4b2'",
            self.workflow,
        )
        self.assertIn(
            "package_identity_successor_parser_test='de189065192ca1c0bd30ce1ecec559e8f61cc1bc'",
            self.workflow,
        )
        self.assertIn(
            "package_identity_successor_contract_test='c0904af9b42e5cd50cf2a240145fd3cd0bfde9d2'",
            self.workflow,
        )
        self.assertIn(
            'test "$candidate_parser" = "$package_identity_successor_parser"',
            self.workflow,
        )
        self.assertIn(
            'test "$candidate_parser_test" = "$package_identity_successor_parser_test"',
            self.workflow,
        )
        self.assertIn(
            'test "$candidate_package_contract_test" = "$package_identity_successor_contract_test"',
            self.workflow,
        )
        self.assertIn("EPUB_PACKAGE_IDENTITY_SUCCESSOR=EXACT", self.workflow)
        self.assertIn(
            "EPUB parser/test drift requires an exact reviewed hardening set",
            self.workflow,
        )

        marker = "protected_paths=("
        start = self.workflow.index(marker)
        end = self.workflow.index("\n          )", start)
        protected_block = self.workflow[start:end]
        self.assertIn(
            "'tests/test_version2_epub_application_reachability.py'",
            protected_block,
        )
        self.assertNotIn("'acs/book_epub_import.py'", protected_block)
        self.assertNotIn("'tests/test_v2_book_epub_import.py'", protected_block)
        self.assertNotIn("'tests/test_v2_book_epub_package_contract.py'", protected_block)
        self.assertIn(
            'product_blob="$(git rev-parse "$product:$path")"',
            self.workflow,
        )
        self.assertIn(
            'candidate_blob="$(git rev-parse "HEAD:$path")"',
            self.workflow,
        )

    def test_dc_metadata_successor_is_pinned_and_current_owner_apex_is_qualified(self) -> None:
        pull_request_start = self.workflow.index("  pull_request:")
        pull_request_end = self.workflow.index("    paths:", pull_request_start)
        pull_request_block = self.workflow[pull_request_start:pull_request_end]
        self.assertIn(
            "- converge/owner-apex-docx-bootstrap-generic-win32-20261004-c2mbezb",
            pull_request_block,
        )
        self.assertIn(
            "- converge/book-inline-order-current-owner-apex-20261004-c2mbezb",
            pull_request_block,
        )
        self.assertIn(
            "- converge/book-html-epub-semantics-20261004-c2mbezb",
            pull_request_block,
        )
        self.assertIn(
            "- fix/owner-final-post-upload-apex-freshness-20261004-a7f3c9",
            pull_request_block,
        )
        self.assertIn(
            "dc_metadata_test_path='tests/test_epub_dc_metadata_identity.py'",
            self.workflow,
        )
        self.assertIn(
            "dc_metadata_successor_parser='9eaef49ac61ede991733a53611ac8f933d86990c'",
            self.workflow,
        )
        self.assertIn(
            "dc_metadata_successor_parser_test='2af1740b289d0c231f1618acf9a3c25b409f5fb7'",
            self.workflow,
        )
        self.assertIn(
            "dc_metadata_successor_contract_test='134cf79cf81037f4412b1eacb8e2358ddfe38163'",
            self.workflow,
        )
        self.assertIn(
            "dc_metadata_successor_test='a59c4ac174dba43ce64962c1d780b6e9f49d95a6'",
            self.workflow,
        )
        self.assertIn(
            'test "$candidate_dc_metadata_test" = "$dc_metadata_successor_test"',
            self.workflow,
        )
        self.assertIn("EPUB_DC_METADATA_IDENTITY_SUCCESSOR=EXACT", self.workflow)
        self.assertGreaterEqual(
            self.workflow.count("tests/test_epub_dc_metadata_identity.py"),
            3,
        )
        self.assertIn("tests.test_epub_dc_metadata_identity", self.workflow)


    def test_document_scope_id_uniqueness_successor_is_exactly_pinned(self) -> None:
        self.assertIn(
            "document_id_successor_parser='38d996fe820ff6c5c3e0f085bc87317fbc36a03a'",
            self.workflow,
        )
        self.assertIn(
            "document_id_successor_parser_test='2af1740b289d0c231f1618acf9a3c25b409f5fb7'",
            self.workflow,
        )
        self.assertIn(
            "document_id_successor_contract_test='134cf79cf81037f4412b1eacb8e2358ddfe38163'",
            self.workflow,
        )
        self.assertIn(
            "document_id_successor_test='a47f8b6ac4d82929e9dc751e308d0265d32482cc'",
            self.workflow,
        )
        self.assertIn(
            'test "$candidate_parser" = "$document_id_successor_parser"',
            self.workflow,
        )
        self.assertIn(
            'test "$candidate_dc_metadata_test" = "$document_id_successor_test"',
            self.workflow,
        )
        self.assertIn(
            "EPUB_DOCUMENT_ID_UNIQUENESS_SUCCESSOR=EXACT",
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
            "tests.test_v2_book_epub_package_contract",
            "tests.test_v2_native_dialog_language",
            "tests.test_version2_application",
        ):
            with self.subTest(suite=suite):
                self.assertIn(suite, self.workflow)

    def test_contract_tests_are_part_of_trigger_compile_and_focused_gate(self) -> None:
        self.assertGreaterEqual(
            self.workflow.count("tests/test_epub_application_reachability_workflow.py"),
            2,
        )
        self.assertGreaterEqual(
            self.workflow.count("tests/test_v2_book_epub_package_contract.py"),
            3,
        )
        self.assertIn(
            "tests.test_epub_application_reachability_workflow",
            self.workflow,
        )
        self.assertIn(
            "tests.test_v2_book_epub_package_contract",
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
