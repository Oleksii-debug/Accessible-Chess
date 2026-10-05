from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "training-progress-durability.yml"


class TrainingProgressDurabilityConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_concurrency_is_scoped_to_exact_candidate_identity(self) -> None:
        self.assertIn(
            "group: training-progress-durability-"
            "${{ github.event.pull_request.number || github.ref }}-"
            "${{ github.event.pull_request.head.sha || github.sha }}",
            self.text,
        )
        self.assertNotIn(
            "group: training-progress-durability-"
            "${{ github.event.pull_request.number || github.ref }}\n",
            self.text,
        )

    def test_duplicate_exact_candidate_runs_still_supersede(self) -> None:
        self.assertIn("  cancel-in-progress: true\n", self.text)

    def test_checkout_uses_same_exact_candidate_identity(self) -> None:
        self.assertIn(
            "          ref: ${{ github.event.pull_request.head.sha || github.sha }}\n",
            self.text,
        )

    def test_superseded_pr_head_fails_before_product_tests(self) -> None:
        self.assertIn("      - name: Reject superseded pull-request candidate\n", self.text)
        self.assertIn(
            '          git fetch --no-tags origin "refs/pull/${{ github.event.pull_request.number }}/head"\n',
            self.text,
        )
        self.assertIn('          event_sha="${{ github.event.pull_request.head.sha }}"\n', self.text)
        self.assertIn('          live_sha="$(git rev-parse FETCH_HEAD)"\n', self.text)
        self.assertIn('          test "$live_sha" = "$event_sha" || {\n', self.text)
        self.assertIn("          echo 'TRAINING_PROGRESS_EXACT_HEAD=PASS'\n", self.text)


if __name__ == "__main__":
    unittest.main()
