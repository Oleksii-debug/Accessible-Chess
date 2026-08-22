from __future__ import annotations

import unittest
from pathlib import Path


class ClassroomWebAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (Path(__file__).parents[1] / "web" / "full_product_classroom.js").read_text(
            encoding="utf-8"
        )

    def test_renderer_uses_semantic_listbox_and_native_controls(self) -> None:
        source = self.source
        self.assertIn('setAttribute("role", "listbox")', source)
        self.assertIn('setAttribute("role", "option")', source)
        self.assertIn('setAttribute("aria-selected"', source)
        self.assertIn('node("input")', source)
        self.assertIn('node("button"', source)
        self.assertIn('node("h2"', source)

    def test_renderer_never_uses_html_injection_or_raw_markup_assignment(self) -> None:
        source = self.source
        self.assertIn("textContent", source)
        self.assertNotIn("innerHTML", source)
        self.assertNotIn("outerHTML", source)
        self.assertNotIn("insertAdjacentHTML", source)
        self.assertNotIn("document.write", source)

    def test_keyboard_handler_is_scoped_to_list_options_not_global_document(self) -> None:
        source = self.source
        self.assertIn('option.addEventListener("keydown"', source)
        self.assertNotIn('document.addEventListener("keydown"', source)
        self.assertNotIn('window.addEventListener("keydown"', source)
        self.assertIn('event.key === "ArrowUp"', source)
        self.assertIn('event.key === "ArrowDown"', source)
        self.assertIn('event.key === "Enter"', source)

    def test_remote_section_does_not_create_second_live_region(self) -> None:
        source = self.source
        self.assertIn('status.setAttribute("aria-live", "off")', source)
        self.assertNotIn('aria-live", "polite"', source)
        self.assertNotIn('setAttribute("role", "status")', source)

    def test_browser_asset_delegates_management_and_snapshot_supplied_remote_actions(self) -> None:
        source = self.source
        for command in ("management.select", "management.move", "management.open"):
            self.assertIn(command, source)
        self.assertIn('const command = String(action.action || "")', source)
        self.assertIn('command === "remote.connect"', source)
        self.assertIn("actions.forEach(function (action)", source)
        # Reconnect/leave action identity comes from the validated Python snapshot,
        # rather than a second JavaScript action registry.
        self.assertNotIn('invoke("remote.reconnect"', source)
        self.assertNotIn('invoke("remote.leave"', source)
        lowered = source.casefold()
        self.assertNotIn("fen", lowered)
        self.assertNotIn("chesscore", lowered)
        self.assertNotIn("make_move", lowered)

    def test_renderer_never_steals_focus_without_explicit_focus_target(self) -> None:
        source = self.source
        self.assertIn("function focusRequestedOption(root, focusTarget)", source)
        self.assertIn('querySelectorAll(\'[role="option"]\')', source)
        self.assertIn("option.id === focusTarget", source)
        self.assertIn("option.focus({ preventScroll: true })", source)
        self.assertIn('focusRequestedOption(root, focusTarget || "")', source)
        self.assertNotIn('[role="option"][aria-selected="true"]', source)
        self.assertIn("root.replaceChildren(fragment)", source)


if __name__ == "__main__":
    unittest.main()
