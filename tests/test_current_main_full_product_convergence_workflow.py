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

    def test_current_main_qualification_binds_live_product_apex(self) -> None:
        required = (
            "DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}",
            "CURRENT_PRODUCT_BRANCH: converge/current-pgn-graph-board-review-20261004-c2mbezb",
            'if [ "$event_base_ref" = "$DEFAULT_BRANCH" ]; then',
            'git fetch --no-tags origin "+refs/heads/$CURRENT_PRODUCT_BRANCH:refs/remotes/origin/$CURRENT_PRODUCT_BRANCH"',
            'live_product="$(git rev-parse "origin/$CURRENT_PRODUCT_BRANCH")"',
            'git merge-base --is-ancestor "$live_product" HEAD',
            "FULL_PRODUCT_CURRENT_PRODUCT_ANCESTRY=PASS",
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

    def test_owner_snapshot_successor_push_late_binds_live_parent(self) -> None:
        required = (
            "      - fix/owner-portable-qualification-snapshot-pin-20261004-sol56",
            'elif [ "${GITHUB_REF_NAME:-}" = "fix/owner-portable-qualification-snapshot-pin-20261004-sol56" ]; then',
            "live_base_ref='qualification/owner-portable-candidate-20261004-sol6f2'",
            "FULL_PRODUCT_LIVE_OWNER_SNAPSHOT_PARENT_ANCESTRY=PASS",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)

    def test_equal_sha_release_convergence_late_binds_live_owner_ingress_parent(self) -> None:
        required = (
            "      - integration/owner-equal-sha-release-convergence-20261004-ooxple7",
            "      - fix/owner-w4-windows-path-ingress-20261004-zftrkmo",
            'elif [ "${GITHUB_REF_NAME:-}" = "integration/owner-equal-sha-release-convergence-20261004-ooxple7" ]; then',
            "live_base_ref='fix/owner-w4-windows-path-ingress-20261004-zftrkmo'",
            "FULL_PRODUCT_LIVE_EQUAL_SHA_RELEASE_PARENT_ANCESTRY=PASS",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)

    def test_owner_run_provenance_successor_late_binds_live_equal_sha_parent(self) -> None:
        required = (
            "      - converge/owner-equal-apex-run-provenance-20261004-c2mbezb",
            "      - integration/owner-equal-sha-release-convergence-20261004-ooxple7",
            'elif [ "${GITHUB_REF_NAME:-}" = "converge/owner-equal-apex-run-provenance-20261004-c2mbezb" ]; then',
            "live_base_ref='integration/owner-equal-sha-release-convergence-20261004-ooxple7'",
            "FULL_PRODUCT_LIVE_RUN_PROVENANCE_PARENT_ANCESTRY=PASS",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)

    def test_w4_sound_readback_successor_late_binds_live_provenance_parent(self) -> None:
        required = (
            "      - fix/w4-sound-byte-readback-20261004-sol56",
            "      - converge/owner-equal-apex-run-provenance-20261004-c2mbezb",
            'elif [ "${GITHUB_REF_NAME:-}" = "fix/w4-sound-byte-readback-20261004-sol56" ]; then',
            "live_base_ref='converge/owner-equal-apex-run-provenance-20261004-c2mbezb'",
            "FULL_PRODUCT_LIVE_W4_SOUND_READBACK_PARENT_ANCESTRY=PASS",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)

    def test_owner_release_pgn_successor_late_binds_live_w4_parent(self) -> None:
        required = (
            "      - integration/owner-release-pgn-terminal-convergence-20261004-c2mbezb",
            "      - fix/w4-sound-byte-readback-20261004-sol56",
            'elif [ "${GITHUB_REF_NAME:-}" = "integration/owner-release-pgn-terminal-convergence-20261004-c2mbezb" ]; then',
            "live_base_ref='fix/w4-sound-byte-readback-20261004-sol56'",
            "FULL_PRODUCT_LIVE_OWNER_PGN_CONVERGENCE_PARENT_ANCESTRY=PASS",
            "tests/js/pgn_tree_keyboard_dom_test.js",
            "tests.test_pgn_browser_presentation_lease_required",
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
            "tests.test_bookreader",
            "tests.test_books_progress_backup_recovery_workflow",
            "tests.test_books_training_ui_integration",
            "tests.test_v2_accessible_book_core",
            "tests.test_v2_book_epub_import",
            "tests.test_v2_html_semantic_lists",
            "tests.test_v2_markdown_semantic_lists",
            "tests.test_v2_book_html_import",
            "tests.test_v2_book_epub_package_contract",
            "tests.test_v2_book_text_import",
            "tests.test_book_index",
            "tests.test_books_semantic_host_bounds",
            "tests.test_d08_book_training_contract",
            "tests.test_version2_book_workspace",
            "tests.test_book_board_progress_failure_exact",
            "tests.test_book_reverse_progress_failure_exact",
            "tests.test_acsdb",
            "tests.test_d07_search_semantic_equivalence",
            "tests.test_v2_library_integrity_repair",
            "tests.test_v2_library_presentation_path_privacy",
            "tests.test_d07_library_import_reuse_final_cancel",
            "tests.test_d07_acsdb_migration_atomicity",
            "tests.test_d07_canonical_ingress_current",
            "tests.test_d07_library_import_exact_source_order",
            "tests.test_d07_library_import_start_lock",
            "tests.test_d07_library_import_transaction_ownership",
            "tests.test_d07_library_search_cancellation",
            "tests.test_d07_search_scalar_equivalence",
            "tests.test_w3_library_dirty_replace_confirmation",
            "tests.test_dev1_pgn_webview_projection",
            "tests.test_dev1_pgn_webview_atomicity",
            "tests.test_v2_pgn_nested_comment_recovery",
            "tests.test_pgn_document",
            "tests.test_pgn_service",
            "tests.test_pgn_workspace",
            "tests.test_dev4_pgn_encoding_quality",
            "tests.test_dev4_pgn_truncation_quality",
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
            "tests.test_pgn_document",
            "tests.test_pgn_service",
            "tests.test_pgn_workspace",
            "tests.test_dev4_pgn_encoding_quality",
            "tests.test_dev4_pgn_truncation_quality",
            "tests.test_version2_pgn_real_board_projection",
            "tests.test_w3_unsaved_pgn_open_guard",
            "tests/js/library_event_boundary_test.js",
            "tests/js/pgn_surface_dom_test.js",
            "tests.test_pgn_open_source_binding",
            "tests.test_pgn_open_identity_fail_closed",
            "tests.test_version2_pgn_commands",
            "tests.test_version2_pgn_real_board_projection",
            "tests.test_w3_unsaved_pgn_open_guard",
            "tests.test_pgn_document_new_game_position_integrity",
            "tests.test_d08_training_canonical_resume",
            "tests.test_w2_training_progress_crash_recovery",
            "tests.test_training_snapshot_definition_identity_v4",
            "tests.test_settings_corruption_security",
            "tests.test_d06_gametree_snapshot_resume",
            "tests.test_d06_snapshot_canonical_restore",
            "tests.test_d06_annotation_insertion_persistence_vertical",
            "tests.test_d06_gametree_persistence_vertical",
            "tests.test_d06_real_corpus_recovery",
            "tests.test_d06_v2_gametree_resume_reachability",
            "tests.test_training_authority_convergence",
            "tests.test_version2_upgrade_recovery_integrity",
            "tests.test_version2_upgrade_stale_writer",
            "tests.test_work_v2_shutdown_progress_failure_cleanup",
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
            "tests.test_keybindings",
            "tests.test_keymap_corruption_security",
            "tests.test_v2_remapped_keyboard_routing",
            "tests.test_v2_remapped_keyboard_native_editing",
            "tests.test_stage1_webview2_accessibility_boundary",
            "tests.test_dev1_full_product_accessible_shell",
            "tests.test_full_product_native_menu",
            "tests.test_windows_native_menu_smoke_contract",
            "tests.test_version2_import_terminal_ui",
            "tests.test_v2_windows_nvda_file_workflows",
            "tests.test_v2_native_thread_runtime_workflow",
            "tests.test_v2_windows_book_board_adapter",
            "tests.test_p0f_starter_training_canonical_legality",
            "tests.test_p0f_lawful_starter_bundle",
            "tests.test_p0f_starter_content",
            "tests.test_p0f_starter_structured_examples",
            "tests.test_full_product_book_command_authority",
            "tests.test_user_library_seed",
            "tests.test_user_library_seed_parent_safety",
            "tests.test_v2_packaged_starter_application",
            "tests.test_v2_library_source_catalog",
            "tests.test_owner_delivery_uk_docs",
            "tests.test_stage_p0f_release_content",
            "tests.test_release_preflight_extended_source_hygiene",
            "tests.test_slsa_provenance",
            "tests.test_slsa_provenance_builder_binding",
            "tests.test_version2_package_assembler",
            "tests.test_portable_launcher_contract",
            "tests.test_version2_portable_package",
            "tests.test_version2_package_preflight",
            "tests.test_v2_package_required_resources",
            "tests.test_version2_release_payload",
            "tests.test_whole_product_user_journey",
            "tests.test_stage1_complete_user_flow",
            "tests.test_p0_packaged_acceptance_orchestrator",
            "tests.test_p0_packaged_document_copy_probe",
            "tests.test_p0g_final_product_runtime_reachability",
            "tests.test_p0g_packaged_hotkey_result_probe",
            "tests.test_windows_unicode_path_portability",
            "tests.test_version2_composition_publication_boundary",
            "tests.test_version2_composition_startup_cleanup_current",
            "tests.test_version2_final_product_composition",
            "tests.test_version2_final_release_binding",
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

        owner = step_block(
            "Owner accessibility and package contracts",
            "Whole product diagnostic",
        )

        for fragment in (
            "tests.test_book_bidirectional_semantic_navigation",
            "tests.test_bookreader_snapshot_bounds",
            "tests.test_v2_accessible_book_core",
            "tests.test_bookreader",
            "tests.test_books_progress_backup_recovery_workflow",
            "tests.test_books_training_ui_integration",
            "tests.test_d08_book_training_contract",
            "tests.test_version2_book_workspace",
            "tests.test_book_board_progress_failure_exact",
            "tests.test_book_reverse_progress_failure_exact",
            "tests.test_v2_book_epub_import",
            "tests.test_v2_html_semantic_lists",
            "tests.test_v2_markdown_semantic_lists",
            "tests.test_dev1_books_training_webview_atomicity",
            "tests.test_p0f_lawful_starter_bundle",
            "tests.test_p0f_starter_content",
            "tests.test_p0f_starter_structured_examples",
        ):
            with self.subTest(step="books", fragment=fragment):
                self.assertIn(fragment, books)

        for fragment in (
            "tests.test_d07_search_semantic_equivalence",
            "tests.test_v2_library_integrity_repair",
            "tests.test_v2_library_presentation_path_privacy",
            "tests.test_v2_library_source_catalog",
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

        for fragment in (
            "tests.test_stage_p0f_release_content",
            "tests.test_release_preflight_extended_source_hygiene",
            "tests.test_slsa_provenance",
            "tests.test_slsa_provenance_builder_binding",
        ):
            with self.subTest(step="owner", fragment=fragment):
                self.assertIn(fragment, owner)

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
            ".github/workflows/p0f-lawful-starter-corpus.yml",
            ".github/workflows/p0f-package-staging.yml",
            ".github/workflows/p0f-packaged-w2-runtime-discovery.yml",
            ".github/workflows/p0f-starter-content.yml",
            ".github/workflows/release-preflight-extended-source-hygiene.yml",
            ".github/workflows/slsa-provenance-v1.yml",
            ".github/workflows/current-user-library-seed.yml",
            ".github/workflows/full-product-book-command-authority.yml",
            ".github/workflows/p0-dynamic-selection-executable.yml",
            ".github/workflows/p0-user-oneclick-portable-launcher.yml",
            ".github/workflows/p0-packaged-acceptance-orchestrator.yml",
            ".github/workflows/p0-packaged-document-copy-probe-contract.yml",
            ".github/workflows/p0g-final-product-runtime-reachability.yml",
            ".github/workflows/p0g-packaged-hotkey-result-probe-contract.yml",
            ".github/workflows/windows-unicode-path-portability.yml",
            ".github/workflows/integration-owner-delivery-uk-docs-current.yml",
            ".github/workflows/w6-v2-package-assembler.yml",
            ".github/workflows/w6-v2-package-preflight-current-runtime.yml",
            ".github/workflows/w6-v2-release-payload-current-assembler.yml",
            ".github/workflows/books-semantic-durable-board-convergence.yml",
            ".github/workflows/books-progress-backup-recovery.yml",
            ".github/workflows/integration-book-progress-successors.yml",
            ".github/workflows/d08-book-training-contract.yml",
            ".github/workflows/v2-book-board-workflow.yml",
            ".github/workflows/v2-book-progress-production-repair.yml",
            ".github/workflows/v2-accessible-book-core.yml",
            ".github/workflows/v2-book-epub-semantic-ingress.yml",
            ".github/workflows/v2-markdown-semantic-lists-convergence.yml",
            ".github/workflows/d06-pgn-nested-comment-recovery.yml",
            ".github/workflows/d06-pgn-semantic-fidelity.yml",
            ".github/workflows/pgn-context-atomicity.yml",
            ".github/workflows/v2-pgn-stream-source-binding.yml",
            ".github/workflows/w2-training-progress-windows-missing-parent.yml",
            ".github/workflows/v2-windows-nvda-ui.yml",
            ".github/workflows/current-combined-hotkey-accessibility.yml",
            ".github/workflows/d01-full-product-native-menu.yml",
            ".github/workflows/p0-native-menubar-uia-runtime.yml",
            ".github/workflows/integration-accessibility-successors.yml",
            ".github/workflows/d01-books-training-ui-integration.yml",
            ".github/workflows/d01-pgn-workspace-webview.yml",
            ".github/workflows/d06-gametree-snapshot-resume.yml",
            ".github/workflows/d06-snapshot-canonical-restore.yml",
            ".github/workflows/d06-real-corpus-recovery.yml",
            ".github/workflows/d06-pgn-streaming-import.yml",
            ".github/workflows/d06-pgn-streaming-export.yml",
            ".github/workflows/v2-library-integrity-repair.yml",
            ".github/workflows/d07-library-export.yml",
            ".github/workflows/integration-library-browser-contract-successor.yml",
            ".github/workflows/v2-library-acsdb-search-v4.yml",
            ".github/workflows/settings-save-lock-and-temp-identity.yml",
            ".github/workflows/windows-stage1-webview-build.yml",
            ".github/workflows/w3-unsaved-pgn-open-guard.yml",
            ".github/workflows/v2-windows-pgn-save-action-reachability.yml",
            ".github/workflows/v2-composition-publication-boundary.yml",
            ".github/workflows/v2-composition-startup-cleanup.yml",
            ".github/workflows/whole-product-integration-preview.yml",
        ):
            with self.subTest(path=path):
                self.assertIn(f"      - '{path}'", self.text)

    def test_owner_final_authorities_retrigger_and_execute_in_whole_product_gate(self) -> None:
        retriggers = (
            ".github/workflows/owner-library-seed-ingress.yml",
            ".github/workflows/owner-oneclick-finalizer-contract.yml",
            ".github/workflows/owner-oneclick-from-w4.yml",
            ".github/workflows/owner-portable-final-candidate-contract.yml",
            ".github/workflows/w4-v2-p0-fresh-windows-candidate.yml",
            "scripts/build_owner_portable_candidate.py",
            "scripts/materialize_owner_library_seed.py",
            "scripts/verify_owner_w4_run_provenance.py",
            "packaging/portable_launcher.c",
        )
        for path in retriggers:
            with self.subTest(path=path):
                self.assertIn(f"      - \'{path}\'", self.text)

        contracts = (
            "tests.test_owner_portable_candidate",
            "tests.test_owner_portable_candidate_stable_reads",
            "tests.test_materialize_owner_library_seed",
            "tests.test_owner_oneclick_from_w4_workflow",
            "tests.test_verify_owner_w4_run_provenance",
            "tests.test_w4_v2_p0_fresh_candidate_workflow",
        )
        for contract in contracts:
            with self.subTest(contract=contract):
                self.assertIn(contract, self.text)

    def test_w4_current_readback_retriggers_and_executes_in_whole_product_gate(self) -> None:
        for path in (
            ".github/workflows/w4-v2-p0-candidate-artifact-readback.yml",
            ".github/workflows/w4-candidate-artifact-readback-workflow-contract.yml",
            "scripts/verify_w4_current_candidate_artifact.py",
            "scripts/verify_w4_sound_inventory.py",
        ):
            with self.subTest(path=path):
                self.assertIn(f"      - '{path}'", self.text)
        for contract in (
            "tests.test_w4_candidate_artifact_readback_workflow",
            "tests.test_w4_sound_inventory_workflow_binding",
            "tests.test_verify_w4_current_candidate_artifact",
            "tests.test_verify_w4_sound_inventory",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, self.text)

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
