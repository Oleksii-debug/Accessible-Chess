from __future__ import annotations

import unittest

import acs.book_epub_import as epub
from test_v2_book_epub_import import _simple_epub


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
