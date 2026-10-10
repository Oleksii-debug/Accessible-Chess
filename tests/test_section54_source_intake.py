from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from acs.format_factory_intake import (
    FactoryIntakeError, import_factory_book, inspect_factory_source,
)


def make_zip(entries: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return output.getvalue()


class Section54SourceIntakeTests(unittest.TestCase):
    def test_markdown_imports_through_canonical_model(self) -> None:
        data = "# Chapter 1\n\nA chess paragraph.\n".encode()
        result = import_factory_book(data, source_name="lesson.md")
        self.assertEqual(result.source.sha256, sha256(data).hexdigest())
        self.assertEqual(result.source.import_status, "SUPPORTED_BOOK_INGRESS")
        self.assertEqual(result.importer, "acs.book_text_import")
        self.assertTrue(result.document.blocks)

    def test_plain_text_is_not_guessed_into_a_game(self) -> None:
        result = import_factory_book(
            b"Hello.\n\n1. e4 e5 appears only in prose.", source_name="note.txt",
        )
        self.assertEqual(result.source.detected_format, "txt")
        self.assertFalse(any(x.__class__.__name__ == "Game" for x in result.document.blocks))

    def test_html_uses_existing_ingress(self) -> None:
        data = b"<html><body><h1>Chapter</h1><p>Study</p></body></html>"
        result = import_factory_book(data, source_name="a.html")
        self.assertEqual(result.source.detected_format, "html")
        self.assertTrue(result.document.blocks)

    def test_xhtml_xml_declaration_routes_through_canonical_html_import(self) -> None:
        source = (
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<html xmlns="http://www.w3.org/1999/xhtml">'
            b'<head><title>Study</title></head>'
            b'<body><h1>First chapter</h1><p>Study one position.</p></body>'
            b'</html>'
        )
        receipt = inspect_factory_source(source, source_name="study.xhtml")
        self.assertEqual(receipt.detected_format, "html")
        self.assertEqual(receipt.import_status, "SUPPORTED_BOOK_INGRESS")
        self.assertFalse(receipt.extension_mismatch)
        imported = import_factory_book(source, source_name="study.xhtml")
        self.assertEqual(imported.importer, "acs.book_html_import")
        self.assertEqual(imported.source.sha256, sha256(source).hexdigest())
        self.assertTrue(imported.document.blocks)

    def test_html_fragment_with_leading_comment_is_book_not_plaintext(self) -> None:
        data = b'<!-- Public sample -->\n<main><h2>Chess</h2><p>Study a position.</p></main>'
        receipt = inspect_factory_source(data, source_name="fragment.html")
        self.assertEqual(receipt.detected_format, "html")
        self.assertTrue(receipt.can_import_as_book)
        book = import_factory_book(data, source_name="fragment.html")
        self.assertTrue(book.document.blocks)

    def test_html_doctype_and_semantic_fragment_are_not_misclassified(self) -> None:
        for body, name in (
            (b"<!DOCTYPE html>\\n<html><body><p>Chess</p></body></html>", "doctype.html"),
            (b"<p>Prose and annotations.</p>", "fragment.xhtml"),
            (b"<article><h1>Strategy</h1><p>Reading</p></article>", "article.html"),
        ):
            with self.subTest(name=name):
                receipt = inspect_factory_source(body, source_name=name)
                self.assertTrue(receipt.can_import_as_book)
                self.assertEqual(receipt.detected_format, "html")

    def test_generic_xml_is_not_silently_accepted_as_html(self) -> None:
        xml = b'<?xml version="1.0"?><records><item>Not a book</item></records>'
        receipt = inspect_factory_source(xml, source_name="not-html.xhtml")
        self.assertNotEqual(receipt.detected_format, "html")
        self.assertEqual(receipt.import_status, "UNSUPPORTED")
        self.assertTrue(receipt.extension_mismatch)
        with self.assertRaises(FactoryIntakeError):
            import_factory_book(xml, source_name="not-html.xhtml")

    def test_pdf_and_image_bytes_cannot_claim_semantic_success(self) -> None:
        for data, name, expected in (
            (b"%PDF-1.7\nx", "a.pdf", "pdf"),
            (b"\x89PNG\r\n\x1a\nx", "a.png", "png"),
            (b"\xff\xd8\xffx", "a.jpeg", "jpeg"),
        ):
            receipt = inspect_factory_source(data, source_name=name)
            self.assertEqual(receipt.detected_format, expected)
            self.assertEqual(receipt.import_status, "PARTIAL")
            with self.assertRaises(FactoryIntakeError):
                import_factory_book(data, source_name=name)

    def test_zip_family_detection_remains_unqualified_when_needed(self) -> None:
        docx = make_zip({
            "[Content_Types].xml": b"<Types/>", "word/document.xml": b"<doc/>",
        })
        self.assertEqual(
            inspect_factory_source(docx, source_name="actual.docx").import_status, "PARTIAL",
        )
        epub = make_zip({
            "mimetype": b"application/epub+zip",
            "META-INF/container.xml": b"<container/>",
        })
        receipt = inspect_factory_source(epub, source_name="sample.epub")
        self.assertEqual(receipt.detected_format, "epub")
        self.assertTrue(receipt.can_import_as_book)

    def test_extension_spoof_and_generic_zip_fail_closed(self) -> None:
        receipt = inspect_factory_source(b"%PDF-1.7\n", source_name="fake.epub")
        self.assertTrue(receipt.extension_mismatch)
        self.assertEqual(receipt.import_status, "UNSUPPORTED")
        with self.assertRaises(FactoryIntakeError):
            import_factory_book(b"%PDF-1.7\n", source_name="fake.epub")
        generic = inspect_factory_source(
            make_zip({"other.txt": b"text"}), source_name="a.zip",
        )
        self.assertEqual(generic.import_status, "UNSUPPORTED")

    def test_traversal_and_duplicate_archive_names_rejected(self) -> None:
        for entries in (
            {"../outside.txt": b"x"}, {"/root/file": b"x"},
            {"C:/private": b"x"},
        ):
            with self.assertRaises(FactoryIntakeError):
                inspect_factory_source(make_zip(entries), source_name="bad.zip")
        # On Windows ZipInfo converts backslashes into forward slashes while
        # WRITING. Mutate both ZIP filename headers after writing a valid
        # same-length entry so the input really contains an unsafe backslash
        # on BOTH Windows and Linux (not a platform-specific safe path).
        unsafe = make_zip({"bad/member": b"x"})
        self.assertEqual(unsafe.count(b"bad/member"), 2)
        unsafe = unsafe.replace(b"bad/member", b"bad\\member")
        with self.assertRaises(FactoryIntakeError):
            inspect_factory_source(unsafe, source_name="backslash.zip")
        # ZipInfo may truncate NUL-bearing names when decoding archive
        # metadata. Inspect the original header, not the sanitized filename.
        nul_name = make_zip({"bad/entry.txt": b"x"})
        self.assertEqual(nul_name.count(b"bad/entry.txt"), 2)
        nul_name = nul_name.replace(b"bad/entry.txt", b"bad\x00entry.txt")
        with self.assertRaises(FactoryIntakeError):
            inspect_factory_source(nul_name, source_name="nul.zip")
        dest = BytesIO()
        with ZipFile(dest, "w") as archive:
            archive.writestr("A.txt", "first")
            archive.writestr("a.txt", "second")
        with self.assertRaises(FactoryIntakeError):
            inspect_factory_source(dest.getvalue(), source_name="duplicate.zip")

    def test_bad_epub_and_truncated_zip_rejected(self) -> None:
        with self.assertRaises(FactoryIntakeError):
            inspect_factory_source(b"PK\x03\x04garbage", source_name="bad.zip")
        with self.assertRaises(FactoryIntakeError):
            inspect_factory_source(
                make_zip({"mimetype": b"application/epub+zip"}),
                source_name="missing.epub",
            )

    def test_late_binary_controls_do_not_become_semantic_text(self) -> None:
        # The format-sniff window is 8192 chars, but every decoded source
        # character must be checked before it reaches the canonical importer.
        prefix = b"Normal chess prose and chapter text.\n" * 300
        self.assertGreater(len(prefix), 8192)
        self.assertTrue(
            inspect_factory_source(prefix + b"Last paragraph.\n", source_name="book.txt").can_import_as_book
        )
        for byte in (b"\x00", b"\x07", b"\x1f", b"\x7f"):
            with self.subTest(control=byte):
                data = prefix + byte + b"Later text."
                receipt = inspect_factory_source(data, source_name="book.txt")
                self.assertEqual(receipt.detected_format, "unknown")
                self.assertEqual(receipt.import_status, "UNSUPPORTED")
                with self.assertRaises(FactoryIntakeError):
                    import_factory_book(data, source_name="book.txt")

    def test_private_path_removed_from_provenance(self) -> None:
        data = b"First paragraph.\n"
        result = inspect_factory_source(
            data, source_name=r"C:\secret\parent\book.txt",
        )
        self.assertEqual(result.source_name, "book.txt")
        self.assertEqual(result.sha256, sha256(data).hexdigest())

    def test_pgn_chessbase_and_binary_do_not_create_books(self) -> None:
        data = b'[Event "Game"]\n[White "A"]\n[Black "B"]\n\n1. e4 *'
        receipt = inspect_factory_source(data, source_name="games.pgn")
        self.assertEqual(receipt.import_status, "SUPPORTED_BOOK_INGRESS")
        book = import_factory_book(data, source_name="games.pgn")
        self.assertEqual(book.importer, "acs.format_factory_pgn_book")
        self.assertEqual(len(book.document.blocks), 1)
        self.assertEqual(book.document.blocks[0].kind, "Game")
        self.assertEqual(book.source.sha256, sha256(data).hexdigest())
        self.assertEqual(
            inspect_factory_source(b"\x00\x01\x02", source_name="legacy.cbh").import_status,
            "UNSUPPORTED",
        )


if __name__ == "__main__":
    unittest.main()
