from __future__ import annotations

import unicodedata
import unittest

import acs.legacy_text_encoding as legacy_text_encoding
from acs.legacy_text_encoding import LegacyTextEncodingError, decode_book_text_bytes


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

    def test_utf8_bom_decodes_deterministically(self) -> None:
        text = "Українська книга — позиції та аналіз"
        decoded = decode_book_text_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))

        self.assertEqual(decoded.encoding, "utf-8")
        self.assertFalse(decoded.legacy)
        self.assertEqual(decoded.text, text)

    def test_malformed_utf8_bom_never_falls_through_to_cp1251(self) -> None:
        cases = (
            (
                False,
                "Українська книга позиції аналіз партія".encode("cp1251"),
            ),
            (
                True,
                (
                    "<html><body><p>Українська книга позиції аналіз партія"
                    "</p></body></html>"
                ).encode("cp1251"),
            ),
        )
        for html, body in cases:
            with self.subTest(html=html):
                with self.assertRaises(LegacyTextEncodingError) as raised:
                    decode_book_text_bytes(b"\xef\xbb\xbf" + body, html=html)
                self.assertIn("BOM-declared UTF-8", str(raised.exception))

    def test_bom_utf16_little_and_big_endian_decode_deterministically(self) -> None:
        text = "Українська книга — позиції та аналіз"
        payloads = (
            b"\xff\xfe" + text.encode("utf-16-le"),
            b"\xfe\xff" + text.encode("utf-16-be"),
        )
        for payload in payloads:
            with self.subTest(bom=payload[:2]):
                decoded = decode_book_text_bytes(payload)
                self.assertEqual(decoded.encoding, "utf-16")
                self.assertFalse(decoded.legacy)
                self.assertEqual(decoded.text, text)

    def test_bom_utf16_html_uses_same_decoder(self) -> None:
        text = "<html><body><p>Українська книга</p></body></html>"
        payload = b"\xff\xfe" + text.encode("utf-16-le")

        decoded = decode_book_text_bytes(payload, html=True)

        self.assertEqual(decoded.encoding, "utf-16")
        self.assertEqual(decoded.text, text)

    def test_malformed_bom_utf16_does_not_fall_through_to_cp1251(self) -> None:
        with self.assertRaises(LegacyTextEncodingError):
            decode_book_text_bytes(b"\xff\xfeA")

    def test_utf32_bom_is_rejected_instead_of_misread_as_utf16(self) -> None:
        payload = "Книга".encode("utf-32")
        with self.assertRaises(LegacyTextEncodingError):
            decode_book_text_bytes(payload)


if __name__ == "__main__":
    unittest.main()
