from __future__ import annotations

import unicodedata
import unittest

import acs.legacy_text_encoding as legacy_text_encoding
from acs.legacy_text_encoding import decode_book_text_bytes


class LegacyTextEncodingTests(unittest.TestCase):
    def test_cp1251_cyrillic_evidence_matches_codec_letter_semantics(self) -> None:
        expected: set[int] = set()
        for value in range(256):
            try:
                character = bytes([value]).decode("cp1251", errors="strict")
            except UnicodeDecodeError:
                continue
            if character.isalpha() and "CYRILLIC" in unicodedata.name(character, ""):
                expected.add(value)

        self.assertEqual(legacy_text_encoding._CP1251_CYRILLIC_BYTES, frozenset(expected))
        self.assertNotIn(0x98, expected)

    def test_extended_cp1251_cyrillic_letters_qualify_plain_book_text(self) -> None:
        text = "ЂЃѓЉЊЌЋЏ ЂЃѓЉ ЎўЈ јЅѕ"
        payload = text.encode("cp1251")
        self.assertNotEqual(payload.decode("cp1251"), payload.decode("latin-1"))

        decoded = decode_book_text_bytes(payload)

        self.assertEqual(decoded.encoding, "windows-1251")
        self.assertTrue(decoded.legacy)
        self.assertEqual(decoded.text, text)

    def test_extended_cp1251_cyrillic_letters_qualify_structured_html(self) -> None:
        text = "<html><body><p>ЂЃѓЉЊЌЋЏ ЎўЈ јЅѕ</p></body></html>"
        decoded = decode_book_text_bytes(text.encode("cp1251"), html=True)

        self.assertEqual(decoded.encoding, "windows-1251")
        self.assertEqual(decoded.text, text)

    def test_utf8_remains_authoritative_for_same_letters(self) -> None:
        text = "ЂЃѓЉЊЌЋЏ ЎўЈ јЅѕ"
        decoded = decode_book_text_bytes(text.encode("utf-8"))

        self.assertEqual(decoded.encoding, "utf-8")
        self.assertFalse(decoded.legacy)
        self.assertEqual(decoded.text, text)


if __name__ == "__main__":
    unittest.main()
