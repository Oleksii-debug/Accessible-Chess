from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "current-books-keymap-semantic-convergence.yml"


class CurrentBooksKeymapSemanticConvergenceWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_concurrency_is_scoped_to_exact_candidate_identity(self) -> None:
        self.assertIn(
            "group: current-books-keymap-semantic-convergence-"
            "${{ github.event.pull_request.number || github.ref }}-"
            "${{ github.event.pull_request.head.sha || github.sha }}",
            self.text,
        )
        self.assertIn("  cancel-in-progress: true\n", self.text)

    def test_checkout_uses_same_exact_candidate_identity(self) -> None:
        self.assertIn(
            "          ref: ${{ github.event.pull_request.head.sha || github.sha }}\n",
            self.text,
        )

    def test_superseded_pr_head_fails_before_qualification(self) -> None:
        guard = "      - name: Reject superseded pull-request candidate\n"
        ancestry = "      - name: Prove exact candidate and retained source ancestry\n"
        self.assertIn(guard, self.text)
        self.assertIn(ancestry, self.text)
        self.assertLess(self.text.index(guard), self.text.index(ancestry))
        self.assertIn(
            '          event_sha="${{ github.event.pull_request.head.sha }}"\n',
            self.text,
        )
        self.assertIn(
            '          git fetch --no-tags origin "refs/pull/${{ github.event.pull_request.number }}/head"\n',
            self.text,
        )
        self.assertIn('          live_sha="$(git rev-parse FETCH_HEAD)"\n', self.text)
        self.assertIn('          test "$live_sha" = "$event_sha" || {\n', self.text)
        self.assertIn(
            "          echo 'CURRENT_BOOKS_KEYMAP_CONVERGENCE_EXACT_HEAD=PASS'\n",
            self.text,
        )

    def test_workflow_self_qualifies_contract_changes(self) -> None:
        contract_path = "tests/test_current_books_keymap_semantic_convergence_workflow.py"
        self.assertGreaterEqual(self.text.count("      - '" + contract_path + "'\n"), 2)
        self.assertIn(
            "            tests.test_current_books_keymap_semantic_convergence_workflow \\\n",
            self.text,
        )


if __name__ == "__main__":
    unittest.main()
