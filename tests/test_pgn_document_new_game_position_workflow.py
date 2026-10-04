from __future__ import annotations

import unittest
from pathlib import Path


WORKFLOW = Path(".github/workflows/pgn-document-new-game-position-integrity.yml")


class PgnDocumentNewGamePositionWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_gate_is_convergence_safe_without_weakening_bounded_owner_scope(self) -> None:
        self.assertIn("EVENT_NAME: ${{ github.event_name }}", self.text)
        self.assertIn('if [ "$EVENT_NAME" = "pull_request" ]; then', self.text)
        self.assertIn(
            'git fetch --no-tags origin "+refs/heads/$PR_BASE_REF:refs/remotes/origin/$PR_BASE_REF"',
            self.text,
        )
        self.assertIn('git merge-base --is-ancestor "$live_base" HEAD', self.text)
        self.assertIn('changed="$(git diff --name-only "$live_base"...HEAD', self.text)
        self.assertIn('if [ "$changed" = "$expected" ]; then', self.text)
        self.assertIn("PGN_POSITION_TOPOLOGY=BOUNDED_OWNER_SUCCESSOR", self.text)
        self.assertIn("PGN_POSITION_TOPOLOGY=WHOLE_PRODUCT_COMPOSITION", self.text)
        self.assertIn("[ \"$PR_BASE_REF\" = 'main' ]", self.text)

    def test_gate_pins_canonical_pgn_position_authorities(self) -> None:
        self.assertIn(
            "bf9e0f28dda8a811845df2c977436ea9523f6be5",
            self.text,
        )
        self.assertIn(
            "c098f028c9e8811a9c40c682ee5abcbb994dbf4c",
            self.text,
        )
        self.assertIn(
            "e7b2e9ebca69b5b13c5a633ca32b125004b35ac4",
            self.text,
        )

    def test_gate_runs_each_focused_and_adjacent_regression_once(self) -> None:
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
            with self.subTest(module=module):
                self.assertIn(module, self.text)
        self.assertEqual(
            self.text.count("- name: Run adjacent PGN application and command regressions"),
            1,
        )

    def test_manual_dispatch_does_not_require_pull_request_metadata(self) -> None:
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("else\n            # workflow_dispatch has no pull_request metadata.", self.text)
        self.assertIn("git diff --check HEAD^ HEAD", self.text)
        self.assertIn("PGN_POSITION_TOPOLOGY=MANUAL_EXACT_HEAD", self.text)


if __name__ == "__main__":
    unittest.main()
