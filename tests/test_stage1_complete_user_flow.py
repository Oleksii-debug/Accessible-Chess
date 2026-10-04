from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.stage1_release_ui import (
    Stage1ReleaseAccessibleChessAPI,
    complete_user_flow_diagnostic,
)


class Stage1CompleteUserFlowTests(unittest.TestCase):
    def make_api(self) -> Stage1ReleaseAccessibleChessAPI:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return Stage1ReleaseAccessibleChessAPI(
            keymap_path=Path(temp.name) / "keymap.json"
        )

    def test_complete_stage1_sequence_is_coherent(self):
        result = complete_user_flow_diagnostic(self.make_api())
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["boardCells"], 64)
        self.assertTrue(all(result["checks"].values()), result["checks"])

    def test_fen_position_and_square_errors_never_expose_python_exception_text(self):
        api = self.make_api()
        for result in (
            api.set_fen("bad"),
            api.set_position_text("bad", "w"),
            api.activate_square("z9"),
        ):
            self.assertFalse(result["ok"])
            message = str(result["announcement"])
            self.assertNotIn("ValueError", message)
            self.assertNotIn("Traceback", message)
            self.assertNotIn("Exception", message)
            self.assertLessEqual(len(message), 80)

    def test_invalid_editor_and_fen_are_atomic(self):
        api = self.make_api()
        api.make_move("e4")
        before = api.board.fen()
        self.assertFalse(api.set_fen("not a fen")["ok"])
        self.assertEqual(api.board.fen(), before)
        self.assertFalse(api.set_position_text("broken", "w")["ok"])
        self.assertEqual(api.board.fen(), before)

    def test_release_launcher_uses_hardened_api(self):
        source = (
            Path(__file__).resolve().parents[1] / "run_accessible_chess.py"
        ).read_text(encoding="utf-8")
        self.assertIn("acs.stage1_release_ui", source)
        self.assertNotIn("from acs.webapp_keymap import main", source)


if __name__ == "__main__":
    unittest.main()
