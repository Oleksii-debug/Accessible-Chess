from __future__ import annotations

import unittest
from pathlib import Path


class Version2FormatsCanonicalNullMoveGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "version2-formats-integration.yml"
        ).read_text(encoding="utf-8")

    def test_only_exact_reviewed_nullmove_production_blobs_are_accepted(self) -> None:
        self.assertIn(
            "CANONICAL_NULLMOVE_CHESSCORE_BLOB: 8351a91b40bc344e512688c481c762ee0c5b0454",
            self.workflow,
        )
        self.assertIn(
            "CANONICAL_NULLMOVE_DECODER_BLOB: 25073fa9f06d195ad0dbb06c40599cd99359a188",
            self.workflow,
        )
        self.assertIn(
            'test "$head_chesscore_blob" = "$CANONICAL_NULLMOVE_CHESSCORE_BLOB"',
            self.workflow,
        )
        self.assertIn(
            'test "$head_decoder_blob" = "$CANONICAL_NULLMOVE_DECODER_BLOB"',
            self.workflow,
        )

    def test_unreviewed_chesscore_drift_still_fails_closed(self) -> None:
        self.assertIn("Unreviewed chesscore drift in Formats candidate", self.workflow)
        self.assertIn(
            'if [ "$head_chesscore_blob" != "$base_chesscore_blob" ]; then',
            self.workflow,
        )

    def test_other_release_seams_remain_protected(self) -> None:
        for path in (
            "acs/stage1_release_ui.py",
            "acs/stage1_release_ui_core.py",
            "acs/webapp_keymap_core.py",
            "web/stage1_board_actions.js",
            "web/stage1_release_bootstrap.js",
        ):
            with self.subTest(path=path):
                self.assertIn(path, self.workflow)

        self.assertIn("protected_other=", self.workflow)
        self.assertNotIn(
            "grep -E '^(acs/chesscore\\\\.py|",
            self.workflow,
        )

    def test_gate_itself_runs_in_focused_semantic_journey(self) -> None:
        self.assertIn(
            "tests.test_version2_formats_canonical_nullmove_gate",
            self.workflow,
        )


if __name__ == "__main__":
    unittest.main()
