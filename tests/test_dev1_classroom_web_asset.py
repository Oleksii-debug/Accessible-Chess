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

    def test_browser_asset_delegates_management_and_remote_commands_only(self) -> None:
        source = self.source
        for command in (
            "management.select",
            "management.move",
            "management.open",
            "remote.connect",
            "remote.reconnect",
            "remote.leave",
        ):
            self.assertIn(command, source)
        lowered = source.casefold()
        self.assertNotIn("fen", lowered)
        self.assertNotIn("chesscore", lowered)
        self.assertNotIn("make_move", lowered)

    def test_renderer_focuses_only_selected_option_after_render(self) -> None:
        source = self.source
        self.assertIn('[role="option"][aria-selected="true"]', source)
        self.assertIn('selected.focus({ preventScroll: true })', source)
        self.assertIn("root.replaceChildren(fragment)", source)


if __name__ == "__main__":
    unittest.main()
