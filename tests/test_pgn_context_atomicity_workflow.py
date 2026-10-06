from __future__ import annotations

from pathlib import Path
import unittest


class PgnContextAtomicityWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "pgn-context-atomicity.yml"
        ).read_text(encoding="utf-8")

    def test_pull_requests_bind_scope_to_their_exact_base(self) -> None:
        self.assertIn(
            "base='${{ github.event.pull_request.base.sha }}'",
            self.workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$base" HEAD', self.workflow)
        self.assertIn(
            'test "$(git merge-base "$base" HEAD)" = "$base"',
            self.workflow,
        )
        self.assertIn('git diff --check "$base" HEAD', self.workflow)

    def test_historical_parent_and_branch_are_not_descendant_authority(self) -> None:
        self.assertNotIn(
            "450f1cc2ccf786cd07c7b41853e449fc12740b19",
            self.workflow,
        )
        self.assertNotIn(
            "integrate/w5-pgn-integrity-20260911-n9p3",
            self.workflow,
        )
        self.assertNotIn("PARENT:", self.workflow)

    def test_gate_does_not_require_every_future_descendant_to_match_old_scope(self) -> None:
        self.assertNotIn('unexpected="$(printf', self.workflow)
        self.assertNotIn("Unexpected child-scope paths:", self.workflow)
        self.assertIn(
            "Frozen Stage 1 / strict-release contamination detected",
            self.workflow,
        )

    def test_core_integrity_oracles_remain_byte_locked(self) -> None:
        marker = "protected_paths=("
        start = self.workflow.index(marker)
        end = self.workflow.index("\n          )", start)
        protected = self.workflow[start:end]
        self.assertIn(
            "'tests/test_pgn_document_context_atomicity.py'",
            protected,
        )
        self.assertIn(
            "'tests/test_pgn_document_setup_fen_integrity.py'",
            protected,
        )
        self.assertIn(
            'base_blob="$(git rev-parse "$base:$path")"',
            self.workflow,
        )
        self.assertIn(
            'candidate_blob="$(git rev-parse "HEAD:$path")"',
            self.workflow,
        )

    def test_exact_head_checkout_and_current_product_target_are_explicit(self) -> None:
        self.assertIn(
            "branches:\n      - work/full-product-teacher-education-reachability-20260911",
            self.workflow,
        )
        self.assertIn(
            "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
            self.workflow,
        )
        self.assertIn(
            "ref: ${{ github.event.pull_request.head.sha || github.sha }}",
            self.workflow,
        )

    def test_contract_test_runs_in_compile_and_focused_gate(self) -> None:
        self.assertGreaterEqual(
            self.workflow.count("tests/test_pgn_context_atomicity_workflow.py"),
            2,
        )
        self.assertIn(
            "tests.test_pgn_context_atomicity_workflow",
            self.workflow,
        )

    def test_dual_os_and_full_qualification_are_retained(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.workflow)
        self.assertIn("tests.test_pgn_document_context_atomicity", self.workflow)
        self.assertIn("tests.test_pgn_document_setup_fen_integrity", self.workflow)
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)
        self.assertIn("python -m pytest -q tests", self.workflow)
        self.assertIn("python -m acs.selftest", self.workflow)
        self.assertIn("python run_accessible_chess.py --diagnostic", self.workflow)


if __name__ == "__main__":
    unittest.main()
