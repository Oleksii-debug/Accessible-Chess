"""Section 53: visible SAN and screen-reader rendering share one move label.

This is presentation-only; canonical PgnTreeItem.san and chess rules are not changed.
"""
from __future__ import annotations

import unittest

from acs.full_product_presenters import UILanguage, _pgn_accessible_move_label
from acs.notation import format_accessible_compact_san


class Section53PgnCanonicalAccessibleLabelsTests(unittest.TestCase):
    def test_both_locales_retain_exact_san_with_spoken_output(self) -> None:
        for language in (UILanguage.UA, UILanguage.EN):
            for san in ("e4", "d4", "Nf3", "O-O"):
                with self.subTest(language=language, san=san):
                    label = _pgn_accessible_move_label(san, language)
                    spoken = format_accessible_compact_san(
                        san, "en" if language is UILanguage.EN else "uk"
                    )
                    # The literal move must remain available for text selection,
                    # search and copy, regardless of NVDA speech formatting.
                    self.assertTrue(label.startswith(san), label)
                    self.assertIn(spoken, label)
                    if spoken != san:
                        self.assertEqual(f"{san} ({spoken})", label)
                    else:
                        self.assertEqual(san, label)


if __name__ == "__main__":
    unittest.main()
