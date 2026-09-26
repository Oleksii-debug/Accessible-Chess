from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import unittest
import warnings
import zipfile

from acs.book_epub_import import (
    BookEpubImportError,
    BookEpubImportErrorCode,
    SUPPORTED_EPUB_BOOK_CAPABILITY,
    import_epub_book,
)
from acs.bookdocument import Diagram, Game, Heading, ListBlock, Paragraph
from acs.chesscore import Board


CONTAINER = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''


def _opf(*, manifest: str, spine: str, metadata: str | None = None) -> bytes:
    if metadata is None:
        metadata = '''
    <dc:title>Accessible EPUB Chess</dc:title>
    <dc:creator>Author One</dc:creator>
    <dc:creator>Author Two</dc:creator>
    <dc:language>uk</dc:language>
    <dc:rights>Test fixture</dc:rights>'''
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="bookid"
 xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
  <metadata>{metadata}
  </metadata>
  <manifest>
{manifest}
  </manifest>
  <spine>
{spine}
  </spine>
</package>'''.encode("utf-8")


def _epub(
    *,
    opf: bytes,
    entries: dict[str, bytes],
    container: bytes = CONTAINER,
    prepend: list[tuple[str, bytes]] | None = None,
) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_STORED
        archive.writestr(mimetype, b"application/epub+zip")
        for name, data in prepend or []:
            archive.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        for name, data in entries.items():
            archive.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def _simple_epub(chapter: bytes) -> bytes:
    return _epub(
        opf=_opf(
            manifest='    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>',
            spine='    <itemref idref="c1"/>',
        ),
        entries={"OEBPS/Text/ch1.xhtml": chapter},
    )


class BookEpubImportTests(unittest.TestCase):
    def test_spine_metadata_lists_positions_images_and_pgn_are_semantic(self) -> None:
        chapter1 = f'''<!doctype html><html lang="uk"><head><title>Chapter One</title></head><body>
<h1 id="strategy">Стратегія</h1>
<p>План позиції.</p>
<ol id="steps" start="3"><li>Поліпшити фігуру</li><li>Відкрити лінію</li></ol>
<img id="diagram" src="../Images/knight.png" alt="Початкова позиція" data-acs-fen="{Board.START}"/>
</body></html>'''.encode("utf-8")
        chapter2 = b'''<html><head><title>Chapter Two</title></head><body>
<h2>Example</h2>
<pre>{PGN 1}
[Event "Embedded"]
[White "A"]
[Black "B"]
[Result "*"]

1. e4 e5 *</pre>
</body></html>'''
        opf = _opf(
            manifest='''    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="Text/ch2.xhtml" media-type="application/xhtml+xml"/>
    <item id="img" href="Images/knight.png" media-type="image/png"/>''',
            spine='''    <itemref idref="c1"/>
    <itemref idref="c2"/>''',
        )
        raw = _epub(
            opf=opf,
            entries={
                "OEBPS/Text/ch1.xhtml": chapter1,
                "OEBPS/Text/ch2.xhtml": chapter2,
                "OEBPS/Images/knight.png": b"not-decoded-image-bytes",
            },
        )

        result = import_epub_book(raw, source_name="study.epub")

        self.assertEqual(result.document.title, "Accessible EPUB Chess")
        self.assertEqual(result.document.author, "Author One; Author Two")
        self.assertEqual(result.document.language, "uk")
        self.assertEqual(result.document.source_rights, "Test fixture")
        self.assertEqual(result.spine_documents, 2)
        self.assertEqual(result.pgn_games, 1)
        self.assertEqual(result.image_references, ("OEBPS/Images/knight.png",))
        self.assertEqual(result.source_sha256, sha256(raw).hexdigest())
        self.assertEqual(result.book_key, f"epub-sha256:{sha256(raw).hexdigest()}")

        headings = [block for block in result.document.blocks if isinstance(block, Heading)]
        lists = [block for block in result.document.blocks if isinstance(block, ListBlock)]
        diagrams = [block for block in result.document.blocks if isinstance(block, Diagram)]
        games = [block for block in result.document.blocks if isinstance(block, Game)]
        self.assertEqual([heading.text for heading in headings], ["Стратегія", "Example"])
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].items, ["Поліпшити фігуру", "Відкрити лінію"])
        self.assertTrue(lists[0].ordered)
        self.assertEqual(lists[0].start, 3)
        self.assertEqual(diagrams[0].fen, Board.START)
        self.assertEqual(diagrams[0].alt_text, "Початкова позиція")
        self.assertTrue(diagrams[0].source_anchor.startswith("OEBPS/Text/ch1.xhtml#"))
        self.assertEqual(len(games), 1)
        self.assertIn('[Event "Embedded"]', games[0].pgn)
        self.assertEqual(len({block.block_id for block in result.document.blocks}), len(result.document.blocks))
        self.assertEqual(result.document.validate_structure(), list(result.warnings))

    def test_unmarked_valid_pgn_in_spine_stays_readable_text(self) -> None:
        chapter = b'''<html><body><h1>Quoted game</h1><pre>[Event "Quoted"]
[White "A"]
[Black "B"]
[Result "*"]

1. d4 d5 *</pre></body></html>'''
        result = import_epub_book(_simple_epub(chapter), source_name="quoted.epub")
        self.assertEqual(result.pgn_games, 0)
        self.assertFalse(any(isinstance(block, Game) for block in result.document.blocks))
        readable = "\n".join(
            block.text for block in result.document.blocks if isinstance(block, Paragraph)
        )
        self.assertIn('[Event "Quoted"]', readable)

    def test_manifest_fallback_to_readable_xhtml_is_followed(self) -> None:
        opf = _opf(
            manifest='''    <item id="fixed" href="fixed.svg" media-type="image/svg+xml" fallback="fallback"/>
    <item id="fallback" href="Text/fallback.xhtml" media-type="application/xhtml+xml"/>''',
            spine='    <itemref idref="fixed"/>',
        )
        raw = _epub(
            opf=opf,
            entries={
                "OEBPS/fixed.svg": b"<svg/>",
                "OEBPS/Text/fallback.xhtml": b"<html><body><h1>Fallback chapter</h1><p>Readable.</p></body></html>",
            },
        )

        result = import_epub_book(raw, source_name="fallback.epub")
        self.assertEqual(result.spine_documents, 1)
        self.assertEqual(result.document.headings()[0].text, "Fallback chapter")

    def test_unsupported_spine_media_is_explicit_not_silent(self) -> None:
        opf = _opf(
            manifest='''    <item id="cover" href="cover.svg" media-type="image/svg+xml"/>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>''',
            spine='''    <itemref idref="cover" linear="no"/>
    <itemref idref="chapter"/>''',
        )
        raw = _epub(
            opf=opf,
            entries={
                "OEBPS/cover.svg": b"<svg/>",
                "OEBPS/chapter.xhtml": b"<html><body><p>Readable chapter</p></body></html>",
            },
        )

        result = import_epub_book(raw, source_name="mixed.epub")
        self.assertEqual(result.spine_documents, 1)
        self.assertTrue(any("unsupported media" in warning for warning in result.warnings))
        self.assertTrue(any("non-linear" in warning for warning in result.warnings))
        self.assertEqual(
            [block.text for block in result.document.blocks if isinstance(block, Paragraph)],
            ["Readable chapter"],
        )

    def test_missing_package_image_is_reported_without_guessing_position(self) -> None:
        chapter = b'<html><body><img src="../Images/missing.png" alt="Visual diagram"/></body></html>'
        raw = _simple_epub(chapter)

        result = import_epub_book(raw, source_name="missing-image.epub")
        self.assertEqual(result.image_references, ())
        self.assertTrue(any("package image is unavailable" in warning for warning in result.warnings))
        self.assertFalse(any(isinstance(block, Diagram) for block in result.document.blocks))

    def test_invalid_explicit_chess_position_fails_before_publication(self) -> None:
        raw = _simple_epub(
            b'<html><body><p>Before</p><div data-acs-fen="8/8/8/8/8/8/8/8 w - - 0 1"></div><p>After</p></body></html>'
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="invalid-position.epub")
        self.assertEqual(raised.exception.code, BookEpubImportErrorCode.MALFORMED_CHESS_CONTENT)

    def test_archive_traversal_entry_is_rejected_even_when_not_in_spine(self) -> None:
        opf = _opf(
            manifest='    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
            spine='    <itemref idref="c1"/>',
        )
        raw = _epub(
            opf=opf,
            entries={"OEBPS/chapter.xhtml": b"<html><body><p>Safe</p></body></html>"},
            prepend=[("../escape.txt", b"must never extract")],
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="unsafe.epub")
        self.assertEqual(raised.exception.code, BookEpubImportErrorCode.UNSAFE_PACKAGE)

    def test_duplicate_archive_entries_are_rejected(self) -> None:
        buffer = BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(buffer, "w") as archive:
                mimetype = zipfile.ZipInfo("mimetype")
                mimetype.compress_type = zipfile.ZIP_STORED
                archive.writestr(mimetype, b"application/epub+zip")
                archive.writestr("META-INF/container.xml", CONTAINER)
                archive.writestr("META-INF/container.xml", CONTAINER)
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(buffer.getvalue(), source_name="duplicate.epub")
        self.assertEqual(raised.exception.code, BookEpubImportErrorCode.UNSAFE_PACKAGE)

    def test_external_manifest_href_is_rejected(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest='    <item id="c1" href="https://example.invalid/chapter.xhtml" media-type="application/xhtml+xml"/>',
                spine='    <itemref idref="c1"/>',
            ),
            entries={},
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="external.epub")
        self.assertEqual(raised.exception.code, BookEpubImportErrorCode.UNSAFE_PACKAGE)

    def test_fallback_cycle_is_rejected(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest='''    <item id="a" href="a.svg" media-type="image/svg+xml" fallback="b"/>
    <item id="b" href="b.svg" media-type="image/svg+xml" fallback="a"/>''',
                spine='    <itemref idref="a"/>',
            ),
            entries={"OEBPS/a.svg": b"<svg/>", "OEBPS/b.svg": b"<svg/>"},
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="cycle.epub")
        self.assertEqual(raised.exception.code, BookEpubImportErrorCode.MALFORMED_PACKAGE)

    def test_opf_doctype_entity_surface_is_rejected(self) -> None:
        dangerous = b'''<!DOCTYPE package [<!ENTITY xxe SYSTEM "file:///secret">]>
<package><metadata/><manifest/><spine/></package>'''
        raw = _epub(opf=dangerous, entries={})
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="doctype.epub")
        self.assertEqual(raised.exception.code, BookEpubImportErrorCode.UNSAFE_PACKAGE)

    def test_unsupported_only_spine_fails_no_readable_content(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest='    <item id="cover" href="cover.svg" media-type="image/svg+xml"/>',
                spine='    <itemref idref="cover"/>',
            ),
            entries={"OEBPS/cover.svg": b"<svg/>"},
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="image-only.epub")
        self.assertEqual(raised.exception.code, BookEpubImportErrorCode.NO_READABLE_CONTENT)

    def test_utf16_spine_is_explicitly_unsupported(self) -> None:
        chapter = "<html><body><p>UTF sixteen</p></body></html>".encode("utf-16")
        raw = _simple_epub(chapter)
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="utf16.epub")
        self.assertEqual(raised.exception.code, BookEpubImportErrorCode.UNSUPPORTED_CONTENT)

    def test_source_contract_and_capability_are_explicit(self) -> None:
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book("not bytes", source_name="bad.epub")  # type: ignore[arg-type]
        self.assertEqual(raised.exception.code, BookEpubImportErrorCode.INVALID_ARGUMENT)
        self.assertEqual(SUPPORTED_EPUB_BOOK_CAPABILITY["format"], "EPUB 2/3")
        self.assertIn("DRM or encrypted spine bypass", SUPPORTED_EPUB_BOOK_CAPABILITY["does_not_claim"])
        self.assertIn("ordered/unordered lists", SUPPORTED_EPUB_BOOK_CAPABILITY["preserves"])


if __name__ == "__main__":
    unittest.main()
