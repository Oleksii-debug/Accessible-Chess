from __future__ import annotations

from io import BytesIO
import unittest
import zipfile

import acs.book_epub_import as epub


_CONTAINER = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''

_OPF = b'''<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="bookid"
 xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
  <metadata>
    <dc:identifier id="bookid">urn:uuid:runtime-fixture</dc:identifier>
    <dc:title>Runtime Fixture</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
  </spine>
</package>'''


def _simple_epub(chapter: bytes) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
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
            _OPF,
            compress_type=zipfile.ZIP_DEFLATED,
        )
        archive.writestr(
            "OEBPS/Text/ch1.xhtml",
            chapter,
            compress_type=zipfile.ZIP_DEFLATED,
        )
    return buffer.getvalue()


class BookEpubRuntimeCorrectnessTests(unittest.TestCase):
    def test_malformed_urlsplit_image_reference_is_unresolved_not_exception(self):
        self.assertIsNone(
            epub._resolved_asset(
                "OEBPS/Text/chapter.xhtml",
                "http://[",
            )
        )

    def test_malformed_image_reference_does_not_abort_epub_reading_flow(self):
        raw = _simple_epub(
            b'<html><body><p>Readable chapter</p>'
            b'<img src="http://[" alt="Broken external image">'
            b'</body></html>'
        )

        imported = epub.import_epub_book(
            raw,
            source_name="malformed-image.epub",
        )

        readable = "\n".join(
            getattr(block, "text", "")
            for block in imported.document.blocks
        )
        self.assertIn("Readable chapter", readable)
        self.assertTrue(
            any(
                "external or unsafe image reference was not resolved" in warning
                for warning in imported.warnings
            )
        )


if __name__ == "__main__":
    unittest.main()
