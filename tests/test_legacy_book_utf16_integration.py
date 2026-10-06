from __future__ import annotations

import unittest

from acs.book_html_import import BookHtmlImportError, BookHtmlImportErrorCode, import_html_book
from acs.book_text_import import BookTextImportError, BookTextImportErrorCode, import_text_book
from acs.bookdocument import Heading, Paragraph


def _utf16le(text: str) -> bytes:
    return b"\xff\xfe" + text.encode("utf-16-le")


def _utf16be(text: str) -> bytes:
    return b"\xfe\xff" + text.encode("utf-16-be")


class LegacyBookUtf16IntegrationTests(unittest.TestCase):
    def test_txt_adapter_preserves_bom_utf16_unicode_text(self) -> None:
        text = "Шахові етюди\n\nПозиції, варіанти та пояснення для читача."
        result = import_text_book(
            _utf16le(text),
            source_name="studies.txt",
            source_format="txt",
        )

        paragraphs = [block for block in result.document.blocks if isinstance(block, Paragraph)]
        self.assertEqual([block.text for block in paragraphs], [
            "Шахові етюди",
            "Позиції, варіанти та пояснення для читача.",
        ])
        self.assertFalse(any("Windows-1251" in warning for warning in result.warnings))

    def test_markdown_adapter_preserves_bom_utf16_structure(self) -> None:
        text = "# Шахова книга\n\n## Розділ\n\nПояснення позиції без неявного шахового вгадування.\n"
        result = import_text_book(
            _utf16be(text),
            source_name="book.md",
            source_format="markdown",
        )

        headings = [block.text for block in result.document.blocks if isinstance(block, Heading)]
        self.assertEqual(headings, ["Шахова книга", "Розділ"])
        self.assertEqual(result.pgn_games, 0)
        self.assertEqual(result.positions, 0)

    def test_html_adapter_preserves_bom_utf16_semantics(self) -> None:
        html = """<!doctype html>
<html lang="uk"><head><title>Шахова книга</title></head>
<body><h1>Етюди</h1><p>Король і пішак у навчальній позиції.</p></body></html>"""
        result = import_html_book(_utf16le(html), source_name="book.html")

        self.assertEqual(result.document.title, "Шахова книга")
        self.assertTrue(
            any(isinstance(block, Heading) and block.text == "Етюди" for block in result.document.blocks)
        )
        self.assertEqual(result.pgn_games, 0)
        self.assertFalse(any("Windows-1251" in warning for warning in result.warnings))

    def test_malformed_bom_utf8_maps_to_public_encoding_errors(self) -> None:
        text_body = "Українська книга позиції аналіз партія".encode("cp1251")
        with self.assertRaises(BookTextImportError) as text_error:
            import_text_book(
                b"\xef\xbb\xbf" + text_body,
                source_name="bad-utf8-bom.txt",
                source_format="txt",
            )
        self.assertEqual(
            text_error.exception.code,
            BookTextImportErrorCode.UNSUPPORTED_ENCODING,
        )

        html_body = (
            "<html><body><p>Українська книга позиції аналіз партія"
            "</p></body></html>"
        ).encode("cp1251")
        with self.assertRaises(BookHtmlImportError) as html_error:
            import_html_book(
                b"\xef\xbb\xbf" + html_body,
                source_name="bad-utf8-bom.html",
            )
        self.assertEqual(
            html_error.exception.code,
            BookHtmlImportErrorCode.UNSUPPORTED_ENCODING,
        )

    def test_malformed_bom_utf16_maps_to_public_encoding_errors(self) -> None:
        malformed = b"\xff\xfeA"
        with self.assertRaises(BookTextImportError) as text_error:
            import_text_book(malformed, source_name="bad.txt", source_format="txt")
        self.assertEqual(text_error.exception.code, BookTextImportErrorCode.UNSUPPORTED_ENCODING)

        with self.assertRaises(BookHtmlImportError) as html_error:
            import_html_book(malformed, source_name="bad.html")
        self.assertEqual(html_error.exception.code, BookHtmlImportErrorCode.UNSUPPORTED_ENCODING)


if __name__ == "__main__":
    unittest.main()
