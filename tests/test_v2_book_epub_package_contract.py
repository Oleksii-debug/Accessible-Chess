from __future__ import annotations

from io import BytesIO
import unittest
import zipfile

from acs.book_epub_import import (
    BookEpubImportError,
    BookEpubImportErrorCode,
    import_epub_book,
)
from acs.bookdocument import Paragraph


CONTAINER = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''


def _epub(opf: bytes, *, container: bytes = CONTAINER) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_STORED
        archive.writestr(mimetype, b"application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            container,
            compress_type=zipfile.ZIP_DEFLATED,
        )
        archive.writestr(
            "OEBPS/content.opf",
            opf,
            compress_type=zipfile.ZIP_DEFLATED,
        )
        archive.writestr(
            "OEBPS/Text/chapter.xhtml",
            b"<html><body><p>Readable package.</p></body></html>",
            compress_type=zipfile.ZIP_DEFLATED,
        )
    return buffer.getvalue()


def _opf(*, version: str = "3.0", unique_identifier: str | None = "bookid") -> bytes:
    unique = (
        ""
        if unique_identifier is None
        else f' unique-identifier="{unique_identifier}"'
    )
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<package version="{version}"{unique}
 xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
  <metadata>
    <dc:identifier id="bookid">urn:uuid:test-book</dc:identifier>
    <dc:title>Package contract</dc:title>
    <dc:language>uk</dc:language>
  </metadata>
  <manifest>
    <item id="chapter" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter"/>
  </spine>
</package>'''.encode("utf-8")


class EpubPackageDocumentContractTests(unittest.TestCase):
    def assert_malformed(self, opf: bytes, *, container: bytes = CONTAINER) -> None:
        with self.assertRaises(BookEpubImportError) as raised:
            import_epub_book(
                _epub(opf, container=container),
                source_name="package-contract.epub",
            )
        self.assertEqual(
            raised.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_epub_2_and_3_package_versions_remain_supported(self) -> None:
        for version in ("2.0", "3.0"):
            with self.subTest(version=version):
                result = import_epub_book(
                    _epub(_opf(version=version)),
                    source_name=f"epub-{version}.epub",
                )
                self.assertEqual(result.spine_documents, 1)
                self.assertEqual(
                    [
                        block.text
                        for block in result.document.blocks
                        if isinstance(block, Paragraph)
                    ],
                    ["Readable package."],
                )

    def test_package_requires_canonical_opf_root_namespace(self) -> None:
        valid = _opf().decode("utf-8")
        cases = (
            valid.replace("<package ", "<publication ", 1).replace(
                "</package>", "</publication>", 1
            ),
            valid.replace(
                'xmlns="http://www.idpf.org/2007/opf"',
                'xmlns="urn:example:not-opf"',
                1,
            ),
        )
        for text in cases:
            with self.subTest(opf=text[:100]):
                self.assert_malformed(text.encode("utf-8"))

    def test_package_version_is_exact_epub_2_or_3_marker(self) -> None:
        for version in ("", " 3.0 ", "3.3", "4.0"):
            with self.subTest(version=version):
                self.assert_malformed(_opf(version=version))

    def test_package_unique_identifier_attribute_is_required_and_not_repaired(self) -> None:
        self.assert_malformed(_opf(unique_identifier=None))
        for unique_identifier in ("", " bookid", "bookid ", "book id"):
            with self.subTest(unique_identifier=unique_identifier):
                self.assert_malformed(_opf(unique_identifier=unique_identifier))

    def test_foreign_namespace_sections_cannot_masquerade_as_opf_structure(self) -> None:
        opf = b'''<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="bookid"
 xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:x="urn:example:foreign">
  <metadata><dc:identifier id="bookid">id</dc:identifier><dc:title>Foreign</dc:title></metadata>
  <x:manifest>
    <x:item id="chapter" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>
  </x:manifest>
  <x:spine><x:itemref idref="chapter"/></x:spine>
</package>'''
        self.assert_malformed(opf)

    def test_foreign_item_and_itemref_cannot_masquerade_inside_opf_sections(self) -> None:
        foreign_item = b'''<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="bookid"
 xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:x="urn:example:foreign">
  <metadata><dc:identifier id="bookid">id</dc:identifier><dc:title>Foreign item</dc:title></metadata>
  <manifest><x:item id="chapter" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/></manifest>
  <spine><itemref idref="chapter"/></spine>
</package>'''
        foreign_itemref = b'''<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="bookid"
 xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:x="urn:example:foreign">
  <metadata><dc:identifier id="bookid">id</dc:identifier><dc:title>Foreign itemref</dc:title></metadata>
  <manifest><item id="chapter" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/></manifest>
  <spine><x:itemref idref="chapter"/></spine>
</package>'''
        self.assert_malformed(foreign_item)
        self.assert_malformed(foreign_itemref)

    def test_required_opf_sections_keep_metadata_manifest_spine_order(self) -> None:
        opf = b'''<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="bookid"
 xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
  <metadata><dc:identifier id="bookid">id</dc:identifier><dc:title>Wrong order</dc:title></metadata>
  <spine><itemref idref="chapter"/></spine>
  <manifest><item id="chapter" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/></manifest>
</package>'''
        self.assert_malformed(opf)


    def test_malformed_url_authority_is_reported_as_stable_package_error(self) -> None:
        opf = _opf().replace(b"Text/chapter.xhtml", b"//[bad")
        self.assert_malformed(opf)

        container = CONTAINER.replace(b"OEBPS/content.opf", b"//[bad")
        self.assert_malformed(_opf(), container=container)


if __name__ == "__main__":
    unittest.main()
