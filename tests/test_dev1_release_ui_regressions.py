from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.stage1_native_menu_router import Stage1NativeMenuActionProxy
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI
from acs.ui_keymap_editor import KeymapEditorModel


class _PartialMenuAPI:
    def __init__(self) -> None:
        self.direct_calls = 0

    def toggle_engine(self):
        self.direct_calls += 1
        return {"ok": True}


class Dev1ReleaseUiRegressionTests(unittest.TestCase):
    def test_native_menu_proxy_accepts_partial_release_seam_but_registry_actions_fail_closed(self) -> None:
        api = _PartialMenuAPI()
        proxy = Stage1NativeMenuActionProxy(api)

        self.assertTrue(proxy.toggle_engine()["ok"])
        self.assertEqual(api.direct_calls, 1)

        with self.assertRaisesRegex(TypeError, "must expose dispatch_action"):
            proxy.undo()
        with self.assertRaisesRegex(TypeError, "must expose dispatch_action"):
            proxy.select_relative_analysis_pv(1)
        self.assertEqual(api.direct_calls, 1)

    def test_dense_rank_file_labels_do_not_flood_generic_localized_navigation_search(self) -> None:
        uk = KeymapEditorModel(lang="uk")
        self.assertEqual(
            [row.action_id for row in uk.rows(query="перейти")],
            ["history.go_to_move"],
        )
        uk_rank = next(row for row in uk.rows() if row.action_id == "board.rank_1")
        uk_file = next(row for row in uk.rows() if row.action_id == "board.file_1")
        self.assertEqual(uk_rank.label, "Горизонталь 1")
        self.assertEqual(uk_file.label, "Вертикаль a")
        self.assertEqual(
            {row.action_id for row in uk.rows(query="горизонталь")},
            {f"board.rank_{number}" for number in range(1, 9)},
        )

        en = KeymapEditorModel(lang="en")
        self.assertEqual(
            [row.action_id for row in en.rows(query="go")],
            ["history.go_to_move"],
        )
        en_rank = next(row for row in en.rows() if row.action_id == "board.rank_1")
        en_file = next(row for row in en.rows() if row.action_id == "board.file_1")
        self.assertEqual(en_rank.label, "Rank 1")
        self.assertEqual(en_file.label, "File a")

    def test_board_controller_projection_uses_canonical_move_generator_not_ui_piece_geometry(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "acs" / "webapp_keymap.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("def _piece_controls_square", source)
        self.assertIn("probe.pseudo_moves(color)", source)

        with tempfile.TemporaryDirectory() as td:
            api = Stage1ReleaseAccessibleChessAPI(keymap_path=Path(td) / "keymap.json")
            api.new_game()
            attackers = api.dispatch_action("board.attackers", "e3")
            self.assertTrue(attackers["ok"])
            # White d2/f2 pawns control e3 diagonally. The e2 pawn advances to
            # e3 but does not attack/control e3, so it must never be projected.
            self.assertIn("d 2", attackers["announcement"])
            self.assertIn("f 2", attackers["announcement"])
            self.assertNotIn("e 2", attackers["announcement"])


if __name__ == "__main__":
    unittest.main()
