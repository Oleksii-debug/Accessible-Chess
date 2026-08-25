from __future__ import annotations

from pathlib import Path
import unittest


ASSET = Path("web/full_product_books_training.js")


class BooksTrainingWebAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = ASSET.read_text(encoding="utf-8")

    def test_native_bookmark_and_training_answer_controls_preserve_editing_semantics(self) -> None:
        text = self.text
        self.assertIn('input.id = "book-bookmark-name"', text)
        self.assertIn('input.id = "training-answer"', text)
        self.assertIn('input.type = "text"', text)
        self.assertIn('form.addEventListener("submit"', text)
        for chord in ("Ctrl+A", "Ctrl+C", "Ctrl+X", "Ctrl+V", "Meta+A", "Meta+C"):
            self.assertNotIn(chord, text)
        self.assertNotIn("clipboardData", text)
        self.assertNotIn("navigator.clipboard", text)

    def test_no_global_keyboard_interception_or_html_injection(self) -> None:
        text = self.text
        self.assertNotIn('document.addEventListener("keydown"', text)
        self.assertNotIn('window.addEventListener("keydown"', text)
        self.assertNotIn('global.addEventListener("keydown"', text)
        for token in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            self.assertNotIn(token, text)

    def test_passive_messages_are_not_background_live_regions(self) -> None:
        text = self.text
        self.assertIn('warning.setAttribute("aria-live", "off")', text)
        self.assertIn('message.setAttribute("aria-live", "off")', text)
        self.assertNotIn('aria-live", "polite"', text)
        self.assertNotIn('aria-live", "assertive"', text)

    def test_reset_uses_native_dialog_and_restores_opener_on_cancel(self) -> None:
        text = self.text
        self.assertIn('const dialog = node("dialog")', text)
        self.assertIn('dialog.setAttribute("aria-labelledby"', text)
        self.assertIn('dialog.showModal()', text)
        self.assertIn('opener.focus({ preventScroll: true })', text)
        self.assertIn('{ confirmed: true }', text)

    def test_wrong_training_answer_is_preserved_locally_but_accepted_answer_clears(self) -> None:
        text = self.text
        self.assertIn('let priorAnswer = ""', text)
        self.assertIn('if (!payload.clear_answer && priorAnswer)', text)
        self.assertIn('next.value = priorAnswer', text)
        self.assertNotIn("accepted_moves", text)
        self.assertNotIn("start_fen", text)

    def test_transport_rejection_is_caught_without_error_object_projection(self) -> None:
        text = self.text
        self.assertIn('.catch(function ()', text)
        self.assertIn('announce(String(fallbackMessage))', text)
        self.assertNotIn("error.message", text)
        self.assertNotIn("String(error)", text)

    def test_book_position_path_has_no_browser_fen_or_direct_board_mutation(self) -> None:
        text = self.text
        self.assertNotIn("position_fen", text)
        self.assertNotIn("start_fen", text)
        self.assertNotIn("board.set_fen", text)
        self.assertNotIn("executeAction", text)


if __name__ == "__main__":
    unittest.main()
