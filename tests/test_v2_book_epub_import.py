from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import stat
import unittest
import warnings
import zipfile

from acs.book_epub_import import (
    BookEpubImportError,
    BookEpubImportErrorCode,
    SUPPORTED_EPUB_BOOK_CAPABILITY,
    import_epub_book,
)
from acs.bookdocument import Diagram, Game, Heading, ListBlock, Note, Paragraph
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
    <dc:identifier id="bookid">urn:uuid:test-fixture</dc:identifier>
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


def _corrupt_deflated_entry(raw: bytes, name: str) -> bytes:
    damaged = bytearray(raw)
    with zipfile.ZipFile(BytesIO(raw), "r") as archive:
        info = archive.getinfo(name)
    if info.compress_type != zipfile.ZIP_DEFLATED or info.compress_size < 3:
        raise AssertionError("fixture entry must use a non-trivial Deflate payload")
    offset = info.header_offset
    if damaged[offset : offset + 4] != b"PK\x03\x04":
        raise AssertionError("fixture local ZIP header was not found")
    name_length = int.from_bytes(damaged[offset + 26 : offset + 28], "little")
    extra_length = int.from_bytes(damaged[offset + 28 : offset + 30], "little")
    data_offset = offset + 30 + name_length + extra_length
    damaged[data_offset + 1] ^= 0xFF
    return bytes(damaged)


def _mark_zip_entry_encrypted(raw: bytes, name: str) -> bytes:
    damaged = bytearray(raw)
    with zipfile.ZipFile(BytesIO(raw), "r") as archive:
        info = archive.getinfo(name)
        central_offset = archive.start_dir

    local_offset = info.header_offset
    if damaged[local_offset : local_offset + 4] != b"PK\x03\x04":
        raise AssertionError("fixture local ZIP header was not found")
    local_flags = int.from_bytes(
        damaged[local_offset + 6 : local_offset + 8],
        "little",
    )
    damaged[local_offset + 6 : local_offset + 8] = (local_flags | 0x1).to_bytes(
        2,
        "little",
    )

    encoded_name = name.encode("utf-8")
    cursor = central_offset
    while damaged[cursor : cursor + 4] == b"PK\x01\x02":
        name_length = int.from_bytes(damaged[cursor + 28 : cursor + 30], "little")
        extra_length = int.from_bytes(damaged[cursor + 30 : cursor + 32], "little")
        comment_length = int.from_bytes(damaged[cursor + 32 : cursor + 34], "little")
        entry_name = bytes(damaged[cursor + 46 : cursor + 46 + name_length])
        if entry_name == encoded_name:
            central_flags = int.from_bytes(
                damaged[cursor + 8 : cursor + 10],
                "little",
            )
            damaged[cursor + 8 : cursor + 10] = (central_flags | 0x1).to_bytes(
                2,
                "little",
            )
            return bytes(damaged)
        cursor += 46 + name_length + extra_length + comment_length
    raise AssertionError("fixture central ZIP entry was not found")


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

    def test_duplicate_direct_manifest_sections_fail_closed(self) -> None:
        opf = b'''<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0"
 xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
  <metadata><dc:title>Ambiguous manifest</dc:title></metadata>
  <manifest>
    <item id="c1" href="Text/one.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <manifest>
    <item id="c2" href="Text/two.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>'''
        raw = _epub(
            opf=opf,
            entries={
                "OEBPS/Text/one.xhtml": b"<html><body><p>One</p></body></html>",
                "OEBPS/Text/two.xhtml": b"<html><body><p>Two</p></body></html>",
            },
        )

        with self.assertRaises(BookEpubImportError) as caught:
            import_epub_book(raw, source_name="duplicate-manifest.epub")

        self.assertEqual(
            caught.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_duplicate_direct_spine_sections_fail_closed(self) -> None:
        opf = b'''<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0"
 xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
  <metadata><dc:title>Ambiguous spine</dc:title></metadata>
  <manifest>
    <item id="c1" href="Text/one.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="Text/two.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
  <spine><itemref idref="c2"/></spine>
</package>'''
        raw = _epub(
            opf=opf,
            entries={
                "OEBPS/Text/one.xhtml": b"<html><body><p>One</p></body></html>",
                "OEBPS/Text/two.xhtml": b"<html><body><p>Two</p></body></html>",
            },
        )

        with self.assertRaises(BookEpubImportError) as caught:
            import_epub_book(raw, source_name="duplicate-spine.epub")

        self.assertEqual(
            caught.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

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

    def test_package_identifiers_are_not_repaired_by_whitespace_trimming(self) -> None:
        cases = (
            (
                '    <item id=" c1 " href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>',
                '    <itemref idref="c1"/>',
            ),
            (
                '    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>',
                '    <itemref idref=" c1 "/>',
            ),
            (
                '    <item id="fixed" href="fixed.svg" media-type="image/svg+xml" fallback=" fallback "/>\n'
                '    <item id="fallback" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>',
                '    <itemref idref="fixed"/>',
            ),
            (
                '    <item id="fixed" href="fixed.svg" media-type="image/svg+xml" fallback=""/>\n'
                '    <item id="fallback" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>',
                '    <itemref idref="fixed"/>',
            ),
        )
        for manifest, spine in cases:
            with self.subTest(manifest=manifest, spine=spine):
                raw = _epub(
                    opf=_opf(manifest=manifest, spine=spine),
                    entries={
                        "OEBPS/Text/ch1.xhtml": b"<html><body><p>Readable.</p></body></html>",
                        "OEBPS/fixed.svg": b"<svg/>",
                    },
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="malformed-identifiers.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_manifest_media_type_is_not_repaired_by_whitespace(self) -> None:
        entries = {
            "OEBPS/Text/ch1.xhtml": b"<html><body><p>Readable.</p></body></html>"
        }
        for media_type in (
            " application/xhtml+xml",
            "application/xhtml+xml ",
            "application/ xhtml+xml",
            "application/xhtml +xml",
        ):
            with self.subTest(media_type=media_type):
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            '    <item id="c1" href="Text/ch1.xhtml" '
                            f'media-type="{media_type}"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries=entries,
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="media-type-whitespace.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_manifest_media_type_requires_exact_mime_type_and_subtype_tokens(self) -> None:
        cases = (
            "",
            "image/",
            "/png",
            "image//png",
            "image/png;charset=utf-8",
            "image/png?variant",
            "image/png=alias",
            "imäge/png",
            "image/pñg",
            "image/&#x7F;png",
        )
        for media_type in cases:
            with self.subTest(media_type=media_type):
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            '    <item id="c1" href="Text/ch1.xhtml" '
                            'media-type="application/xhtml+xml"/>\n'
                            '    <item id="image" href="Images/board.bin" '
                            f'media-type="{media_type}"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={
                        "OEBPS/Text/ch1.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        ),
                        "OEBPS/Images/board.bin": b"opaque-bytes",
                    },
                )

                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="malformed-media-type.epub")

                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_valid_vendor_image_media_type_remains_image_authority(self) -> None:
        chapter = (
            b'<html><body><img src="../Images/board.bin" '
            b'alt="Vendor image"/></body></html>'
        )
        raw = _epub(
            opf=_opf(
                manifest='''    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="image" href="Images/board.bin" media-type="IMAGE/VND.EXAMPLE+PNG"/>''',
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/Text/ch1.xhtml": chapter,
                "OEBPS/Images/board.bin": b"opaque-bytes",
            },
        )

        result = import_epub_book(raw, source_name="vendor-image-media.epub")

        self.assertEqual(
            result.image_references,
            ("OEBPS/Images/board.bin",),
        )
        self.assertIn(
            "Vendor image",
            [
                block.text
                for block in result.document.blocks
                if isinstance(block, Note)
            ],
        )

    def test_manifest_media_type_matching_remains_case_insensitive(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest=(
                    '    <item id="c1" href="Text/ch1.xhtml" '
                    'media-type="APPLICATION/XHTML+XML"/>'
                ),
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/Text/ch1.xhtml": (
                    b"<html><body><p>Case-insensitive MIME type.</p></body></html>"
                )
            },
        )
        result = import_epub_book(raw, source_name="media-type-case.epub")
        self.assertEqual(result.spine_documents, 1)
        self.assertIn(
            "Case-insensitive MIME type.",
            [
                block.text
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ],
        )

    def test_package_and_metadata_mixed_text_fail_closed(self) -> None:
        base = _opf(
            manifest=(
                '    <item id="c1" href="Text/ch1.xhtml" '
                'media-type="application/xhtml+xml"/>'
            ),
            spine='    <itemref idref="c1"/>',
        )
        cases = (
            base.replace(b"  <metadata>", b"package-text\n  <metadata>", 1),
            base.replace(b"<metadata>", b"<metadata>metadata-text", 1),
            base.replace(b"</dc:title>", b"</dc:title>metadata-tail", 1),
        )
        for opf in cases:
            with self.subTest(opf=opf):
                raw = _epub(
                    opf=opf,
                    entries={
                        "OEBPS/Text/ch1.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        )
                    },
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="mixed-package-text.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_required_opf_sections_must_be_first_three_opf_children(self) -> None:
        base = _opf(
            manifest=(
                '    <item id="c1" href="Text/ch1.xhtml" '
                'media-type="application/xhtml+xml"/>'
            ),
            spine='    <itemref idref="c1"/>',
        )
        cases = (
            base.replace(
                b"  <metadata>",
                b"  <guide/>\n  <metadata>",
                1,
            ),
            base.replace(
                b"  </metadata>\n  <manifest>",
                b"  </metadata>\n  <guide/>\n  <manifest>",
                1,
            ),
            base.replace(
                b"  </manifest>\n  <spine>",
                b"  </manifest>\n  <guide/>\n  <spine>",
                1,
            ),
        )
        for opf in cases:
            with self.subTest(opf=opf):
                raw = _epub(
                    opf=opf,
                    entries={
                        "OEBPS/Text/ch1.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        )
                    },
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="misordered-package.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_invalid_versioned_opf_top_level_tail_fails_closed(self) -> None:
        base = _opf(
            manifest=(
                '    <item id="c1" href="Text/ch1.xhtml" '
                'media-type="application/xhtml+xml"/>'
            ),
            spine='    <itemref idref="c1"/>',
        )
        closing = b"  </spine>\n</package>"
        cases = (
            base.replace(
                closing,
                b'''  </spine>
  <item id="rogue" href="Text/rogue.xhtml" media-type="application/xhtml+xml"/>
</package>''',
                1,
            ),
            base.replace(
                closing,
                b'''  </spine>
  <collection role="preview"><link href="Text/ch1.xhtml"/></collection>
  <guide><reference type="toc" title="Contents" href="Text/ch1.xhtml"/></guide>
</package>''',
                1,
            ),
            base.replace(
                closing,
                b'''  </spine>
  <guide><reference type="toc" title="Contents" href="Text/ch1.xhtml"/></guide>
  <guide><reference type="text" title="Text" href="Text/ch1.xhtml"/></guide>
</package>''',
                1,
            ),
            base.replace(b'version="3.0"', b'version="2.0"', 1).replace(
                closing,
                b'''  </spine>
  <collection role="preview"><link href="Text/ch1.xhtml"/></collection>
</package>''',
                1,
            ),
        )
        for opf in cases:
            with self.subTest(opf=opf):
                raw = _epub(
                    opf=opf,
                    entries={
                        "OEBPS/Text/ch1.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        ),
                        "OEBPS/Text/rogue.xhtml": (
                            b"<html><body><p>Rogue.</p></body></html>"
                        ),
                    },
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="invalid-package-tail.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_versioned_opf_top_level_optional_order_is_preserved(self) -> None:
        base = _opf(
            manifest=(
                '    <item id="c1" href="Text/ch1.xhtml" '
                'media-type="application/xhtml+xml"/>'
            ),
            spine='    <itemref idref="c1"/>',
        )
        closing = b"  </spine>\n</package>"
        epub3 = base.replace(
            closing,
            b'''  </spine>
  <guide><reference type="toc" title="Contents" href="Text/ch1.xhtml"/></guide>
  <collection role="preview"><link href="Text/ch1.xhtml"/></collection>
</package>''',
            1,
        )
        epub2 = base.replace(b'version="3.0"', b'version="2.0"', 1).replace(
            closing,
            b'''  </spine>
  <tours><tour id="tour1" title="Tour"><site title="Start" href="Text/ch1.xhtml"/></tour></tours>
  <guide><reference type="toc" title="Contents" href="Text/ch1.xhtml"/></guide>
</package>''',
            1,
        )
        for opf in (epub3, epub2):
            with self.subTest(opf=opf):
                result = import_epub_book(
                    _epub(
                        opf=opf,
                        entries={
                            "OEBPS/Text/ch1.xhtml": (
                                b"<html><body><p>Readable.</p></body></html>"
                            ),
                        },
                    ),
                    source_name="valid-package-tail.epub",
                )
                self.assertEqual(result.spine_documents, 1)

    def test_all_recognized_epub_ids_reject_empty_or_whitespace_values(self) -> None:
        base = _opf(
            manifest=(
                '    <item id="c1" href="Text/ch1.xhtml" '
                'media-type="application/xhtml+xml"/>'
            ),
            spine='    <itemref idref="c1"/>',
        )
        cases = (
            base.replace(
                b'<package version="3.0"',
                b'<package id=" bad " version="3.0"',
                1,
            ),
            base.replace(
                b"<dc:title>",
                b'<dc:title id="">',
                1,
            ),
            base.replace(
                b"<manifest>",
                b'<manifest id="bad id">',
                1,
            ),
            base.replace(
                b"<spine>",
                b'<spine id=" bad">',
                1,
            ),
            base.replace(
                b'<itemref idref="c1"/>',
                b'<itemref id="bad id" idref="c1"/>',
                1,
            ),
        )
        for opf in cases:
            with self.subTest(opf=opf):
                raw = _epub(
                    opf=opf,
                    entries={
                        "OEBPS/Text/ch1.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        )
                    },
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="malformed-package-id.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_manifest_media_overlay_identifier_is_exact(self) -> None:
        entries = {
            "OEBPS/Text/ch1.xhtml": b"<html><body><p>Readable.</p></body></html>",
            "OEBPS/Audio/ch1.smil": b"<smil/>",
        }
        for media_overlay in ("", " overlay ", "bad id"):
            with self.subTest(media_overlay=media_overlay):
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            '    <item id="c1" href="Text/ch1.xhtml" '
                            'media-type="application/xhtml+xml" '
                            f'media-overlay="{media_overlay}"/>\n'
                            '    <item id="overlay" href="Audio/ch1.smil" '
                            'media-type="application/smil+xml"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries=entries,
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="bad-media-overlay-id.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_manifest_media_overlay_reference_must_exist(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest=(
                    '    <item id="c1" href="Text/ch1.xhtml" '
                    'media-type="application/xhtml+xml" media-overlay="missing"/>'
                ),
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/Text/ch1.xhtml": (
                    b"<html><body><p>Readable.</p></body></html>"
                )
            },
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="missing-media-overlay.epub")
        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_manifest_media_overlay_target_must_be_smil(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest=(
                    '    <item id="c1" href="Text/ch1.xhtml" '
                    'media-type="application/xhtml+xml" media-overlay="overlay"/>\n'
                    '    <item id="overlay" href="Audio/ch1.xml" '
                    'media-type="application/xml"/>'
                ),
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/Text/ch1.xhtml": (
                    b"<html><body><p>Readable.</p></body></html>"
                ),
                "OEBPS/Audio/ch1.xml": b"<smil/>",
            },
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="wrong-media-overlay-type.epub")
        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_manifest_media_overlay_is_only_valid_on_epub_content_document(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest=(
                    '    <item id="c1" href="Text/ch1.xhtml" '
                    'media-type="application/xhtml+xml"/>\n'
                    '    <item id="image" href="Images/board.png" '
                    'media-type="image/png" media-overlay="overlay"/>\n'
                    '    <item id="overlay" href="Audio/ch1.smil" '
                    'media-type="application/smil+xml"/>'
                ),
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/Text/ch1.xhtml": (
                    b"<html><body><p>Readable.</p></body></html>"
                ),
                "OEBPS/Images/board.png": b"image-bytes",
                "OEBPS/Audio/ch1.smil": b"<smil/>",
            },
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="overlay-on-image.epub")
        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_valid_manifest_media_overlay_relationship_is_ignored_safely(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest=(
                    '    <item id="c1" href="Text/ch1.xhtml" '
                    'media-type="application/xhtml+xml" media-overlay="overlay"/>\n'
                    '    <item id="overlay" href="Audio/ch1.smil" '
                    'media-type="application/smil+xml"/>'
                ),
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/Text/ch1.xhtml": (
                    b"<html><body><p>Readable with overlay metadata.</p></body></html>"
                ),
                "OEBPS/Audio/ch1.smil": b"<smil/>",
            },
        )
        result = import_epub_book(raw, source_name="valid-media-overlay.epub")
        self.assertEqual(result.spine_documents, 1)
        self.assertIn(
            "Readable with overlay metadata.",
            [
                block.text
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ],
        )

    def test_spine_legacy_toc_identifier_is_exact(self) -> None:
        manifest = (
            '    <item id="c1" href="Text/ch1.xhtml" '
            'media-type="application/xhtml+xml"/>\n'
            '    <item id="ncx" href="toc.ncx" '
            'media-type="application/x-dtbncx+xml"/>'
        )
        entries = {
            "OEBPS/Text/ch1.xhtml": b"<html><body><p>Readable.</p></body></html>",
            "OEBPS/toc.ncx": b"<ncx/>",
        }
        for toc in ("", " ncx ", "bad id"):
            with self.subTest(toc=toc):
                opf = _opf(
                    manifest=manifest,
                    spine='    <itemref idref="c1"/>',
                ).replace(
                    b"<spine>",
                    f'<spine toc="{toc}">'.encode("utf-8"),
                    1,
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(
                        _epub(opf=opf, entries=entries),
                        source_name="bad-spine-toc.epub",
                    )
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_spine_legacy_toc_must_resolve_to_ncx_manifest_item(self) -> None:
        cases = (
            (
                '    <item id="c1" href="Text/ch1.xhtml" '
                'media-type="application/xhtml+xml"/>',
                "missing",
                {
                    "OEBPS/Text/ch1.xhtml": (
                        b"<html><body><p>Readable.</p></body></html>"
                    )
                },
            ),
            (
                '    <item id="c1" href="Text/ch1.xhtml" '
                'media-type="application/xhtml+xml"/>\n'
                '    <item id="tocitem" href="toc.xml" '
                'media-type="application/xml"/>',
                "tocitem",
                {
                    "OEBPS/Text/ch1.xhtml": (
                        b"<html><body><p>Readable.</p></body></html>"
                    ),
                    "OEBPS/toc.xml": b"<ncx/>",
                },
            ),
        )
        for manifest, toc, entries in cases:
            with self.subTest(toc=toc):
                opf = _opf(
                    manifest=manifest,
                    spine='    <itemref idref="c1"/>',
                ).replace(
                    b"<spine>",
                    f'<spine toc="{toc}">'.encode("ascii"),
                    1,
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(
                        _epub(opf=opf, entries=entries),
                        source_name="invalid-spine-toc-target.epub",
                    )
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_valid_spine_legacy_ncx_reference_remains_readable(self) -> None:
        opf = _opf(
            manifest=(
                '    <item id="c1" href="Text/ch1.xhtml" '
                'media-type="application/xhtml+xml"/>\n'
                '    <item id="ncx" href="toc.ncx" '
                'media-type="application/x-dtbncx+xml"/>'
            ),
            spine='    <itemref idref="c1"/>',
        ).replace(b"<spine>", b'<spine toc="ncx">', 1)
        result = import_epub_book(
            _epub(
                opf=opf,
                entries={
                    "OEBPS/Text/ch1.xhtml": (
                        b"<html><body><p>Readable with NCX metadata.</p></body></html>"
                    ),
                    "OEBPS/toc.ncx": b"<ncx/>",
                },
            ),
            source_name="valid-spine-toc.epub",
        )
        self.assertEqual(result.spine_documents, 1)
        self.assertIn(
            "Readable with NCX metadata.",
            [
                block.text
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ],
        )

    def test_required_title_and_language_metadata_fail_closed_when_missing_or_empty(self) -> None:
        cases = (
            '''
    <dc:identifier id="bookid">urn:uuid:test-fixture</dc:identifier>
    <dc:language>uk</dc:language>''',
            '''
    <dc:identifier id="bookid">urn:uuid:test-fixture</dc:identifier>
    <dc:title>Readable title</dc:title>''',
            '''
    <dc:identifier id="bookid">urn:uuid:test-fixture</dc:identifier>
    <dc:title>   </dc:title>
    <dc:language>uk</dc:language>''',
            '''
    <dc:identifier id="bookid">urn:uuid:test-fixture</dc:identifier>
    <dc:title>Readable title</dc:title>
    <dc:language>   </dc:language>''',
        )
        for metadata in cases:
            with self.subTest(metadata=metadata):
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            '    <item id="c1" href="Text/ch1.xhtml" '
                            'media-type="application/xhtml+xml"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                        metadata=metadata,
                    ),
                    entries={
                        "OEBPS/Text/ch1.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        )
                    },
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="missing-core-metadata.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_dublin_core_metadata_values_must_be_nonempty_text(self) -> None:
        cases = (
            '''
    <dc:identifier id="bookid">urn:uuid:test-fixture</dc:identifier>
    <dc:title><dc:creator>Nested</dc:creator></dc:title>
    <dc:language>uk</dc:language>''',
            '''
    <dc:identifier id="bookid">urn:uuid:test-fixture</dc:identifier>
    <dc:title>Readable title</dc:title>
    <dc:creator>   </dc:creator>
    <dc:language>uk</dc:language>''',
            '''
    <dc:identifier id="bookid">urn:uuid:test-fixture</dc:identifier>
    <dc:title>Readable title</dc:title>
    <dc:language>uk</dc:language>
    <dc:rights></dc:rights>''',
        )
        for metadata in cases:
            with self.subTest(metadata=metadata):
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            '    <item id="c1" href="Text/ch1.xhtml" '
                            'media-type="application/xhtml+xml"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                        metadata=metadata,
                    ),
                    entries={
                        "OEBPS/Text/ch1.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        )
                    },
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="bad-dc-value.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_metadata_rejects_unrecognized_opf_native_children(self) -> None:
        metadata = '''
    <dc:identifier id="bookid">urn:uuid:test-fixture</dc:identifier>
    <dc:title>Readable title</dc:title>
    <dc:language>uk</dc:language>
    <item id="nested" href="unexpected.xhtml" media-type="application/xhtml+xml"/>'''
        raw = _epub(
            opf=_opf(
                manifest=(
                    '    <item id="c1" href="Text/ch1.xhtml" '
                    'media-type="application/xhtml+xml"/>'
                ),
                spine='    <itemref idref="c1"/>',
                metadata=metadata,
            ),
            entries={
                "OEBPS/Text/ch1.xhtml": (
                    b"<html><body><p>Readable.</p></body></html>"
                ),
            },
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="nested-opf-metadata.epub")
        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_unicode_package_identifier_without_whitespace_remains_supported(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest=(
                    '    <item id="розділ" href="Text/ch1.xhtml" '
                    'media-type="application/xhtml+xml"/>'
                ),
                spine='    <itemref idref="розділ"/>',
            ),
            entries={
                "OEBPS/Text/ch1.xhtml": b"<html><body><p>Readable Unicode ID.</p></body></html>",
            },
        )
        result = import_epub_book(raw, source_name="unicode-id.epub")
        self.assertEqual(result.spine_documents, 1)
        self.assertEqual(
            [block.text for block in result.document.blocks if isinstance(block, Paragraph)],
            ["Readable Unicode ID."],
        )

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

    def test_spine_linear_attribute_rejects_invalid_tokens(self) -> None:
        manifest = (
            '    <item id="c1" href="Text/ch1.xhtml" '
            'media-type="application/xhtml+xml"/>'
        )
        entries = {
            "OEBPS/Text/ch1.xhtml": b"<html><body><p>Readable.</p></body></html>"
        }
        for raw_linear in ("", "maybe", " no "):
            with self.subTest(linear=raw_linear):
                raw = _epub(
                    opf=_opf(
                        manifest=manifest,
                        spine=(
                            '    <itemref idref="c1" linear="'
                            + raw_linear
                            + '"/>'
                        ),
                    ),
                    entries=entries,
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="invalid-linear.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_spine_rejects_duplicate_manifest_reference(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest=(
                    '    <item id="c1" href="Text/ch1.xhtml" '
                    'media-type="application/xhtml+xml"/>'
                ),
                spine='''    <itemref idref="c1"/>
    <itemref idref="c1"/>''',
            ),
            entries={
                "OEBPS/Text/ch1.xhtml": (
                    b"<html><body><p>Must not be duplicated.</p></body></html>"
                )
            },
        )

        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="duplicate-spine-reference.epub")
        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_spine_requires_at_least_one_linear_item(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest='''    <item id="a" href="Text/a.xhtml" media-type="application/xhtml+xml"/>
    <item id="b" href="Text/b.xhtml" media-type="application/xhtml+xml"/>''',
                spine='''    <itemref idref="a" linear="no"/>
    <itemref idref="b" linear="no"/>''',
            ),
            entries={
                "OEBPS/Text/a.xhtml": b"<html><body><p>Aux A.</p></body></html>",
                "OEBPS/Text/b.xhtml": b"<html><body><p>Aux B.</p></body></html>",
            },
        )

        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="all-nonlinear.epub")
        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_spine_linear_yes_is_explicitly_accepted(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest=(
                    '    <item id="c1" href="Text/ch1.xhtml" '
                    'media-type="application/xhtml+xml"/>'
                ),
                spine='    <itemref idref="c1" linear="yes"/>',
            ),
            entries={
                "OEBPS/Text/ch1.xhtml": (
                    b"<html><body><p>Explicit linear item.</p></body></html>"
                )
            },
        )

        result = import_epub_book(raw, source_name="explicit-linear.epub")
        self.assertEqual(result.spine_documents, 1)
        self.assertIn(
            "Explicit linear item.",
            [
                block.text
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ],
        )

    def test_manifest_and_spine_empty_content_models_fail_closed(self) -> None:
        cases = (
            (
                '    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml">text</item>',
                '    <itemref idref="c1"/>',
            ),
            (
                '    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"><meta/></item>',
                '    <itemref idref="c1"/>',
            ),
            (
                '    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>',
                '    <itemref idref="c1">text</itemref>',
            ),
            (
                '    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>',
                '    <itemref idref="c1"><meta/></itemref>',
            ),
        )
        for manifest, spine in cases:
            with self.subTest(manifest=manifest, spine=spine):
                raw = _epub(
                    opf=_opf(manifest=manifest, spine=spine),
                    entries={
                        "OEBPS/Text/ch1.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        ),
                    },
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="non-empty-item-model.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_manifest_and_spine_mixed_text_fail_closed(self) -> None:
        cases = (
            (
                'manifest-text\n    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>',
                '    <itemref idref="c1"/>',
            ),
            (
                '    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>tail-text',
                '    <itemref idref="c1"/>',
            ),
            (
                '    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>',
                'spine-text\n    <itemref idref="c1"/>',
            ),
            (
                '    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>',
                '    <itemref idref="c1"/>tail-text',
            ),
        )
        for manifest, spine in cases:
            with self.subTest(manifest=manifest, spine=spine):
                raw = _epub(
                    opf=_opf(manifest=manifest, spine=spine),
                    entries={
                        "OEBPS/Text/ch1.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        ),
                    },
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="mixed-section-text.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_manifest_and_spine_reject_unexpected_opf_children(self) -> None:
        cases = (
            (
                '''    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>
    <meta property="x:test">unexpected</meta>''',
                '    <itemref idref="c1"/>',
            ),
            (
                '    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>',
                '''    <itemref idref="c1"/>
    <meta property="x:test">unexpected</meta>''',
            ),
        )
        for manifest, spine in cases:
            with self.subTest(manifest=manifest, spine=spine):
                raw = _epub(
                    opf=_opf(manifest=manifest, spine=spine),
                    entries={
                        "OEBPS/Text/ch1.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        ),
                    },
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="unexpected-opf-child.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_unused_manifest_fallback_reference_is_still_validated(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest='''    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="unused" href="unused.svg" media-type="image/svg+xml" fallback="missing"/>''',
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/Text/ch1.xhtml": (
                    b"<html><body><p>Readable.</p></body></html>"
                ),
                "OEBPS/unused.svg": b"<svg/>",
            },
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="unused-missing-fallback.epub")
        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_unused_manifest_fallback_cycle_is_still_rejected(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest='''    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="a" href="a.svg" media-type="image/svg+xml" fallback="b"/>
    <item id="b" href="b.svg" media-type="image/svg+xml" fallback="a"/>''',
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/Text/ch1.xhtml": (
                    b"<html><body><p>Readable.</p></body></html>"
                ),
                "OEBPS/a.svg": b"<svg/>",
                "OEBPS/b.svg": b"<svg/>",
            },
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="unused-fallback-cycle.epub")
        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_unused_manifest_fallback_chain_is_bounded(self) -> None:
        fallback_items = []
        entries = {
            "OEBPS/Text/ch1.xhtml": b"<html><body><p>Readable.</p></body></html>"
        }
        for index in range(17):
            fallback = f' fallback="f{index + 1}"' if index < 16 else ""
            fallback_items.append(
                f'    <item id="f{index}" href="f{index}.svg" '
                f'media-type="image/svg+xml"{fallback}/>'
            )
            entries[f"OEBPS/f{index}.svg"] = b"<svg/>"
        raw = _epub(
            opf=_opf(
                manifest=(
                    '    <item id="c1" href="Text/ch1.xhtml" '
                    'media-type="application/xhtml+xml"/>\n'
                    + "\n".join(fallback_items)
                ),
                spine='    <itemref idref="c1"/>',
            ),
            entries=entries,
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="unused-deep-fallback.epub")
        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.RESOURCE_LIMIT,
        )

    def test_manifest_rejects_restricted_package_resources(self) -> None:
        for href in ("content.opf", "../mimetype", "../META-INF/container.xml"):
            with self.subTest(href=href):
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            '    <item id="c1" href="Text/ch1.xhtml" '
                            'media-type="application/xhtml+xml"/>\n'
                            f'    <item id="reserved" href="{href}" '
                            'media-type="application/octet-stream"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={
                        "OEBPS/Text/ch1.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        ),
                    },
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="reserved-manifest-resource.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_manifest_rejects_missing_local_resource_even_when_unused(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest='''    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="missing" href="Images/missing.png" media-type="image/png"/>''',
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/Text/ch1.xhtml": (
                    b"<html><body><p>Readable.</p></body></html>"
                ),
            },
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="missing-unused-resource.epub")
        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_spine_page_progression_direction_is_exact(self) -> None:
        manifest = (
            '    <item id="c1" href="Text/ch1.xhtml" '
            'media-type="application/xhtml+xml"/>'
        )
        entries = {
            "OEBPS/Text/ch1.xhtml": b"<html><body><p>Readable.</p></body></html>"
        }
        for direction in ("ltr", "rtl", "default"):
            with self.subTest(direction=direction):
                opf = _opf(
                    manifest=manifest,
                    spine='    <itemref idref="c1"/>',
                ).replace(
                    b"<spine>",
                    f'<spine page-progression-direction="{direction}">'.encode("ascii"),
                    1,
                )
                result = import_epub_book(
                    _epub(opf=opf, entries=entries),
                    source_name="valid-progression.epub",
                )
                self.assertEqual(result.spine_documents, 1)

        for direction in ("", "LTR", "sideways", " rtl "):
            with self.subTest(invalid_direction=direction):
                opf = _opf(
                    manifest=manifest,
                    spine='    <itemref idref="c1"/>',
                ).replace(
                    b"<spine>",
                    f'<spine page-progression-direction="{direction}">'.encode("ascii"),
                    1,
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(
                        _epub(opf=opf, entries=entries),
                        source_name="invalid-progression.epub",
                    )
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_foreign_spine_content_requires_epub_content_fallback(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest='''    <item id="foreign" href="attachment.pdf" media-type="application/pdf"/>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>''',
                spine='''    <itemref idref="foreign" linear="no"/>
    <itemref idref="chapter"/>''',
            ),
            entries={
                "OEBPS/attachment.pdf": b"%PDF-not-decoded",
                "OEBPS/chapter.xhtml": (
                    b"<html><body><p>Readable chapter.</p></body></html>"
                ),
            },
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="foreign-without-fallback.epub")
        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_foreign_spine_content_with_xhtml_fallback_remains_readable(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest='''    <item id="foreign" href="attachment.pdf" media-type="application/pdf" fallback="fallback"/>
    <item id="fallback" href="fallback.xhtml" media-type="application/xhtml+xml"/>''',
                spine='    <itemref idref="foreign"/>',
            ),
            entries={
                "OEBPS/attachment.pdf": b"%PDF-not-decoded",
                "OEBPS/fallback.xhtml": (
                    b"<html><body><p>Fallback text.</p></body></html>"
                ),
            },
        )
        result = import_epub_book(raw, source_name="foreign-with-fallback.epub")
        self.assertEqual(result.spine_documents, 1)
        self.assertEqual(
            [block.text for block in result.document.blocks if isinstance(block, Paragraph)],
            ["Fallback text."],
        )

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

    def test_existing_unmanifested_package_image_is_not_published(self) -> None:
        chapter = (
            b'<html><body><img src="../Images/unlisted.png" '
            b'alt="Unlisted visual"/></body></html>'
        )
        raw = _epub(
            opf=_opf(
                manifest=(
                    '    <item id="c1" href="Text/chapter.xhtml" '
                    'media-type="application/xhtml+xml"/>'
                ),
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/Text/chapter.xhtml": chapter,
                "OEBPS/Images/unlisted.png": b"image-bytes",
            },
        )

        result = import_epub_book(raw, source_name="unmanifested-image.epub")

        self.assertEqual(result.image_references, ())
        self.assertTrue(
            any(
                "not declared in the manifest" in warning
                for warning in result.warnings
            )
        )
        self.assertIn(
            "Unlisted visual",
            [
                block.text
                for block in result.document.blocks
                if isinstance(block, Note)
            ],
        )

    def test_manifest_non_image_resource_cannot_be_published_as_image(self) -> None:
        chapter = (
            b'<html><body><img src="../Data/payload.bin" '
            b'alt="Accessible fallback"/></body></html>'
        )
        raw = _epub(
            opf=_opf(
                manifest='''    <item id="c1" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>
    <item id="payload" href="Data/payload.bin" media-type="application/octet-stream"/>''',
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/Text/chapter.xhtml": chapter,
                "OEBPS/Data/payload.bin": b"not-image-bytes",
            },
        )

        result = import_epub_book(raw, source_name="wrong-image-media.epub")

        self.assertEqual(result.image_references, ())
        self.assertTrue(
            any(
                "not declared as an image" in warning
                for warning in result.warnings
            )
        )
        self.assertIn(
            "Accessible fallback",
            [
                block.text
                for block in result.document.blocks
                if isinstance(block, Note)
            ],
        )

    def test_ocf_service_files_cannot_be_published_as_images(self) -> None:
        for src in (
            "../../META-INF/container.xml",
            "../content.opf",
            "../../mimetype",
        ):
            with self.subTest(src=src):
                chapter = (
                    f'<html><body><img src="{src}" '
                    'alt="Service-file fallback"/></body></html>'
                ).encode("utf-8")
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            '    <item id="c1" href="Text/chapter.xhtml" '
                            'media-type="application/xhtml+xml"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={
                        "OEBPS/Text/chapter.xhtml": chapter,
                    },
                )

                result = import_epub_book(
                    raw,
                    source_name="service-file-image.epub",
                )

                self.assertEqual(result.image_references, ())
                self.assertTrue(
                    any(
                        "not declared in the manifest" in warning
                        for warning in result.warnings
                    )
                )
                self.assertIn(
                    "Service-file fallback",
                    [
                        block.text
                        for block in result.document.blocks
                        if isinstance(block, Note)
                    ],
                )

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

    def test_mimetype_zip_extra_field_is_rejected(self) -> None:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            mimetype = zipfile.ZipInfo("mimetype")
            mimetype.compress_type = zipfile.ZIP_STORED
            mimetype.extra = b"\x01\x00\x00\x00"
            archive.writestr(mimetype, b"application/epub+zip")

        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(buffer.getvalue(), source_name="mimetype-extra.epub")

        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.UNSUPPORTED_CONTAINER,
        )

    def test_zip_encryption_flag_is_rejected_even_on_unused_resource(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest=(
                    '    <item id="c1" href="chapter.xhtml" '
                    'media-type="application/xhtml+xml"/>'
                ),
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/chapter.xhtml": (
                    b"<html><body><p>Readable.</p></body></html>"
                ),
                "OEBPS/unused.bin": b"not part of the publication manifest",
            },
        )
        raw = _mark_zip_entry_encrypted(raw, "OEBPS/unused.bin")

        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="zip-encrypted-unused.epub")

        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.UNSUPPORTED_CONTAINER,
        )

    def test_corrupt_deflate_is_wrapped_as_stable_container_error(self) -> None:
        raw = _simple_epub(b"<html><body><p>Readable.</p></body></html>")
        raw = _corrupt_deflated_entry(raw, "OEBPS/content.opf")

        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="corrupt-deflate.epub")

        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.UNSUPPORTED_CONTAINER,
        )

    def test_special_or_contradictory_zip_entry_types_fail_closed(self) -> None:
        cases = (
            ("OEBPS/fifo", stat.S_IFIFO | 0o644),
            ("OEBPS/device", stat.S_IFCHR | 0o600),
            ("OEBPS/socket", stat.S_IFSOCK | 0o600),
            ("OEBPS/directory-without-slash", stat.S_IFDIR | 0o755),
            ("OEBPS/regular-file/", stat.S_IFREG | 0o644),
        )
        for name, mode in cases:
            with self.subTest(name=name, mode=mode):
                buffer = BytesIO()
                with zipfile.ZipFile(buffer, "w") as archive:
                    mimetype = zipfile.ZipInfo("mimetype")
                    mimetype.compress_type = zipfile.ZIP_STORED
                    archive.writestr(mimetype, b"application/epub+zip")

                    special = zipfile.ZipInfo(name)
                    special.create_system = 3
                    special.external_attr = mode << 16
                    archive.writestr(special, b"not a regular EPUB resource")

                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(
                        buffer.getvalue(),
                        source_name="special-entry.epub",
                    )
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.UNSAFE_PACKAGE,
                )
                self.assertNotIn(name, str(raised.exception))

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

    def test_canonical_casefold_package_name_collisions_are_rejected(self) -> None:
        collision_pairs = (
            ("OEBPS/Text/Straße.txt", "OEBPS/Text/STRASSE.txt"),
            ("OEBPS/Text/café.txt", "OEBPS/Text/cafe\u0301.txt"),
            ("OEBPS/CaseDir/one.txt", "OEBPS/casedir/two.txt"),
        )
        for first, second in collision_pairs:
            with self.subTest(first=first, second=second):
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            '    <item id="c1" href="chapter.xhtml" '
                            'media-type="application/xhtml+xml"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={
                        "OEBPS/chapter.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        ),
                    },
                    prepend=[(first, b"one"), (second, b"two")],
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="canonical-collision.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.UNSAFE_PACKAGE,
                )

    def test_manifest_rejects_multiple_ids_for_same_resolved_resource(self) -> None:
        cases = (
            ("Text/chapter.xhtml", "Text/chapter.xhtml"),
            ("Text/chapter.xhtml", "Text/%63hapter.xhtml"),
            ("Text/%63hapter.xhtml", "Text/chapter.xhtml"),
        )
        for first_href, second_href in cases:
            with self.subTest(first_href=first_href, second_href=second_href):
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            f'    <item id="c1" href="{first_href}" '
                            'media-type="application/xhtml+xml"/>\n'
                            f'    <item id="c2" href="{second_href}" '
                            'media-type="application/xhtml+xml"/>'
                        ),
                        spine='    <itemref idref="c1"/>\n    <itemref idref="c2"/>',
                    ),
                    entries={
                        "OEBPS/Text/chapter.xhtml": (
                            b"<html><body><p>One canonical chapter.</p></body></html>"
                        ),
                    },
                )

                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="duplicate-manifest-resource.epub")

                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )
                self.assertIn("same package resource", str(raised.exception))

    def test_manifest_keeps_distinct_resolved_resources_distinct(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest=(
                    '    <item id="c1" href="Text/one.xhtml" '
                    'media-type="application/xhtml+xml"/>\n'
                    '    <item id="c2" href="Text/two.xhtml" '
                    'media-type="application/xhtml+xml"/>'
                ),
                spine='    <itemref idref="c1"/>\n    <itemref idref="c2"/>',
            ),
            entries={
                "OEBPS/Text/one.xhtml": b"<html><body><p>First chapter.</p></body></html>",
                "OEBPS/Text/two.xhtml": b"<html><body><p>Second chapter.</p></body></html>",
            },
        )

        result = import_epub_book(raw, source_name="distinct-manifest-resources.epub")
        self.assertEqual(result.spine_documents, 2)
        self.assertEqual(
            [block.text for block in result.document.blocks if isinstance(block, Paragraph)],
            ["First chapter.", "Second chapter."],
        )

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

    def test_package_urls_are_not_repaired_by_surrounding_whitespace(self) -> None:
        for href in (" Text/chapter.xhtml", "Text/chapter.xhtml ", "\tText/chapter.xhtml"):
            with self.subTest(href=href):
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            f'    <item id="c1" href="{href}" '
                            'media-type="application/xhtml+xml"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={
                        "OEBPS/Text/chapter.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        ),
                    },
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="manifest-url-whitespace.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

        container = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path=" OEBPS/content.opf " media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''
        raw = _epub(
            opf=_opf(
                manifest='    <item id="c1" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>',
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/Text/chapter.xhtml": b"<html><body><p>Readable.</p></body></html>",
            },
            container=container,
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="rootfile-url-whitespace.epub")
        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_manifest_item_href_fragment_is_rejected(self) -> None:
        for href in ("Text/chapter.xhtml#start", "Text/chapter.xhtml#"):
            with self.subTest(href=href):
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            f'    <item id="c1" href="{href}" '
                            'media-type="application/xhtml+xml"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={
                        "OEBPS/Text/chapter.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        ),
                    },
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="manifest-fragment.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_malformed_percent_encoding_cannot_alias_package_resources(self) -> None:
        cases = (
            "Text/%FF.xhtml",
            "Text/%C3%28.xhtml",
            "Text/%2.xhtml",
            "Text/%GG.xhtml",
        )
        for href in cases:
            with self.subTest(href=href):
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            f'    <item id="c1" href="{href}" '
                            'media-type="application/xhtml+xml"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={
                        "OEBPS/Text/�.xhtml": (
                            b"<html><body><p>Wrong replacement target.</p></body></html>"
                        ),
                    },
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="malformed-percent.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_percent_encoded_slash_cannot_alias_archive_hierarchy(self) -> None:
        for href in ("Text%2Fchapter.xhtml", "Text%2fchapter.xhtml"):
            with self.subTest(href=href):
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            f'    <item id="c1" href="{href}" '
                            'media-type="application/xhtml+xml"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={
                        "OEBPS/Text/chapter.xhtml": (
                            b"<html><body><p>Wrong hierarchy target.</p></body></html>"
                        ),
                    },
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="encoded-slash.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_valid_percent_encoded_utf8_package_path_is_preserved(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest=(
                    '    <item id="c1" href="Text/%D0%A8%D0%B0%D1%85%D0%B8.xhtml" '
                    'media-type="application/xhtml+xml"/>'
                ),
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/Text/Шахи.xhtml": (
                    "<html><body><p>Український розділ.</p></body></html>".encode("utf-8")
                ),
            },
        )

        result = import_epub_book(raw, source_name="utf8-path.epub")
        self.assertEqual(result.spine_documents, 1)
        self.assertIn(
            "Український розділ.",
            [
                block.text
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ],
        )

    def test_regular_file_and_implicit_directory_identity_collisions_fail_closed(self) -> None:
        collision_orders = (
            (
                ("OEBPS/Collision", b"regular-file"),
                ("OEBPS/Collision/child.bin", b"child"),
            ),
            (
                ("OEBPS/Collision/child.bin", b"child"),
                ("OEBPS/Collision", b"regular-file"),
            ),
        )
        for first, second in collision_orders:
            with self.subTest(first=first[0], second=second[0]):
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            '    <item id="c1" href="chapter.xhtml" '
                            'media-type="application/xhtml+xml"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={
                        "OEBPS/chapter.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        ),
                    },
                    prepend=[first, second],
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="file-directory-collision.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.UNSAFE_PACKAGE,
                )

    def test_percent_encoded_hash_remains_package_path_character(self) -> None:
        raw = _epub(
            opf=_opf(
                manifest=(
                    '    <item id="c1" href="Text/chapter%23one.xhtml" '
                    'media-type="application/xhtml+xml"/>'
                ),
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/Text/chapter#one.xhtml": (
                    b"<html><body><p>Encoded hash path.</p></body></html>"
                ),
            },
        )

        result = import_epub_book(raw, source_name="encoded-hash.epub")
        self.assertEqual(result.spine_documents, 1)
        self.assertIn(
            "Encoded hash path.",
            [
                block.text
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ],
        )

    def test_container_rootfile_fragment_is_rejected(self) -> None:
        container = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf#rendition"
      media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''
        raw = _epub(
            opf=_opf(
                manifest='    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/chapter.xhtml": b"<html><body><p>Readable.</p></body></html>",
            },
            container=container,
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="rootfile-fragment.epub")
        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_container_requires_canonical_namespace_and_exact_version(self) -> None:
        cases = (
            b'''<?xml version="1.0"?><container version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>''',
            b'''<?xml version="1.0"?><container version="2.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>''',
            b'''<?xml version="1.0"?><container version=" 1.0 " xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>''',
        )
        for container in cases:
            with self.subTest(container=container):
                raw = _epub(
                    opf=_opf(
                        manifest='    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={"OEBPS/chapter.xhtml": b"<html><body><p>Readable.</p></body></html>"},
                    container=container,
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="bad-container-root.epub")
                self.assertEqual(raised.exception.code, BookEpubImportErrorCode.MALFORMED_PACKAGE)

    def test_container_rootfile_requires_direct_canonical_identity_and_exact_media_type(self) -> None:
        cases = (
            b'''<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>''',
            b'''<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="APPLICATION/OEBPS-PACKAGE+XML"/></rootfiles></container>''',
            b'''<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type=" application/oebps-package+xml "/></rootfiles></container>''',
            b'''<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:x="urn:foreign"><rootfiles><x:rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>''',
            b'''<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><wrapper><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></wrapper></rootfiles></container>''',
            b'''<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"><unexpected/></rootfile></rootfiles></container>''',
        )
        for container in cases:
            with self.subTest(container=container):
                raw = _epub(
                    opf=_opf(
                        manifest='    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={"OEBPS/chapter.xhtml": b"<html><body><p>Readable.</p></body></html>"},
                    container=container,
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="bad-rootfile.epub")
                self.assertEqual(raised.exception.code, BookEpubImportErrorCode.MALFORMED_PACKAGE)

    def test_container_requires_exactly_one_direct_rootfiles_section(self) -> None:
        for rootfiles_markup in ("", "<rootfiles/><rootfiles/>"):
            with self.subTest(rootfiles_markup=rootfiles_markup):
                container = (
                    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    f"{rootfiles_markup}</container>"
                ).encode("utf-8")
                raw = _epub(
                    opf=_opf(
                        manifest='    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={"OEBPS/chapter.xhtml": b"<html><body><p>Readable.</p></body></html>"},
                    container=container,
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="bad-rootfiles-count.epub")
                self.assertEqual(raised.exception.code, BookEpubImportErrorCode.MALFORMED_PACKAGE)

    def test_container_canonical_children_keep_required_order_and_content_model(self) -> None:
        valid_rootfiles = '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>'
        cases = (
            f"<links/>{valid_rootfiles}",
            f"{valid_rootfiles}<bogus/>",
            f"{valid_rootfiles}<links/><links/>",
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/><bogus/></rootfiles>',
            '<rootfiles>text<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>',
        )
        for markup in cases:
            with self.subTest(markup=markup):
                container = (
                    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    f"{markup}</container>"
                ).encode("utf-8")
                raw = _epub(
                    opf=_opf(
                        manifest='    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={"OEBPS/chapter.xhtml": b"<html><body><p>Readable.</p></body></html>"},
                    container=container,
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="bad-container-structure.epub")
                self.assertEqual(raised.exception.code, BookEpubImportErrorCode.MALFORMED_PACKAGE)

    def test_container_direct_mixed_text_fails_closed(self) -> None:
        valid_rootfiles = (
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles>'
        )
        cases = (
            f"text{valid_rootfiles}",
            f"{valid_rootfiles}tail",
            (
                '<x:ignored xmlns:x="urn:example:foreign"/>'
                f"tail{valid_rootfiles}"
            ),
        )
        for markup in cases:
            with self.subTest(markup=markup):
                container = (
                    '<container version="1.0" '
                    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    f"{markup}</container>"
                ).encode("utf-8")
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            '    <item id="c1" href="chapter.xhtml" '
                            'media-type="application/xhtml+xml"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={
                        "OEBPS/chapter.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        ),
                    },
                    container=container,
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="container-mixed-text.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_container_foreign_tail_text_inside_rootfiles_fails_closed(self) -> None:
        container = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0"
 xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
 xmlns:x="urn:example:foreign">
  <rootfiles>
    <x:ignored/>tail
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''
        raw = _epub(
            opf=_opf(
                manifest=(
                    '    <item id="c1" href="chapter.xhtml" '
                    'media-type="application/xhtml+xml"/>'
                ),
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/chapter.xhtml": (
                    b"<html><body><p>Readable.</p></body></html>"
                ),
            },
            container=container,
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="rootfiles-foreign-tail.epub")
        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_container_links_require_nonempty_valid_ocf_links(self) -> None:
        rootfiles = (
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles>'
        )
        cases = (
            ("<links/>", BookEpubImportErrorCode.MALFORMED_PACKAGE),
            ("<links><bogus/></links>", BookEpubImportErrorCode.MALFORMED_PACKAGE),
            (
                '<links>text<link href="OEBPS/chapter.xhtml" rel="alternate"/></links>',
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            ),
            (
                '<links><link href="OEBPS/chapter.xhtml" rel="alternate"><bogus/></link></links>',
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            ),
            (
                '<links><link rel="alternate"/></links>',
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            ),
            (
                '<links><link href="OEBPS/chapter.xhtml"/></links>',
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            ),
            (
                '<links><link href="https://example.test/map.xml" rel="alternate"/></links>',
                BookEpubImportErrorCode.UNSAFE_PACKAGE,
            ),
            (
                '<links><link href="OEBPS/chapter.xhtml" rel=" alternate "/></links>',
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            ),
            (
                '<links><link href="OEBPS/chapter.xhtml" rel="alternate  mapping"/></links>',
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            ),
        )
        for links_markup, expected_code in cases:
            with self.subTest(links_markup=links_markup):
                container = (
                    '<container version="1.0" '
                    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    f"{rootfiles}{links_markup}</container>"
                ).encode("utf-8")
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            '    <item id="c1" href="chapter.xhtml" '
                            'media-type="application/xhtml+xml"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={
                        "OEBPS/chapter.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        ),
                    },
                    container=container,
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="invalid-container-links.epub")
                self.assertEqual(raised.exception.code, expected_code)

    def test_container_link_path_query_fragment_and_rel_tokens_are_preserved(self) -> None:
        container = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
  <links>
    <link href="OEBPS/chapter.xhtml?view=print#start" rel="alternate mapping"/>
  </links>
</container>'''
        result = import_epub_book(
            _epub(
                opf=_opf(
                    manifest=(
                        '    <item id="c1" href="chapter.xhtml" '
                        'media-type="application/xhtml+xml"/>'
                    ),
                    spine='    <itemref idref="c1"/>',
                ),
                entries={
                    "OEBPS/chapter.xhtml": (
                        b"<html><body><p>Readable.</p></body></html>"
                    ),
                },
                container=container,
            ),
            source_name="valid-container-links.epub",
        )
        self.assertEqual(result.spine_documents, 1)

    def test_container_foreign_extensions_are_removed_before_structure_validation(self) -> None:
        container = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0"
 xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
 xmlns:x="urn:example:foreign">
  <x:ignored><rootfile full-path="WRONG/content.opf" media-type="application/oebps-package+xml"/></x:ignored>
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml">
      <x:extension><x:data/></x:extension>
    </rootfile>
  </rootfiles>
  <links>
    <link href="OEBPS/chapter.xhtml" rel="alternate">
      <x:extension><x:data/></x:extension>
    </link>
  </links>
</container>'''
        raw = _epub(
            opf=_opf(
                manifest='    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
                spine='    <itemref idref="c1"/>',
            ),
            entries={"OEBPS/chapter.xhtml": b"<html><body><p>Foreign extension safe.</p></body></html>"},
            container=container,
        )
        result = import_epub_book(raw, source_name="foreign-extension.epub")
        self.assertEqual(result.spine_documents, 1)
        self.assertIn(
            "Foreign extension safe.",
            [block.text for block in result.document.blocks if isinstance(block, Paragraph)],
        )

    def test_multiple_valid_rootfiles_preserve_first_rendition_policy(self) -> None:
        container = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    <rootfile full-path="ALT/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''
        alternate_opf = _opf(
            manifest=(
                '    <item id="alt" href="chapter.xhtml" '
                'media-type="application/xhtml+xml"/>'
            ),
            spine='    <itemref idref="alt"/>',
        )
        raw = _epub(
            opf=_opf(
                manifest='    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/chapter.xhtml": (
                    b"<html><body><p>Primary rendition.</p></body></html>"
                ),
                "ALT/content.opf": alternate_opf,
                "ALT/chapter.xhtml": (
                    b"<html><body><p>Alternate rendition.</p></body></html>"
                ),
            },
            container=container,
        )
        result = import_epub_book(raw, source_name="multi-rendition.epub")
        self.assertEqual(result.spine_documents, 1)
        self.assertEqual(
            [
                block.text
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ],
            ["Primary rendition."],
        )
        self.assertTrue(
            any(
                "multiple EPUB package documents" in warning
                for warning in result.warnings
            )
        )

    def test_secondary_rootfile_must_be_a_valid_package_document(self) -> None:
        container = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    <rootfile full-path="ALT/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''
        raw = _epub(
            opf=_opf(
                manifest='    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/chapter.xhtml": (
                    b"<html><body><p>Primary rendition.</p></body></html>"
                ),
                "ALT/content.opf": b"<package/>",
            },
            container=container,
        )

        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="malformed-secondary-rendition.epub")

        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_all_rootfiles_must_use_the_same_epub_package_version(self) -> None:
        container = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    <rootfile full-path="ALT/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''
        alternate_opf = _opf(
            manifest=(
                '    <item id="alt" href="chapter.xhtml" '
                'media-type="application/xhtml+xml"/>'
            ),
            spine='    <itemref idref="alt"/>',
        ).replace(
            b'<package version="3.0"',
            b'<package version="2.0"',
            1,
        )
        raw = _epub(
            opf=_opf(
                manifest='    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/chapter.xhtml": (
                    b"<html><body><p>Primary rendition.</p></body></html>"
                ),
                "ALT/content.opf": alternate_opf,
                "ALT/chapter.xhtml": (
                    b"<html><body><p>Alternate rendition.</p></body></html>"
                ),
            },
            container=container,
        )

        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="mixed-rendition-version.epub")

        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_secondary_rootfile_manifest_resources_are_validated(self) -> None:
        container = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    <rootfile full-path="ALT/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''
        alternate_opf = _opf(
            manifest=(
                '    <item id="alt" href="missing.xhtml" '
                'media-type="application/xhtml+xml"/>'
            ),
            spine='    <itemref idref="alt"/>',
        )
        raw = _epub(
            opf=_opf(
                manifest='    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/chapter.xhtml": (
                    b"<html><body><p>Primary rendition.</p></body></html>"
                ),
                "ALT/content.opf": alternate_opf,
            },
            container=container,
        )

        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="secondary-missing-resource.epub")

        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_secondary_rootfile_spine_references_are_validated(self) -> None:
        container = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    <rootfile full-path="ALT/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''
        alternate_opf = _opf(
            manifest=(
                '    <item id="alt" href="chapter.xhtml" '
                'media-type="application/xhtml+xml"/>'
            ),
            spine='    <itemref idref="unknown"/>',
        )
        raw = _epub(
            opf=_opf(
                manifest='    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/chapter.xhtml": (
                    b"<html><body><p>Primary rendition.</p></body></html>"
                ),
                "ALT/content.opf": alternate_opf,
                "ALT/chapter.xhtml": (
                    b"<html><body><p>Alternate rendition.</p></body></html>"
                ),
            },
            container=container,
        )

        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="secondary-unknown-spine.epub")

        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_every_container_rootfile_path_is_validated_before_selection(self) -> None:
        cases = (
            (
                " ALT/content.opf ",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            ),
            (
                "../ALT/content.opf",
                BookEpubImportErrorCode.UNSAFE_PACKAGE,
            ),
            (
                "ALT/missing.opf",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            ),
        )
        for secondary_path, expected_code in cases:
            with self.subTest(secondary_path=secondary_path):
                container = f'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    <rootfile full-path="{secondary_path}" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''.encode("utf-8")
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            '    <item id="c1" href="chapter.xhtml" '
                            'media-type="application/xhtml+xml"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={
                        "OEBPS/chapter.xhtml": (
                            b"<html><body><p>Primary rendition.</p></body></html>"
                        ),
                    },
                    container=container,
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="invalid-secondary-rootfile.epub")
                self.assertEqual(raised.exception.code, expected_code)

    def test_container_rootfiles_cannot_alias_the_same_package_document(self) -> None:
        for secondary_path in ("OEBPS/content.opf", "OEBPS/%63ontent.opf"):
            with self.subTest(secondary_path=secondary_path):
                container = f'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    <rootfile full-path="{secondary_path}" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''.encode("utf-8")
                raw = _epub(
                    opf=_opf(
                        manifest=(
                            '    <item id="c1" href="chapter.xhtml" '
                            'media-type="application/xhtml+xml"/>'
                        ),
                        spine='    <itemref idref="c1"/>',
                    ),
                    entries={
                        "OEBPS/chapter.xhtml": (
                            b"<html><body><p>Primary rendition.</p></body></html>"
                        ),
                    },
                    container=container,
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(raw, source_name="aliased-rootfiles.epub")
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )

    def test_in_document_asset_fragment_remains_resolvable(self) -> None:
        chapter = (
            b'<html><body><img src="../Images/board.svg#diagram" '
            b'alt="Board diagram"/></body></html>'
        )
        raw = _epub(
            opf=_opf(
                manifest='''    <item id="c1" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>
    <item id="board" href="Images/board.svg" media-type="image/svg+xml"/>''',
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/Text/chapter.xhtml": chapter,
                "OEBPS/Images/board.svg": b"<svg/>",
            },
        )

        result = import_epub_book(raw, source_name="asset-fragment.epub")
        self.assertEqual(
            result.image_references,
            ("OEBPS/Images/board.svg",),
        )

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

    def test_utf16_opf_doctype_entity_is_rejected_structurally(self) -> None:
        dangerous = """<?xml version="1.0" encoding="UTF-16"?>
<!DOCTYPE package [<!ENTITY injected "Injected title">]>
<package version="3.0"
 xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
  <metadata><dc:title>&injected;</dc:title></metadata>
  <manifest>
    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>""".encode("utf-16")
        raw = _epub(
            opf=dangerous,
            entries={
                "OEBPS/chapter.xhtml": b"<html><body><p>Readable.</p></body></html>",
            },
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="utf16-doctype-opf.epub")
        self.assertEqual(raised.exception.code, BookEpubImportErrorCode.UNSAFE_PACKAGE)

    def test_utf16_endian_opf_doctype_entity_is_rejected_structurally(self) -> None:
        template = """<?xml version="1.0" encoding="{declaration}"?>
<!DOCTYPE package [<!ENTITY injected "Injected title">]>
<package version="3.0"
 xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
  <metadata><dc:title>&injected;</dc:title></metadata>
  <manifest>
    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>"""
        for encoding, declaration in (
            ("utf-16-le", "UTF-16LE"),
            ("utf-16-be", "UTF-16BE"),
        ):
            with self.subTest(encoding=encoding):
                raw = _epub(
                    opf=template.format(declaration=declaration).encode(encoding),
                    entries={
                        "OEBPS/chapter.xhtml": (
                            b"<html><body><p>Readable.</p></body></html>"
                        ),
                    },
                )
                with self.assertRaises(BookEpubImportError) as raised:
                    import_epub_book(
                        raw,
                        source_name=f"{encoding}-doctype-opf.epub",
                    )
                self.assertEqual(
                    raised.exception.code,
                    BookEpubImportErrorCode.UNSAFE_PACKAGE,
                )

    def test_utf16_container_doctype_entity_is_rejected_structurally(self) -> None:
        dangerous_container = """<?xml version="1.0" encoding="UTF-16"?>
<!DOCTYPE container [<!ENTITY packagePath "OEBPS/content.opf">]>
<container version="1.0"
 xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="&packagePath;"
      media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""".encode("utf-16")
        raw = _epub(
            opf=_opf(
                manifest='    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
                spine='    <itemref idref="c1"/>',
            ),
            entries={
                "OEBPS/chapter.xhtml": b"<html><body><p>Readable.</p></body></html>",
            },
            container=dangerous_container,
        )
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(raw, source_name="utf16-doctype-container.epub")
        self.assertEqual(raised.exception.code, BookEpubImportErrorCode.UNSAFE_PACKAGE)

    def test_utf16_opf_without_dtd_remains_supported(self) -> None:
        opf_text = _opf(
            manifest='    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
            spine='    <itemref idref="c1"/>',
        ).decode("utf-8")
        opf_utf16 = opf_text.replace(
            'encoding="UTF-8"',
            'encoding="UTF-16"',
            1,
        ).encode("utf-16")
        raw = _epub(
            opf=opf_utf16,
            entries={
                "OEBPS/chapter.xhtml": b"<html><body><p>UTF-16 metadata, safe content.</p></body></html>",
            },
        )
        result = import_epub_book(raw, source_name="utf16-safe-opf.epub")
        self.assertEqual(result.spine_documents, 1)
        self.assertIn(
            "UTF-16 metadata, safe content.",
            [block.text for block in result.document.blocks if isinstance(block, Paragraph)],
        )

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
        self.assertIn(
            "Media Overlay playback/synchronization",
            SUPPORTED_EPUB_BOOK_CAPABILITY["does_not_claim"],
        )
        self.assertIn(
            "NCX navigation rendering",
            SUPPORTED_EPUB_BOOK_CAPABILITY["does_not_claim"],
        )
        self.assertIn("ordered/unordered lists", SUPPORTED_EPUB_BOOK_CAPABILITY["preserves"])


if __name__ == "__main__":
    unittest.main()
