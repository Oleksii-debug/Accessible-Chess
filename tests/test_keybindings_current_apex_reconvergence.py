from __future__ import annotations

import json
from pathlib import Path
import unittest

from acs.full_product_actions import build_full_product_action_registry
from acs.keybindings import ActionRegistry, BindingContext, normalize_binding
from acs.ui_keymap_adapter import build_web_keymap


ROOT = Path(__file__).resolve().parents[1]


class CurrentApexKeybindingReconvergenceTests(unittest.TestCase):
    def test_current_file_new_binding_survives_terminal_reconvergence(self) -> None:
        registry = ActionRegistry()
        self.assertEqual(registry.get_binding("file.new"), "Ctrl+N")

    def test_nvda_and_dom_arrow_spellings_normalize_canonically(self) -> None:
        self.assertEqual(normalize_binding("NVDA+F7"), "NVDA+F7")
        self.assertEqual(normalize_binding("ArrowLeft"), "Left")
        self.assertEqual(normalize_binding("control-arrowdown"), "Ctrl+Down")

    def test_stage1_terminal_navigation_defaults_are_central_registry_actions(self) -> None:
        registry = ActionRegistry()
        expected = {
            "history.commit_go_to_move": "Enter",
            "move.submit": "Enter",
            "board.cursor_left": "Left",
            "board.cursor_right": "Right",
            "board.cursor_up": "Up",
            "board.cursor_down": "Down",
            "board.activate": "Enter",
            "board.activate_alternative": "Space",
            "board.exit": "Escape",
        }
        for action_id, binding in expected.items():
            with self.subTest(action_id=action_id):
                self.assertEqual(registry.get_binding(action_id), binding)

    def test_static_web_fallback_matches_stage1_canonical_projection(self) -> None:
        fallback = json.loads((ROOT / "web" / "keybindings.json").read_text(encoding="utf-8"))
        self.assertEqual(fallback, build_web_keymap(ActionRegistry()))

    def test_full_product_terminal_contexts_are_registry_owned(self) -> None:
        registry = build_full_product_action_registry()
        expected = {
            "screen.help": (BindingContext.GLOBAL, "F1"),
            "pgn.previous_item": (BindingContext.PGN_TREE, "Up"),
            "pgn.next_item": (BindingContext.PGN_TREE, "Down"),
            "pgn.parent_variation": (BindingContext.PGN_TREE, "Left"),
            "library.previous_result": (BindingContext.LIBRARY_RESULTS, "Up"),
            "library.next_result": (BindingContext.LIBRARY_RESULTS, "Down"),
            "library.open_game": (BindingContext.LIBRARY_RESULTS, "Enter"),
            "education.previous_item": (BindingContext.EDUCATION_LIST, "Up"),
            "education.next_item": (BindingContext.EDUCATION_LIST, "Down"),
            "education.open_selected": (BindingContext.EDUCATION_LIST, "Enter"),
            "classroom.previous_item": (BindingContext.CLASSROOM_LIST, "Up"),
            "classroom.next_item": (BindingContext.CLASSROOM_LIST, "Down"),
            "classroom.first_item": (BindingContext.CLASSROOM_LIST, "Home"),
            "classroom.last_item": (BindingContext.CLASSROOM_LIST, "End"),
            "classroom.open_selected": (BindingContext.CLASSROOM_LIST, "Enter"),
            "toolbar.previous_control": (BindingContext.TOOLBAR, "Left"),
            "toolbar.next_control": (BindingContext.TOOLBAR, "Right"),
            "toolbar.first_control": (BindingContext.TOOLBAR, "Home"),
            "toolbar.last_control": (BindingContext.TOOLBAR, "End"),
            "profile.save_name": (BindingContext.PROFILE_DIALOG, "Enter"),
        }
        for action_id, (context, binding) in expected.items():
            with self.subTest(action_id=action_id):
                definition = registry.definition(action_id)
                self.assertEqual(definition.context, context)
                self.assertEqual(registry.get_binding(action_id), binding)

    def test_current_book_navigation_actions_are_not_regressed(self) -> None:
        registry = build_full_product_action_registry()
        for action_id in (
            "book.previous_block",
            "book.next_block",
            "book.previous_heading",
            "book.next_heading",
            "book.previous_position",
            "book.next_position",
            "book.previous_game",
            "book.next_game",
        ):
            with self.subTest(action_id=action_id):
                self.assertEqual(registry.definition(action_id).context, BindingContext.BOOK_READER)

    def test_web_projection_exposes_terminal_contexts_and_current_file_new(self) -> None:
        rows = {row["id"]: row for row in build_web_keymap(build_full_product_action_registry())["actions"]}
        self.assertEqual(rows["file.new"]["binding"], "Ctrl+N")
        self.assertEqual(rows["pgn.previous_item"]["context"], "pgn_tree")
        self.assertEqual(rows["library.open_game"]["context"], "library_results")
        self.assertEqual(rows["education.open_selected"]["context"], "education_list")
        self.assertEqual(rows["classroom.open_selected"]["context"], "classroom_list")
        self.assertEqual(rows["toolbar.next_control"]["context"], "toolbar")
        self.assertEqual(rows["profile.save_name"]["context"], "profile_dialog")

    def test_imported_duplicate_binding_fails_closed(self) -> None:
        registry = ActionRegistry()
        profile = registry.to_profile()
        profile["bindings"]["history.next"] = "Shift+A"
        with self.assertRaisesRegex(ValueError, "invalid keymap profile"):
            ActionRegistry.import_json(json.dumps(profile))


if __name__ == "__main__":
    unittest.main()
