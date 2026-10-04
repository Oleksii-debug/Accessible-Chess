from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "full-product-convergence-integration-20261004.yml"


class CurrentMainFullProductConvergenceWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_current_main_is_an_explicit_pull_request_target(self) -> None:
        pull = self.text.index("  pull_request:\n")
        paths = self.text.index("    paths:\n", pull)
        block = self.text[pull:paths]
        self.assertIn("      - main\n", block)
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

    def test_completion_lens_domains_are_bound_into_one_exact_head_gate(self) -> None:
        required = (
            "tests.test_bookdocument",
            "tests.test_v2_book_html_import",
            "tests.test_v2_book_text_import",
            "tests.test_book_index",
            "tests.test_pgn_open_source_binding",
            "tests.test_pgn_open_identity_fail_closed",
            "tests.test_version2_pgn_commands",
            "tests.test_pgn_document_new_game_position_integrity",
            "tests.test_d08_training_canonical_resume",
            "tests.test_training_snapshot_definition_identity_v4",
            "tests.test_version2_import_terminal_ui",
            "tests.test_v2_windows_nvda_file_workflows",
            "tests.test_v2_native_thread_runtime_workflow",
            "tests.test_v2_windows_book_board_adapter",
            "tests.test_p0f_starter_training_canonical_legality",
            "tests.test_user_library_seed",
            "tests.test_user_library_seed_parent_safety",
            "tests.test_v2_packaged_starter_application",
            "tests.test_owner_delivery_uk_docs",
            "tests.test_version2_package_assembler",
            "tests.test_version2_package_preflight",
            "tests.test_v2_package_required_resources",
            "tests.test_version2_release_payload",
            "python run_accessible_chess_v2.py --diagnostic",
            "python -m acs.selftest",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)

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
            ".github/workflows/integration-owner-delivery-uk-docs-current.yml",
            ".github/workflows/w6-v2-package-assembler.yml",
            ".github/workflows/w6-v2-package-preflight-current-runtime.yml",
            ".github/workflows/w6-v2-release-payload-current-assembler.yml",
        ):
            with self.subTest(path=path):
                self.assertIn(f"      - '{path}'", self.text)

    def test_gate_keeps_dual_os_qualification(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.text)
        self.assertIn("python -m compileall -q acs tests", self.text)


if __name__ == "__main__":
    unittest.main()
