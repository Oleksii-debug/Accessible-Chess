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
  <links/>
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
        raw = _epub(
            opf=_opf(
                manifest='    <item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
                spine='    <itemref idref="c1"/>',
            ),
            entries={"OEBPS/chapter.xhtml": b"<html><body><p>Primary rendition.</p></body></html>"},
            container=container,
        )
        result = import_epub_book(raw, source_name="multi-rendition.epub")
        self.assertEqual(result.spine_documents, 1)
        self.assertIn("Primary rendition.", [block.text for block in result.document.blocks if isinstance(block, Paragraph)])
        self.assertTrue(any("multiple EPUB package documents" in warning for warning in result.warnings))

    def test_in_document_asset_fragment_remains_resolvable(self) -> None:
        chapter = (
            b'<html><body><img src="../Images/board.svg#diagram" '
            b'alt="Board diagram"/></body></html>'
        )
        raw = _epub(
            opf=_opf(
                manifest='    <item id="c1" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>',
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
        self.assertIn("ordered/unordered lists", SUPPORTED_EPUB_BOOK_CAPABILITY["preserves"])


if __name__ == "__main__":
    unittest.main()
