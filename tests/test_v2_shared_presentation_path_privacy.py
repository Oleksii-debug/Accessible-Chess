from __future__ import annotations

import unittest

from acs.book_webview_projection import _safe_text as book_safe_text
from acs.full_product_ui_shell import UILanguage
from acs.presentation_privacy import redact_local_paths
from acs.training_webview_projection import _safe_text as training_safe_text


class V2SharedPresentationPathPrivacyTests(unittest.TestCase):
    PRIVATE_PATHS = (
        r"C:\Users\PrivateUser\Documents\study.pgn",
        r"C:Users\PrivateUser\Documents\study.pgn",
        r"\\server\private-share\PrivateUser\study.pgn",
        r"\\?\C:\Users\PrivateUser\Documents\study.pgn",
        "file:///C:/Users/PrivateUser/Documents/study.pgn",
        "/home/PrivateUser/study.pgn",
        "/opt/accessible-chess/private/study.pgn",
        "/srv/accessible-chess/private/study.pgn",
        "/etc/accessible-chess/private.conf",
        "/run/user/1000/private.sock",
        "/root/private/study.pgn",
        "/Applications/AccessibleChess/private/study.pgn",
    )

    def test_shared_helper_redacts_cross_platform_private_paths_and_keeps_next_line(self) -> None:
        marker = "[private path hidden]"
        for raw in self.PRIVATE_PATHS:
            with self.subTest(raw=raw):
                rendered = redact_local_paths(f"Source: {raw}\nNext semantic line", marker)
                self.assertIn(marker, rendered)
                self.assertIn("Next semantic line", rendered)
                self.assertNotIn("PrivateUser", rendered)
                self.assertNotIn("private-share", rendered)

    def test_book_and_training_surfaces_use_the_same_bilingual_redaction_contract(self) -> None:
        for raw in self.PRIVATE_PATHS:
            with self.subTest(raw=raw):
                self.assertIn(
                    "[local path hidden]",
                    book_safe_text(f"Book source {raw}", language=UILanguage.EN, limit=2000),
                )
                self.assertIn(
                    "[local path hidden]",
                    training_safe_text(f"Training source {raw}", language=UILanguage.EN, limit=2000),
                )
                self.assertIn(
                    "[локальний шлях приховано]",
                    book_safe_text(f"Джерело {raw}", language=UILanguage.UA, limit=2000),
                )
                self.assertIn(
                    "[локальний шлях приховано]",
                    training_safe_text(f"Джерело {raw}", language=UILanguage.UA, limit=2000),
                )

    def test_safe_domain_text_is_not_rewritten(self) -> None:
        safe_values = (
            "https://example.com/chess/help",
            "/help",
            "incoming/books/study.md",
            "incoming\\books\\study.md",
            "8/8/8/8/8/8/4P3/4K2k w - - 0 1",
            "1. e4 e5 2. Nf3 Nc6",
            "Evaluation: +0.35",
        )
        for value in safe_values:
            with self.subTest(value=value):
                self.assertEqual(value, redact_local_paths(value, "[hidden]"))
                self.assertEqual(
                    value,
                    book_safe_text(value, language=UILanguage.EN, limit=2000),
                )
                self.assertEqual(
                    value,
                    training_safe_text(value, language=UILanguage.EN, limit=2000),
                )

    def test_helper_rejects_invalid_boundary_arguments(self) -> None:
        with self.assertRaises(TypeError):
            redact_local_paths(123, "[hidden]")
        with self.assertRaises(ValueError):
            redact_local_paths("text", "")


if __name__ == "__main__":
    unittest.main()
