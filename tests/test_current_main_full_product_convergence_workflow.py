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

    def test_completion_lens_domains_are_bound_into_one_exact_head_gate(self) -> None:
        required = (
            "tests.test_bookdocument",
            "tests.test_v2_book_html_import",
            "tests.test_v2_book_text_import",
            "tests.test_book_index",
            "tests.test_pgn_open_source_binding",
            "tests.test_pgn_open_identity_fail_closed",
            "tests.test_version2_pgn_commands",
            "tests.test_d08_training_canonical_resume",
            "tests.test_training_snapshot_definition_identity_v4",
            "tests.test_version2_import_terminal_ui",
            "tests.test_v2_windows_nvda_file_workflows",
            "tests.test_v2_native_thread_runtime_workflow",
            "tests.test_v2_windows_book_board_adapter",
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
            ".github/workflows/v2-native-thread-runtime.yml",
            ".github/workflows/v2-windows-book-board-adapter.yml",
            ".github/workflows/version2-windows-composition.yml",
        ):
            with self.subTest(path=path):
                self.assertIn(f"      - '{path}'", self.text)

    def test_gate_keeps_dual_os_qualification(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.text)
        self.assertIn("python -m compileall -q acs tests", self.text)


if __name__ == "__main__":
    unittest.main()
