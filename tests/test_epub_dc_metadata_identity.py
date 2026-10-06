from __future__ import annotations

from io import BytesIO
import unittest
import zipfile

from acs.book_epub_import import (
    BookEpubImportError,
    BookEpubImportErrorCode,
    import_epub_book,
)


_CONTAINER = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''

_CHAPTER = b'''<html><head><title>Chapter title</title></head><body>
<h1>Chapter fallback</h1><p>Readable content.</p>
</body></html>'''


def _package(
    metadata: str,
    *,
    unique_identifier: str = "bookid",
    trailing_package_content: str = "",
) -> bytes:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="{unique_identifier}"
 xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:x="urn:example:foreign-metadata">
  <metadata>
{metadata}
  </metadata>
  <manifest>
    <item id="chapter" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="chapter"/></spine>
{trailing_package_content}
</package>'''.encode("utf-8")


def _epub(package: bytes) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_STORED
        archive.writestr(mimetype, b"application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            _CONTAINER,
            compress_type=zipfile.ZIP_DEFLATED,
        )
        archive.writestr(
            "OEBPS/content.opf",
            package,
            compress_type=zipfile.ZIP_DEFLATED,
        )
        archive.writestr(
            "OEBPS/Text/chapter.xhtml",
            _CHAPTER,
            compress_type=zipfile.ZIP_DEFLATED,
        )
    return output.getvalue()


class EpubDublinCoreMetadataIdentityTests(unittest.TestCase):
    def test_foreign_namespace_metadata_cannot_spoof_dublin_core_values(self) -> None:
        metadata = '''
    <dc:identifier id="bookid">urn:uuid:real</dc:identifier>
    <x:title>Foreign title</x:title>
    <x:creator>Foreign creator</x:creator>
    <x:language>zz</x:language>
    <x:rights>Foreign rights</x:rights>
    <dc:title>Canonical title</dc:title>
    <dc:creator>Canonical creator</dc:creator>
    <dc:language>uk</dc:language>
    <dc:rights>Canonical rights</dc:rights>'''

        result = import_epub_book(
            _epub(_package(metadata)),
            source_name="metadata.epub",
        )

        self.assertEqual(result.document.title, "Canonical title")
        self.assertEqual(result.document.author, "Canonical creator")
        self.assertEqual(result.document.language, "uk")
        self.assertEqual(result.document.source_rights, "Canonical rights")

    def test_nested_dublin_core_elements_are_not_promoted_to_package_metadata(self) -> None:
        metadata = '''
    <dc:identifier id="bookid">urn:uuid:real</dc:identifier>
    <dc:title>Canonical title</dc:title>
    <dc:language>uk</dc:language>
    <x:wrapper>
      <dc:title>Nested title</dc:title>
      <dc:creator>Nested creator</dc:creator>
      <dc:language>zz</dc:language>
      <dc:rights>Nested rights</dc:rights>
    </x:wrapper>'''

        result = import_epub_book(
            _epub(_package(metadata)),
            source_name="nested-metadata.epub",
        )

        self.assertEqual(result.document.title, "Canonical title")
        self.assertIsNone(result.document.author)
        self.assertEqual(result.document.language, "uk")
        self.assertIsNone(result.document.source_rights)

    def test_nested_title_and_language_cannot_satisfy_required_package_metadata(self) -> None:
        metadata = '''
    <dc:identifier id="bookid">urn:uuid:real</dc:identifier>
    <x:wrapper><dc:title>Nested title</dc:title><dc:language>uk</dc:language></x:wrapper>'''
        with self.assertRaises(BookEpubImportError) as caught:
            import_epub_book(_epub(_package(metadata)), source_name='nested-required-metadata.epub')
        self.assertEqual(BookEpubImportErrorCode.MALFORMED_PACKAGE, caught.exception.code)

    def test_unique_identifier_must_bind_one_direct_dc_identifier(self) -> None:
        invalid_metadata = (
            '<dc:title>No identifier</dc:title>',
            '<x:identifier id="bookid">urn:foreign</x:identifier>',
            '<dc:identifier id="bookid"></dc:identifier>',
            (
                '<dc:identifier id="bookid">urn:first</dc:identifier>'
                '<dc:identifier id="bookid">urn:second</dc:identifier>'
            ),
            (
                '<x:wrapper><dc:identifier id="bookid">urn:nested</dc:identifier>'
                '</x:wrapper>'
            ),
        )
        for metadata in invalid_metadata:
            with self.subTest(metadata=metadata):
                with self.assertRaises(BookEpubImportError) as caught:
                    import_epub_book(
                        _epub(_package(metadata)),
                        source_name="bad-identity.epub",
                    )
                self.assertEqual(
                    caught.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )


    def test_epub_defined_ids_are_unique_across_package_document_scope(self) -> None:
        invalid_packages = (
            _package(
                '<dc:identifier id="bookid">urn:uuid:real</dc:identifier>'
                '<dc:title id="bookid">Conflicting title</dc:title>'
            ),
            _package(
                '<dc:identifier id="bookid">urn:uuid:real</dc:identifier>'
                '<dc:title id="chapter">Conflicts with manifest item</dc:title>'
            ),
        )
        for package in invalid_packages:
            with self.subTest(package=package):
                with self.assertRaises(BookEpubImportError) as caught:
                    import_epub_book(
                        _epub(package),
                        source_name="duplicate-document-id.epub",
                    )
                self.assertEqual(
                    caught.exception.code,
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )


    def test_collection_metadata_dublin_core_id_shares_document_scope(self) -> None:
        package = _package(
            '''
    <dc:identifier id="bookid">urn:uuid:real</dc:identifier>
    <dc:title>Canonical title</dc:title>''',
            trailing_package_content='''
  <collection role="index" id="collection-root">
    <metadata>
      <dc:title id="bookid">Conflicting collection title</dc:title>
    </metadata>
    <link href="Text/chapter.xhtml"/>
  </collection>''',
        )

        with self.assertRaises(BookEpubImportError) as caught:
            import_epub_book(
                _epub(package),
                source_name="collection-metadata-duplicate-id.epub",
            )

        self.assertEqual(
            caught.exception.code,
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    def test_foreign_extension_id_does_not_claim_epub_id_space(self) -> None:
        metadata = '''
    <dc:identifier id="bookid">urn:uuid:real</dc:identifier>
    <x:title id="bookid">Foreign extension title</x:title>
    <dc:title>Canonical title</dc:title>
    <dc:language>uk</dc:language>'''

        result = import_epub_book(
            _epub(_package(metadata)),
            source_name="foreign-extension-id.epub",
        )

        self.assertEqual(result.document.title, "Canonical title")

    def test_matching_unicode_dc_identifier_remains_supported(self) -> None:
        metadata = '''
    <dc:identifier id="книга">urn:example:книга</dc:identifier>
    <dc:title>Українська книга</dc:title>
    <dc:language>uk</dc:language>'''

        result = import_epub_book(
            _epub(_package(metadata, unique_identifier="книга")),
            source_name="unicode-identity.epub",
        )

        self.assertEqual(result.document.title, "Українська книга")
        self.assertEqual(result.document.language, "uk")


if __name__ == "__main__":
    unittest.main()
