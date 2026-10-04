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

        self.assertIsNone(_resolved(registry, BindingContext.PGN_TREE, "Down"))
        self.assertEqual("pgn.next_item", _resolved(registry, BindingContext.PGN_TREE, "J"))
        self.assertIsNone(_resolved(registry, BindingContext.LIBRARY_RESULTS, "Down"))
        self.assertEqual("library.next_result", _resolved(registry, BindingContext.LIBRARY_RESULTS, "K"))
        self.assertEqual("library.open_game", _resolved(registry, BindingContext.LIBRARY_RESULTS, "Ctrl+Enter"))
        self.assertIsNone(_resolved(registry, BindingContext.EDUCATION_LIST, "Down"))
        self.assertEqual("education.next_item", _resolved(registry, BindingContext.EDUCATION_LIST, "L"))
        self.assertEqual("education.open_selected", _resolved(registry, BindingContext.EDUCATION_LIST, "O"))
        self.assertEqual("board.cursor_down", _resolved(registry, BindingContext.BOARD, "Down"))

        restored = ActionRegistry.import_json(registry.export_json(), registry.definitions())
        self.assertEqual("pgn.next_item", _resolved(restored, BindingContext.PGN_TREE, "J"))
        self.assertEqual("library.next_result", _resolved(restored, BindingContext.LIBRARY_RESULTS, "K"))
        self.assertEqual("library.open_game", _resolved(restored, BindingContext.LIBRARY_RESULTS, "Ctrl+Enter"))
        self.assertEqual("education.next_item", _resolved(restored, BindingContext.EDUCATION_LIST, "L"))
        self.assertEqual("education.open_selected", _resolved(restored, BindingContext.EDUCATION_LIST, "O"))

    def test_shell_exports_current_synchronous_event_resolver_for_child_surfaces(self) -> None:
        source = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function keymapActionForEvent(e,uiContext)", source)
        self.assertIn("if(!keymapReady)return null", source)
        self.assertIn("actionByChord(eventChord(e),uiContext)", source)
        self.assertIn("window.accessibleChessKeymapAction=keymapActionForEvent", source)
        self.assertIn("keymapReady=true", source)

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


if __name__ == "__main__":
    unittest.main()
