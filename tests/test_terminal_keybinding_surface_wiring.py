from __future__ import annotations

from pathlib import Path
import unittest

from acs.full_product_actions import build_full_product_action_registry
from acs.keybindings import ActionRegistry, BindingContext


ROOT = Path(__file__).resolve().parents[1]


def _resolved(registry: ActionRegistry, context: BindingContext, binding: str) -> str | None:
    item = registry.resolve_binding(context, binding)
    return None if item is None else item.action_id


class TerminalKeybindingSurfaceWiringTests(unittest.TestCase):
    def test_terminal_context_remaps_roundtrip_without_cross_context_leakage(self) -> None:
        registry = build_full_product_action_registry()
        registry.set_binding("pgn.next_item", "J")
        registry.set_binding("library.next_result", "K")
        registry.set_binding("library.open_game", "Ctrl+Enter")
        registry.set_binding("education.next_item", "L")
        registry.set_binding("education.open_selected", "O")
        registry.set_binding("classroom.previous_item", "H")
        registry.set_binding("classroom.next_item", "J")
        registry.set_binding("classroom.first_item", "G")
        registry.set_binding("classroom.last_item", "K")
        registry.set_binding("classroom.open_selected", "O")
        registry.set_binding("board.cursor_down", "Ctrl+J")
        registry.set_binding("move.submit", "F2")
        registry.set_binding("history.commit_go_to_move", "F3")

        self.assertIsNone(_resolved(registry, BindingContext.PGN_TREE, "Down"))
        self.assertEqual("pgn.next_item", _resolved(registry, BindingContext.PGN_TREE, "J"))
        self.assertIsNone(_resolved(registry, BindingContext.LIBRARY_RESULTS, "Down"))
        self.assertEqual("library.next_result", _resolved(registry, BindingContext.LIBRARY_RESULTS, "K"))
        self.assertEqual("library.open_game", _resolved(registry, BindingContext.LIBRARY_RESULTS, "Ctrl+Enter"))
        self.assertIsNone(_resolved(registry, BindingContext.EDUCATION_LIST, "Down"))
        self.assertEqual("education.next_item", _resolved(registry, BindingContext.EDUCATION_LIST, "L"))
        self.assertEqual("education.open_selected", _resolved(registry, BindingContext.EDUCATION_LIST, "O"))
        self.assertIsNone(_resolved(registry, BindingContext.CLASSROOM_LIST, "Down"))
        self.assertEqual("classroom.previous_item", _resolved(registry, BindingContext.CLASSROOM_LIST, "H"))
        self.assertEqual("classroom.next_item", _resolved(registry, BindingContext.CLASSROOM_LIST, "J"))
        self.assertEqual("classroom.first_item", _resolved(registry, BindingContext.CLASSROOM_LIST, "G"))
        self.assertEqual("classroom.last_item", _resolved(registry, BindingContext.CLASSROOM_LIST, "K"))
        self.assertEqual("classroom.open_selected", _resolved(registry, BindingContext.CLASSROOM_LIST, "O"))
        self.assertIsNone(_resolved(registry, BindingContext.BOARD, "Down"))
        self.assertEqual("board.cursor_down", _resolved(registry, BindingContext.BOARD, "Ctrl+J"))
        self.assertIsNone(_resolved(registry, BindingContext.MOVE_ENTRY, "Enter"))
        self.assertEqual("move.submit", _resolved(registry, BindingContext.MOVE_ENTRY, "F2"))
        self.assertIsNone(_resolved(registry, BindingContext.HISTORY, "Enter"))
        self.assertEqual("history.commit_go_to_move", _resolved(registry, BindingContext.HISTORY, "F3"))

        restored = ActionRegistry.import_json(registry.export_json(), registry.definitions())
        self.assertEqual("pgn.next_item", _resolved(restored, BindingContext.PGN_TREE, "J"))
        self.assertEqual("library.next_result", _resolved(restored, BindingContext.LIBRARY_RESULTS, "K"))
        self.assertEqual("library.open_game", _resolved(restored, BindingContext.LIBRARY_RESULTS, "Ctrl+Enter"))
        self.assertEqual("education.next_item", _resolved(restored, BindingContext.EDUCATION_LIST, "L"))
        self.assertEqual("education.open_selected", _resolved(restored, BindingContext.EDUCATION_LIST, "O"))
        self.assertEqual("classroom.previous_item", _resolved(restored, BindingContext.CLASSROOM_LIST, "H"))
        self.assertEqual("classroom.next_item", _resolved(restored, BindingContext.CLASSROOM_LIST, "J"))
        self.assertEqual("classroom.first_item", _resolved(restored, BindingContext.CLASSROOM_LIST, "G"))
        self.assertEqual("classroom.last_item", _resolved(restored, BindingContext.CLASSROOM_LIST, "K"))
        self.assertEqual("classroom.open_selected", _resolved(restored, BindingContext.CLASSROOM_LIST, "O"))
        self.assertEqual("board.cursor_down", _resolved(restored, BindingContext.BOARD, "Ctrl+J"))
        self.assertEqual("move.submit", _resolved(restored, BindingContext.MOVE_ENTRY, "F2"))
        self.assertEqual("history.commit_go_to_move", _resolved(restored, BindingContext.HISTORY, "F3"))

    def test_shell_exports_current_synchronous_event_resolver_for_child_surfaces(self) -> None:
        source = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function keymapActionForEvent(e,registryContext)", source)
        self.assertIn("if(!keymapReady)return null", source)
        self.assertIn("actionByChord(eventChord(e),registryContext)", source)
        self.assertIn("window.accessibleChessKeymapAction=keymapActionForEvent", source)
        self.assertIn("function installKeymapSnapshot(snapshot,isCentral)", source)
        self.assertIn("const hadReadyKeymap=keymapReady", source)
        self.assertIn("if(!hadReadyKeymap)keymapReady=false", source)
        self.assertIn("async function applyKeymapMutation(result)", source)
        self.assertIn("if(result.snapshot){try{installKeymapSnapshot(result.snapshot,true)", source)
        self.assertIn("keymapReady=true", source)
        self.assertNotIn("async function loadKeymap(){keymapReady=false", source)

    def test_stage1_board_and_commit_surfaces_consume_live_registry_without_old_defaults(self) -> None:
        source = (ROOT / "web" / "stage1_board_actions.js").read_text(encoding="utf-8")
        for marker in (
            "window.onBoardKey = remappableOnBoardKey",
            "cell.removeEventListener('keydown', baseOnBoardKey)",
            "const projectedAction = liveKeymapAction(event, 'board')",
            "resolveBinding(eventChord(event), 'board', 'board')",
            "if (projectedAction === null)",
            "if (!actionId) return",
            "liveExactRegistryAction(event, registryContext, uiContext)",
            "action.registryContext === registryContext",
            "'move-input', 'move_entry', 'move-entry', 'move.submit'",
            "'history-input'",
            "'history.commit_go_to_move'",
            "if (event.key === 'Enter') event.stopImmediatePropagation()",
        ):
            self.assertIn(marker, source)
        # The central registry projection deliberately distinguishes the Python
        # registry context from the UI interaction scope for move entry.
        adapter = (ROOT / "acs" / "ui_keymap_adapter.py").read_text(encoding="utf-8")
        self.assertIn('BindingContext.MOVE_ENTRY: "move-entry"', adapter)

    def test_pgn_tree_uses_remappable_context_and_retains_current_roving_keys(self) -> None:
        source = (ROOT / "web" / "full_product_pgn.js").read_text(encoding="utf-8")
        self.assertIn('resolve(event, "pgn_tree")', source)
        self.assertIn("resolved !== null && resolved !== undefined", source)
        self.assertIn("!resolverReady", source)
        for action_id in ("pgn.previous_item", "pgn.next_item", "pgn.parent_variation"):
            self.assertIn(action_id, source)
        # These current semantic tree controls are intentionally not collapsed
        # into the three remappable terminal actions.
        self.assertIn('event.key === "ArrowRight"', source)
        self.assertIn('event.key === "Home"', source)
        self.assertIn('event.key === "End"', source)

    def test_library_results_use_remappable_context_with_keyboard_fallback(self) -> None:
        source = (ROOT / "web" / "full_product_library.js").read_text(encoding="utf-8")
        self.assertIn('resolve(event, "library_results")', source)
        self.assertIn('typeof resolve === "function"', source)
        self.assertIn("resolved !== null && resolved !== undefined", source)
        self.assertIn("!resolverReady", source)
        for action_id in ("library.previous_result", "library.next_result", "library.open_game"):
            self.assertIn(action_id, source)

    def test_education_list_uses_remappable_context_with_keyboard_fallback(self) -> None:
        source = (ROOT / "web" / "full_product_education.js").read_text(encoding="utf-8")
        self.assertIn('resolve(event, "education_list")', source)
        self.assertIn('typeof resolve === "function"', source)
        self.assertIn("resolved !== null && resolved !== undefined", source)
        self.assertIn("!resolverReady", source)
        for action_id in ("education.previous_item", "education.next_item", "education.open_selected"):
            self.assertIn(action_id, source)

    def test_classroom_list_uses_remappable_context_with_keyboard_fallback(self) -> None:
        source = (ROOT / "web" / "full_product_classroom.js").read_text(encoding="utf-8")
        self.assertIn('resolve(event, "classroom_list")', source)
        self.assertIn('typeof resolve === "function"', source)
        self.assertIn("resolved !== null && resolved !== undefined", source)
        self.assertIn("!resolverReady", source)
        for action_id in (
            "classroom.previous_item",
            "classroom.next_item",
            "classroom.first_item",
            "classroom.last_item",
            "classroom.open_selected",
        ):
            self.assertIn(action_id, source)

    def test_shipping_toolbars_use_one_remappable_context_with_bootstrap_fallback(self) -> None:
        for relative_path in (
            "web/full_product_books_training.js",
            "web/full_product_pgn.js",
        ):
            with self.subTest(relative_path=relative_path):
                source = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn('resolve(event, "toolbar")', source)
                self.assertIn('typeof resolve === "function"', source)
                self.assertIn("resolved !== null && resolved !== undefined", source)
                self.assertIn("!resolverReady", source)
                for action_id in (
                    "toolbar.previous_control",
                    "toolbar.next_control",
                    "toolbar.first_control",
                    "toolbar.last_control",
                ):
                    self.assertIn(action_id, source)

    def test_local_profile_save_uses_remappable_context_with_bootstrap_fallback(self) -> None:
        source = (ROOT / "web" / "version2_local_profile.js").read_text(encoding="utf-8")
        self.assertIn('resolve(event, "profile_dialog")', source)
        self.assertIn('typeof resolve === "function"', source)
        self.assertIn("resolved !== null && resolved !== undefined", source)
        self.assertIn("!resolverReady", source)
        self.assertIn('actionId = "profile.save_name"', source)


if __name__ == "__main__":
    unittest.main()
