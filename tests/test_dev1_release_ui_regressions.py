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

    def test_board_bridge_claims_readiness_only_after_dependencies_and_routes_current_square_centrally(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "web" / "stage1_board_actions.js"
        ).read_text(encoding="utf-8")
        dependency_gate = "typeof baseExecuteAction !== 'function' || typeof apiAction !== 'function'"
        ready_guard = "window.__accessibleChessStage1BoardActions = true;"
        self.assertIn(dependency_gate, source)
        self.assertIn("typeof state !== 'undefined'", source)
        self.assertIn("typeof keymap !== 'undefined'", source)
        self.assertIn("'board.current', 'board.last_captured'", source)
        self.assertLess(source.index(dependency_gate), source.index(ready_guard))
        self.assertLess(source.index("window.renderHelp();"), source.index(ready_guard))

    def test_editable_controls_bypass_global_app_shortcuts_before_prevent_default(self) -> None:
        html = (
            Path(__file__).resolve().parents[1] / "web" / "index.html"
        ).read_text(encoding="utf-8")
        marker = "document.addEventListener('keydown',async e=>{if(capture)return;if(e.target.closest('#board-application'))return;"
        start = html.index(marker)
        end = html.index("el('move-submit').addEventListener", start)
        handler = html[start:end]
        editable_guard = "if(['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName))return;"
        binding_resolve = "resolveBinding(chord,'analysis','analysis')"
        mapped_prevent_default = "if(a){e.preventDefault();executeAction(a.actionId)}"
        self.assertIn(editable_guard, handler)
        self.assertIn(binding_resolve, handler)
        self.assertIn(mapped_prevent_default, handler)
        self.assertLess(handler.index(editable_guard), handler.index(binding_resolve))
        self.assertLess(handler.index(editable_guard), handler.index(mapped_prevent_default))

        move_listener = "el('move-input').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();submitMove()}})"
        self.assertIn(move_listener, html)
        self.assertNotIn("'move-input').addEventListener('keydown',e=>{e.preventDefault()", html)

    def test_board_square_accessible_names_are_concise_and_bilingual(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            api = Stage1ReleaseAccessibleChessAPI(keymap_path=Path(td) / "keymap.json")
            api.new_game()
            self.assertEqual(api.square_label("e2"), "e 2, білий пішак")
            self.assertEqual(api.square_label("e4"), "e 4")
            changed = api.set_language("en")
            self.assertTrue(changed["ok"])
            self.assertEqual(api.square_label("e2"), "e 2, white pawn")
            self.assertEqual(api.square_label("e4"), "e 4")


if __name__ == "__main__":
    unittest.main()
