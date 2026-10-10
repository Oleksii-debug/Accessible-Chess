"""Original Gutenberg EPUB3 and HTML original test-only acquisition safeguards."""
from __future__ import annotations

from io import BytesIO
import unittest
from unittest.mock import patch
import zipfile

from acs.lawful_corpus_registry import LawfulCorpusError
from tools import section39_real_official_gutenberg_epub_html as real


class OfficialGutenbergNonfictionImportTests(unittest.TestCase):
    def test_only_real_first_party_original_source_endpoints(self):
        self.assertEqual(len(real.ORIGINALS), 2)
        self.assertEqual({x[1] for x in real.ORIGINALS}, {"EPUB", "HTML"})
        for row in real.ORIGINALS:
            self.assertEqual(real.validate_official_url(row[2]), row[2])
        for url in (
            "http://www.gutenberg.org/cache/epub/5614/pg5614-h.zip",
            "https://gutenberg.org/cache/epub/5614/pg5614-h.zip",
            "https://www.gutenberg.org.evil.example/cache/epub/5614/a.zip",
            "https://user@www.gutenberg.org/cache/epub/5614/a.zip",
            "https://www.gutenberg.org:8443/cache/epub/5614/a.zip",
            "https://www.gutenberg.org/ebooks/../../local",
            "https://www.gutenberg.org/ebooks/33870.epub3.images?source=tracking",
        ):
            with self.subTest(url=url):
                with self.assertRaises(LawfulCorpusError):
                    real.validate_official_url(url)

    def test_cross_origin_redirect_denied(self):
        handler = real._FirstPartyOnlyRedirect()
        with self.assertRaisesRegex(LawfulCorpusError, "outside approved"):
            handler.redirect_request(
                object(), None, 302, "redirect", {},
                "https://malicious.example/private-document",
            )

    def test_untrusted_original_html_archive_member_rejected(self):
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("../private.html", "<html><p>forbidden</p></html>")
        with self.assertRaisesRegex(LawfulCorpusError, "unsafe member"):
            real._html_from_original_zip(output.getvalue())

    def test_safe_original_html_archive_directory_does_not_become_traversal(self):
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("images/", b"")
            archive.writestr("book/index.html", "<html><body>"
                             + "<p>Historical chess narrative for testing.</p>" * 20
                             + "</body></html>")
        extracted, path = real._html_from_original_zip(output.getvalue())
        self.assertEqual(path, "book/index.html")
        self.assertIn(b"Historical chess narrative", extracted)

    def test_unauthorized_source_catalog_cannot_be_treated_as_real_book(self):
        untrusted = real.load_catalog
        def wrong():
            sources = untrusted()
            return tuple(
                {**r, "redistribution": "permitted"} if r["id"] == real.ORIGINALS[0][0] else r
                for r in sources
            )
        with patch.object(real, "load_catalog", side_effect=wrong):
            with patch.object(real, "get_original_bytes") as acquisition:
                with self.assertRaisesRegex(LawfulCorpusError, "test-only"):
                    real.qualify_original_ebooks()
                acquisition.assert_not_called()


if __name__ == "__main__":
    unittest.main()
