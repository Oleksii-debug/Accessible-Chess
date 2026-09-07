from __future__ import annotations

import unittest

from acs.full_product_ui_shell import UILanguage
from acs.library_webview_projection import _scrub_visible_text


class V2LibraryPresentationPathPrivacyTests(unittest.TestCase):
    PRIVATE_PATHS = (
        r"C:\Users\PrivateUser\Documents\library.pgn",
        r"C:Users\PrivateUser\Documents\library.pgn",
        r"\\server\private-share\PrivateUser\library.pgn",
        r"\\?\C:\Users\PrivateUser\Documents\library.pgn",
        "file:///C:/Users/PrivateUser/Documents/library.pgn",
        "/home/PrivateUser/library.pgn",
        "/opt/accessible-chess/private/library.pgn",
        "/srv/accessible-chess/private/library.pgn",
        "/etc/accessible-chess/private.conf",
        "/run/user/1000/private.sock",
        "/root/private/library.pgn",
        "/Applications/AccessibleChess/private/library.pgn",
    )

    def test_cross_platform_private_paths_are_redacted_before_webview_projection(self) -> None:
        for raw in self.PRIVATE_PATHS:
            with self.subTest(raw=raw):
                english = _scrub_visible_text(
                    f"Library source {raw}", language=UILanguage.EN, limit=2000
                )
                ukrainian = _scrub_visible_text(
                    f"Джерело бібліотеки {raw}", language=UILanguage.UA, limit=2000
                )
                self.assertIn("[local path hidden]", english)
                self.assertIn("[локальний шлях приховано]", ukrainian)
                self.assertNotIn("PrivateUser", english)
                self.assertNotIn("PrivateUser", ukrainian)
                self.assertNotIn("private-share", english)

    def test_safe_domain_text_is_preserved(self) -> None:
        safe_values = (
            "https://example.com/chess/library",
            "/help",
            "incoming/library/study.pgn",
            "incoming\\library\\study.pgn",
            "8/8/8/8/8/8/4P3/4K2k w - - 0 1",
            "1. e4 e5 2. Nf3 Nc6",
            "Evaluation: +0.35",
        )
        for value in safe_values:
            with self.subTest(value=value):
                self.assertEqual(
                    value,
                    _scrub_visible_text(value, language=UILanguage.EN, limit=2000),
                )


if __name__ == "__main__":
    unittest.main()
