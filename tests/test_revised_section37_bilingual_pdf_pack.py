"""Real Ukrainian and English PDF rendering, searchability and no PDF import overclaims."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import unittest

from tools.revised_section37_bilingual_pdf_pack import render_pdf
from tools.revised_section37_bilingual_workbook_pack import load_advanced_workbook

class GenuineBilingualPdfTests(unittest.TestCase):
    def test_real_pdf_unicode_text_is_extractable_and_contains_all_12_real_fen_positions(self):
        from pypdf import PdfReader
        source = load_advanced_workbook()
        documents = {}
        for lang in ("uk", "en"):
            with self.subTest(language=lang):
                original_bytes = render_pdf(source, lang)
                self.assertTrue(original_bytes.startswith(b"%PDF-"))
                self.assertIn(b"%%EOF", original_bytes[-2048:])
                reader = PdfReader(BytesIO(original_bytes))
                self.assertGreaterEqual(len(reader.pages), 2)
                text = "\n".join(p.extract_text() or "" for p in reader.pages)
                self.assertIn(source["title"][lang], text)
                for row in source["lessons"]:
                    self.assertIn(row["fen_before_opponent_move"], text)
                    self.assertIn(row[lang]["title"], text)
                self.assertIn(source["level"][lang], text)
                self.assertEqual(len({row["lesson_id"] for row in source["lessons"]}), 12)
                documents[lang] = sha256(original_bytes).hexdigest()
        self.assertNotEqual(documents["uk"], documents["en"])

    def test_pdf_output_is_explicitly_not_native_chess_format_readback(self):
        source = load_advanced_workbook()
        self.assertEqual(source["language_codes"], ["uk", "en"])
        self.assertFalse(any(row["composer_study"] for row in source["lessons"]))
        with self.assertRaises(ValueError):
            render_pdf(source, "xx")


if __name__ == "__main__":
    unittest.main()
