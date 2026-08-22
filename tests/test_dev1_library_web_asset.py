from __future__ import annotations

from pathlib import Path
import unittest


ASSET = Path("web/full_product_library.js")


class LibraryWebAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = ASSET.read_text(encoding="utf-8")

    def test_uses_native_search_editables_and_semantic_result_list(self) -> None:
        text = self.text
        self.assertIn('form.setAttribute("role", "search")', text)
        self.assertIn('node("input")', text)
        self.assertIn('node("select")', text)
        self.assertIn('list.setAttribute("role", "listbox")', text)
        self.assertIn('option.setAttribute("role", "option")', text)
        self.assertIn('option.setAttribute("aria-selected"', text)

    def test_keyboard_handler_is_scoped_to_result_options(self) -> None:
        text = self.text
        self.assertIn('option.addEventListener("keydown"', text)
        self.assertNotIn('document.addEventListener("keydown"', text)
        self.assertNotIn('window.addEventListener("keydown"', text)
        self.assertNotIn('global.addEventListener("keydown"', text)
        self.assertIn('eventObject.key === "ArrowUp"', text)
        self.assertIn('eventObject.key === "Enter"', text)

    def test_standard_editing_shortcuts_are_not_intercepted(self) -> None:
        text = self.text
        for chord in ("Ctrl+A", "Ctrl+C", "Ctrl+X", "Ctrl+V", "Meta+A", "Meta+C"):
            self.assertNotIn(chord, text)
        self.assertNotIn("clipboardData", text)
        self.assertNotIn("navigator.clipboard", text)

    def test_no_html_injection_or_background_live_region(self) -> None:
        text = self.text
        for token in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            self.assertNotIn(token, text)
        self.assertIn('status.setAttribute("aria-live", "off")', text)
        self.assertNotIn('aria-live", "polite"', text)
        self.assertNotIn('aria-live", "assertive"', text)

    def test_passive_render_does_not_force_focus_and_transport_rejection_is_caught(self) -> None:
        text = self.text
        self.assertIn('focusTarget(root, requestedFocus || "")', text)
        self.assertIn('.catch(function ()', text)
        self.assertIn('announce(String(errorMessage))', text)
        self.assertNotIn("setTimeout", text)

    def test_browser_does_not_contain_sql_or_fen_search_model(self) -> None:
        text = self.text
        self.assertNotIn("SELECT ", text)
        self.assertNotIn("sqlite", text.lower())
        self.assertNotIn("start_fen", text)
        self.assertNotIn("source_id", text)


if __name__ == "__main__":
    unittest.main()
