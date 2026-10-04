from __future__ import annotations

import unittest
from pathlib import Path


WORKFLOW = Path(".github/workflows/pgn-document-new-game-position-integrity.yml")


class PgnDocumentNewGamePositionWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_gate_is_convergence_safe_for_large_current_main_prs(self) -> None:
        self.assertIn("EVENT_NAME: ${{ github.event_name }}", self.text)
        self.assertIn('if [ "$EVENT_NAME" = "pull_request" ]; then', self.text)
        self.assertIn(
            'git fetch --no-tags origin "+refs/heads/$PR_BASE_REF:refs/remotes/origin/$PR_BASE_REF"',
            self.text,
        )
        self.assertIn('git merge-base --is-ancestor "$live_base" HEAD', self.text)
        self.assertNotIn('changed="$(git diff --name-only', self.text)
        self.assertNotIn('test "$changed" = "$expected"', self.text)
        self.assertNotIn("branches:", self.text)

    def test_gate_pins_canonical_pgn_position_authorities(self) -> None:
        self.assertIn(
            "c098f028c9e8811a9c40c682ee5abcbb994dbf4c",
            self.text,
        )
        self.assertIn(
            "e7b2e9ebca69b5b13c5a633ca32b125004b35ac4",
            self.text,
        )

    def test_gate_runs_focused_and_adjacent_regressions(self) -> None:
        for module in (
            "tests.test_pgn_document_new_game_position_integrity",
            "tests.test_pgn_document_setup_fen_integrity",
            "tests.test_pgn_document_context_atomicity",
            "tests.test_version2_pgn_commands",
            "tests.test_version2_application",
            "tests.test_d06_pgn_roundtrip",
            "tests.test_pgn_concurrent_save",
            "tests.test_pgn_document_new_game_position_workflow",
        ):
            self.assertIn(module, self.text)

    def test_manual_dispatch_does_not_require_pull_request_metadata(self) -> None:
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("else\n            git diff --check HEAD^ HEAD", self.text)


if __name__ == "__main__":
    unittest.main()
