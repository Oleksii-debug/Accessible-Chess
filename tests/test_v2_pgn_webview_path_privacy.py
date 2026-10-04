import unittest

from acs.full_product_ui_shell import UILanguage
from acs.pgn_webview_projection import _bounded_text


class V2PgnWebViewPathPrivacyTests(unittest.TestCase):
    def _project(self, text: str, *, language: UILanguage = UILanguage.EN) -> str:
        return _bounded_text(text, language=language, limit=1200)

    def test_cross_platform_private_path_tokens_are_redacted(self):
        cases = (
            (r"C:\Users\PrivateUser\Documents\book.pgn", "PrivateUser"),
            (r"C:Users\PrivateUser\Documents\book.pgn", "PrivateUser"),
            (r"\\server\private-share\secret.pgn", "private-share"),
            (r"\\?\C:\Users\PrivateUser\secret.pgn", "PrivateUser"),
            ("file:///C:/Users/PrivateUser/secret.pgn", "PrivateUser"),
            ("/home/private-user/book.pgn", "private-user"),
            ("/opt/accessible-chess/private/book.pgn", "accessible-chess"),
            ("/srv/accessible-chess/private/book.pgn", "accessible-chess"),
            ("/etc/accessible-chess/private.conf", "accessible-chess"),
            ("/root/accessible-chess/private/book.pgn", "accessible-chess"),
            ("/run/accessible-chess/private.sock", "accessible-chess"),
            ("/Applications/AccessibleChess/private/book.pgn", "AccessibleChess"),
        )
        for token, private_component in cases:
            with self.subTest(token=token):
                projected = self._project(f"Parser note: {token}")
                self.assertIn("[local path hidden]", projected)
                self.assertNotIn(private_component, projected)

    def test_ukrainian_projection_uses_localized_redaction_marker(self):
        projected = self._project(
            r"Джерело C:Users\PrivateUser\book.pgn",
            language=UILanguage.UA,
        )
        self.assertIn("[локальний шлях приховано]", projected)
        self.assertNotIn("PrivateUser", projected)

    def test_safe_chess_web_and_relative_text_is_not_redacted(self):
        safe = (
            "https://example.com/docs/game.pgn",
            "Invalid command /help",
            "Line e4/e5 continues with Nf3/Nc6",
            "FEN rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            "relative source incoming/game.pgn",
            "Result 1-0",
        )
        for text in safe:
            with self.subTest(text=text):
                self.assertEqual(text, self._project(text))


if __name__ == "__main__":
    unittest.main()
