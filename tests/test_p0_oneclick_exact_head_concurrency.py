from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "p0-user-oneclick-portable-launcher.yml"


class P0OneClickExactHeadConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_concurrency_is_scoped_to_exact_candidate_identity(self) -> None:
        self.assertIn(
            "group: p0-user-oneclick-portable-launcher-"
            "${{ github.event.pull_request.number || github.ref }}-"
            "${{ github.event.pull_request.head.sha || github.sha }}",
            self.text,
        )
        self.assertNotIn(
            "group: p0-user-oneclick-portable-launcher-${{ github.ref }}\n",
            self.text,
        )

    def test_duplicate_exact_candidate_runs_still_supersede(self) -> None:
        self.assertIn("  cancel-in-progress: true\n", self.text)

    def test_checkout_and_guard_use_same_event_candidate(self) -> None:
        self.assertIn(
            "          ref: ${{ github.event.pull_request.head.sha || github.sha }}\n",
            self.text,
        )
        self.assertIn("      - name: Reject superseded pull-request candidate\n", self.text)
        self.assertIn("        if: ${{ github.event_name == 'pull_request' }}\n", self.text)
        self.assertIn(
            '          $eventSha = \'${{ github.event.pull_request.head.sha }}\'\n',
            self.text,
        )
        self.assertIn(
            '          git fetch --no-tags origin "refs/pull/${{ github.event.pull_request.number }}/head"\n',
            self.text,
        )
        self.assertIn("          $liveSha = (git rev-parse FETCH_HEAD).Trim()\n", self.text)
        self.assertIn("          if ($liveSha -ne $eventSha) {\n", self.text)
        self.assertIn("          Write-Host 'P0_ONECLICK_EXACT_HEAD=PASS'\n", self.text)

    def test_stale_head_guard_runs_before_expensive_setup(self) -> None:
        guard = self.text.index("      - name: Reject superseded pull-request candidate\n")
        setup = self.text.index("      - name: Setup exact Python\n")
        build = self.text.index("      - name: Build native x64 launcher without CRT\n")
        self.assertLess(guard, setup)
        self.assertLess(guard, build)


if __name__ == "__main__":
    unittest.main()
