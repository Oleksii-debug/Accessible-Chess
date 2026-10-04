from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "full-product-convergence-integration-20261004.yml"
BOOKDOCUMENT_WORKFLOW = ROOT / ".github" / "workflows" / "bookdocument-constructor-semantic-integrity.yml"
PGN_POSITION_WORKFLOW = ROOT / ".github" / "workflows" / "pgn-document-new-game-position-integrity.yml"
BOOK_AUTHORITY_WORKFLOW = ROOT / ".github" / "workflows" / "full-product-book-command-authority.yml"


class CurrentMainFullProductConvergenceWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_current_main_is_an_explicit_pull_request_target(self) -> None:
        pull = self.text.index("  pull_request:\n")
        paths = self.text.index("    paths:\n", pull)
        block = self.text[pull:paths]
        self.assertIn("      - main\n", block)
        self.assertIn(
            "      - integration/current-main-windows-apex-reconvergence-20261004-sol\n",
            block,
        )
        self.assertIn("FULL_PRODUCT_EVENT_BASE_ANCESTRY=PASS", self.text)

    def test_current_main_qualification_late_binds_live_pr_base(self) -> None:
        required = (
            "EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            "EVENT_BASE_REF: ${{ github.event.pull_request.base.ref }}",
            'git fetch --no-tags origin "+refs/heads/$event_base_ref:refs/remotes/origin/$event_base_ref"',
            'live_base="$(git rev-parse "origin/$event_base_ref")"',
            'git merge-base --is-ancestor "$event_base" "$live_base"',
            'git merge-base --is-ancestor "$live_base" HEAD',
            'test "$(git merge-base "$live_base" HEAD)" = "$live_base"',
            "FULL_PRODUCT_LIVE_BASE_ANCESTRY=PASS",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)

    def test_current_main_non_pr_qualification_late_binds_live_main(self) -> None:
        required = (
            'elif [ "${GITHUB_REF_NAME:-}" = "integration/current-main-windows-apex-reconvergence-20261004-sol" ]; then',
            "live_base_ref='main'",
            'git fetch --no-tags origin "+refs/heads/$live_base_ref:refs/remotes/origin/$live_base_ref"',
            'live_base="$(git rev-parse "origin/$live_base_ref")"',
            'git merge-base --is-ancestor "$live_base" HEAD',
            'test "$(git merge-base "$live_base" HEAD)" = "$live_base"',
            "FULL_PRODUCT_LIVE_MAIN_NON_PR_ANCESTRY=PASS",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)

    def test_consolidated_completion_push_late_binds_live_parent(self) -> None:
        required = (
            "      - qualification/consolidated-completion-contract-20261004-ooxple7",
            'elif [ "${GITHUB_REF_NAME:-}" = "qualification/consolidated-completion-contract-20261004-ooxple7" ]; then',
            "live_base_ref='fix/portable-package-same-inode-stable-read-20261004-ooxple7'",
            'git fetch --no-tags origin "+refs/heads/$live_base_ref:refs/remotes/origin/$live_base_ref"',
            'git merge-base --is-ancestor "$live_base" HEAD',
            'test "$(git merge-base "$live_base" HEAD)" = "$live_base"',
            "FULL_PRODUCT_LIVE_QUALIFICATION_PARENT_ANCESTRY=PASS",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)

    def test_completion_lens_domains_are_bound_into_one_exact_head_gate(self) -> None:
        required = (
            "tests.test_bookdocument",
            "tests.test_book_bidirectional_semantic_navigation",
            "tests.test_dev1_books_training_webview_atomicity",
            "tests.test_bookreader_snapshot_bounds",
            "tests.test_v2_accessible_book_core",
            "tests.test_v2_book_epub_import",
            "tests.test_v2_html_semantic_lists",
            "tests.test_v2_markdown_semantic_lists",
            "tests.test_v2_book_html_import",
            "tests.test_v2_book_epub_package_contract",
            "tests.test_v2_book_text_import",
            "tests.test_book_index",
            "tests.test_books_semantic_host_bounds",
            "tests.test_acsdb",
            "tests.test_d07_search_semantic_equivalence",
            "tests.test_v2_library_integrity_repair",
            "tests.test_v2_library_presentation_path_privacy",
            "tests.test_d07_library_import_reuse_final_cancel",
            "tests.test_dev1_pgn_webview_projection",
            "tests.test_dev1_pgn_webview_atomicity",
            "tests.test_v2_pgn_nested_comment_recovery",
            "tests.test_v2_pgn_semantic_fidelity",
            "tests.test_pgn_document_context_atomicity",
            "tests.test_pgn_document_setup_fen_integrity",
            "tests.test_pgn_stream_source_binding",
            "tests.test_pgn_concurrent_save",
            "tests.test_dev4_pgn_export_concurrency_security",
            "tests.test_dev4_pgn_export_failure_recovery",
            "tests.test_dev4_pgn_export_path_security",
            "tests.test_dev4_pgn_postcommit_cleanup_atomicity",
            "tests.test_pgn_streaming_import",
            "tests.test_v2_pgn_streaming_export",
            "tests.test_v2_pgn_webview_path_privacy",
            "tests.test_chessbase_integrity",
            "tests.test_dev4_chessbase_symlink_security",
            "tests/js/library_event_boundary_test.js",
            "tests/js/pgn_surface_dom_test.js",
            "tests.test_pgn_open_source_binding",
            "tests.test_pgn_open_identity_fail_closed",
            "tests.test_version2_pgn_commands",
            "tests.test_pgn_document_new_game_position_integrity",
            "tests.test_d08_training_canonical_resume",
            "tests.test_w2_training_progress_crash_recovery",
            "tests.test_training_snapshot_definition_identity_v4",
            "tests.test_settings_corruption_security",
            "tests.test_d06_gametree_snapshot_resume",
            "tests.test_d06_snapshot_canonical_restore",
            "tests.test_settings_private_temp_identity_current",
            "tests.test_settings_postpublication_cleanup_current_main",
            "tests/js/p0_selection_ambiguity_runtime_test.js",
            "tests/js/p0_selection_route_epoch_runtime_test.js",
            "tests.test_p0_final_product_resource_order",
            "tests.test_nvda_p0_contract",
            "tests.test_version2_accessibility_convergence",
            "tests.test_webview2_modern_winforms_accessibility",
            "tests.test_ui_native_menu_recovery",
            "tests.test_accessible_webui",
            "tests.test_version2_import_terminal_ui",
            "tests.test_v2_windows_nvda_file_workflows",
            "tests.test_v2_native_thread_runtime_workflow",
            "tests.test_v2_windows_book_board_adapter",
            "tests.test_p0f_starter_training_canonical_legality",
            "tests.test_full_product_book_command_authority",
            "tests.test_user_library_seed",
            "tests.test_user_library_seed_parent_safety",
            "tests.test_v2_packaged_starter_application",
            "tests.test_owner_delivery_uk_docs",
            "tests.test_version2_package_assembler",
            "tests.test_portable_launcher_contract",
            "tests.test_version2_portable_package",
            "tests.test_version2_package_preflight",
            "tests.test_v2_package_required_resources",
            "tests.test_version2_release_payload",
            "python run_accessible_chess_v2.py --diagnostic",
            "python -m acs.selftest",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)

    def test_high_risk_completion_lens_contracts_run_in_domain_steps(self) -> None:
        def step_block(name: str, next_name: str) -> str:
            start = self.text.index(f"      - name: {name}\n")
            end = self.text.index(f"      - name: {next_name}\n", start)
            return self.text[start:end]

        books = step_block(
            "Books Training semantic and accessibility regressions",
            "Library browser identity, import and privacy regressions",
        )
        library = step_block(
            "Library browser identity, import and privacy regressions",
            "Recovery Settings and writer-race regressions",
        )
        recovery = step_block(
            "Recovery Settings and writer-race regressions",
            "Chess content, semantic reading and malformed-content regressions",
        )
        chess = step_block(
            "Chess content, semantic reading and malformed-content regressions",
            "Windows terminal authority, NVDA file flow and Book to Board regressions",
        )
        accessibility = step_block(
            "Windows terminal authority, NVDA file flow and Book to Board regressions",
            "Owner accessibility and package contracts",
        )

        for fragment in (
            "tests.test_book_bidirectional_semantic_navigation",
            "tests.test_bookreader_snapshot_bounds",
            "tests.test_v2_accessible_book_core",
            "tests.test_v2_book_epub_import",
            "tests.test_v2_html_semantic_lists",
            "tests.test_v2_markdown_semantic_lists",
            "tests.test_dev1_books_training_webview_atomicity",
        ):
            with self.subTest(step="books", fragment=fragment):
                self.assertIn(fragment, books)

        for fragment in (
            "tests.test_d07_search_semantic_equivalence",
            "tests.test_v2_library_integrity_repair",
            "tests.test_v2_library_presentation_path_privacy",
        ):
            with self.subTest(step="library", fragment=fragment):
                self.assertIn(fragment, library)

        for fragment in (
            "tests.test_w2_training_progress_crash_recovery",
            "tests.test_settings_corruption_security",
            "tests.test_d06_gametree_snapshot_resume",
            "tests.test_d06_snapshot_canonical_restore",
        ):
            with self.subTest(step="recovery", fragment=fragment):
                self.assertIn(fragment, recovery)

        for fragment in (
            "tests.test_v2_pgn_nested_comment_recovery",
            "tests.test_v2_pgn_semantic_fidelity",
            "tests.test_pgn_document_context_atomicity",
            "tests.test_pgn_document_setup_fen_integrity",
            "tests.test_pgn_stream_source_binding",
            "tests.test_dev1_pgn_webview_atomicity",
            "tests.test_pgn_concurrent_save",
            "tests.test_dev4_pgn_export_concurrency_security",
            "tests.test_dev4_pgn_export_failure_recovery",
            "tests.test_dev4_pgn_export_path_security",
            "tests.test_dev4_pgn_postcommit_cleanup_atomicity",
            "tests.test_pgn_streaming_import",
            "tests.test_v2_pgn_streaming_export",
            "tests.test_v2_pgn_webview_path_privacy",
            "tests.test_chessbase_integrity",
            "tests.test_dev4_chessbase_symlink_security",
        ):
            with self.subTest(step="chess", fragment=fragment):
                self.assertIn(fragment, chess)

        for fragment in (
            "tests.test_nvda_p0_contract",
            "tests.test_version2_accessibility_convergence",
            "tests.test_webview2_modern_winforms_accessibility",
            "tests.test_ui_native_menu_recovery",
            "tests.test_accessible_webui",
        ):
            with self.subTest(step="accessibility", fragment=fragment):
                self.assertIn(fragment, accessibility)

    def test_successor_workflow_authorities_retrigger_whole_product_gate(self) -> None:
        for path in (
            ".github/workflows/training-snapshot-definition-identity-v4.yml",
            ".github/workflows/pgn-open-source-binding.yml",
            ".github/workflows/pgn-command-single-session-toctou.yml",
            ".github/workflows/pgn-document-new-game-position-integrity.yml",
            ".github/workflows/v2-native-thread-runtime.yml",
            ".github/workflows/v2-windows-book-board-adapter.yml",
            ".github/workflows/version2-windows-composition.yml",
            ".github/workflows/w3-p0f-starter-books-training.yml",
            ".github/workflows/current-user-library-seed.yml",
            ".github/workflows/full-product-book-command-authority.yml",
            ".github/workflows/p0-dynamic-selection-executable.yml",
            ".github/workflows/p0-user-oneclick-portable-launcher.yml",
            ".github/workflows/integration-owner-delivery-uk-docs-current.yml",
            ".github/workflows/w6-v2-package-assembler.yml",
            ".github/workflows/w6-v2-package-preflight-current-runtime.yml",
            ".github/workflows/w6-v2-release-payload-current-assembler.yml",
            ".github/workflows/books-semantic-durable-board-convergence.yml",
            ".github/workflows/v2-accessible-book-core.yml",
            ".github/workflows/v2-book-epub-semantic-ingress.yml",
            ".github/workflows/v2-markdown-semantic-lists-convergence.yml",
            ".github/workflows/d06-pgn-nested-comment-recovery.yml",
            ".github/workflows/d06-pgn-semantic-fidelity.yml",
            ".github/workflows/pgn-context-atomicity.yml",
            ".github/workflows/v2-pgn-stream-source-binding.yml",
            ".github/workflows/w2-training-progress-windows-missing-parent.yml",
            ".github/workflows/v2-windows-nvda-ui.yml",
            ".github/workflows/integration-accessibility-successors.yml",
            ".github/workflows/d01-books-training-ui-integration.yml",
            ".github/workflows/d01-pgn-workspace-webview.yml",
            ".github/workflows/d06-gametree-snapshot-resume.yml",
            ".github/workflows/d06-snapshot-canonical-restore.yml",
            ".github/workflows/d06-pgn-streaming-import.yml",
            ".github/workflows/d06-pgn-streaming-export.yml",
            ".github/workflows/v2-library-integrity-repair.yml",
            ".github/workflows/v2-library-acsdb-search-v4.yml",
            ".github/workflows/settings-save-lock-and-temp-identity.yml",
            ".github/workflows/windows-stage1-webview-build.yml",
        ):
            with self.subTest(path=path):
                self.assertIn(f"      - '{path}'", self.text)

    def test_narrow_owner_gates_are_safe_on_whole_product_main_rollup(self) -> None:
        bookdocument = BOOKDOCUMENT_WORKFLOW.read_text(encoding="utf-8")
        pgn_position = PGN_POSITION_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("BOOKDOCUMENT_TOPOLOGY=BOUNDED_OWNER_SUCCESSOR", bookdocument)
        self.assertIn("BOOKDOCUMENT_TOPOLOGY=WHOLE_PRODUCT_COMPOSITION", bookdocument)
        self.assertIn("[ \"$base_ref\" = 'main' ]", bookdocument)
        self.assertIn("71a4ac74de61de10967284b7a1908534b5384259", bookdocument)
        self.assertIn("f8abeb20819df2776e82d1bf5f9007fc12cb31d6", bookdocument)

        self.assertIn("PGN_POSITION_TOPOLOGY=BOUNDED_OWNER_SUCCESSOR", pgn_position)
        self.assertIn("PGN_POSITION_TOPOLOGY=WHOLE_PRODUCT_COMPOSITION", pgn_position)
        self.assertIn("[ \"$PR_BASE_REF\" = 'main' ]", pgn_position)
        self.assertIn("bf9e0f28dda8a811845df2c977436ea9523f6be5", pgn_position)
        self.assertIn("c098f028c9e8811a9c40c682ee5abcbb994dbf4c", pgn_position)
        self.assertIn("e7b2e9ebca69b5b13c5a633ca32b125004b35ac4", pgn_position)
        for required in (
            "tests.test_version2_pgn_commands",
            "python -m unittest discover -s tests -v",
            "python -m pytest -q tests",
            "python run_accessible_chess.py --diagnostic",
            "python run_accessible_chess_v2.py --diagnostic",
        ):
            with self.subTest(required=required):
                self.assertIn(required, pgn_position)

    def test_book_command_authority_gate_tracks_reconverged_lineage_without_weakening_contract(self) -> None:
        text = BOOK_AUTHORITY_WORKFLOW.read_text(encoding="utf-8")
        required = (
            "authority_base='4f7485f220f4250cac990aa89f257ebe219e208e'",
            "authority_tip='e4daa1719b310aa66e8e6cc48bdba80a84a5d7de'",
            "whole_product_parent='71cae99b6ee65ff95c29a9ccfd93723bd58d1ec7'",
            'git merge-base --is-ancestor "$authority_tip" HEAD',
            'git merge-base --is-ancestor "$whole_product_parent" HEAD',
            'git diff --exit-code "$authority_tip" HEAD --',
            "tests/test_full_product_book_command_authority.py",
            "BOOK_COMMAND_AUTHORITY_ORIGINAL_SCOPE=PASS",
            "BOOK_COMMAND_AUTHORITY_RECONVERGED_LINEAGE=PASS",
            "BOOK_COMMAND_AUTHORITY_EXECUTABLE_CONTRACT_PRESERVED=PASS",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)

    def test_gate_keeps_dual_os_qualification(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.text)
        self.assertIn("python -m compileall -q acs tests", self.text)


if __name__ == "__main__":
    unittest.main()
