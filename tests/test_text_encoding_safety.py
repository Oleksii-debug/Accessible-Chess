from __future__ import annotations

import unittest

from acs.text_encoding import LocalTextDecodeError, decode_local_text


class LocalTextControlSafetyTests(unittest.TestCase):
    def test_utf8_rejects_nul_and_c0_control_characters(self) -> None:
        for payload in (b"human\x00text", b"human\x01text", b"human\x1ftext"):
            with self.subTest(payload=payload):
                with self.assertRaises(LocalTextDecodeError):
                    decode_local_text(payload)

    def test_utf8_rejects_del_and_c1_controls(self) -> None:
        for text in ("human\x7ftext", "human\u0085text"):
            with self.subTest(text=repr(text)):
                with self.assertRaises(LocalTextDecodeError):
                    decode_local_text(text.encode("utf-8"))

    def test_bom_utf16_rejects_decoded_control_characters(self) -> None:
        payload = "human\x01text".encode("utf-16")
        with self.assertRaises(LocalTextDecodeError):
            decode_local_text(payload)

    def test_supported_human_whitespace_remains_valid_for_utf8_and_utf16(self) -> None:
        text = "Line one\tvalue\r\nLine two"
        utf8 = decode_local_text(text.encode("utf-8"))
        utf16 = decode_local_text(text.encode("utf-16"))
        self.assertEqual(text, utf8.text)
        self.assertEqual("utf-8", utf8.encoding)
        self.assertFalse(utf8.transcoded)
        self.assertEqual(text, utf16.text)
        self.assertEqual("utf-16", utf16.encoding)
        self.assertTrue(utf16.transcoded)


if __name__ == "__main__":
    unittest.main()
