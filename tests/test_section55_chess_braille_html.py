from __future__ import annotations

"""Only offline semantic HTML/PEF boundary tests; not Braille certification."""
from dataclasses import replace
from hashlib import sha256
from html.parser import HTMLParser
import unittest

from acs.bookdocument import BookDocument, Diagram, Heading, Paragraph
from acs.chess_braille_factory import (
    BrailleFactoryError, BrailleProfile, prepare_chess_book_pef,
)
from acs.chess_braille_html import render_local_braille_html


class FakeSixDot:
    table_id = "synthetic"
    table_version = "1"
    table_sha256 = "a" * 64

    def translate(self, source: str) -> str:
        return "".join("\u2800" if c == " " else "\u2801" for c in source)


class InspectHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []
        self.csp = False
        self.scripts = 0

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if "id" in props:
            self.ids.add(props["id"])
        if tag == "a" and "href" in props:
            self.links.append(props["href"])
        if tag == "script":
            self.scripts += 1
        if tag == "meta" and props.get("http-equiv") == "Content-Security-Policy":
            self.csp = True


def source() -> BookDocument:
    return BookDocument(
        title="Chess & <script>alert(1)</script>",
        blocks=[
            Heading(text="Opening & <img src=x onerror=alert(1)>"),
            Paragraph(text="Read this <strong>without injection</strong>."),
            Diagram(
                fen="4k3/8/8/8/8/8/8/4K3 w - - 0 1",
                caption="Two kings",
                alt_text="White king on e1, black king on e8",
            ),
        ],
    )


def make() -> tuple[BookDocument, object]:
    document = source()
    prepared = prepare_chess_book_pef(
        document,
        BrailleProfile(
            language="en", table_id="synthetic", table_version="1",
            table_sha256="a" * 64, device_model="synthetic-test",
            cells_per_line=40, lines_per_page=10,
        ),
        FakeSixDot(), rights_confirmed=True, rights_basis="Author-owned test fixture",
    )
    return document, prepared


class Section55HTMLTests(unittest.TestCase):
    def test_offline_braille_preview_has_readable_source_and_page_anchors(self):
        book, pef = make()
        a = render_local_braille_html(book, pef)
        b = render_local_braille_html(book, pef)
        self.assertEqual(a, b)
        self.assertEqual(a.sha256, sha256(a.data).hexdigest())
        self.assertEqual(a.pages, pef.manifest["pages"])
        self.assertIs(a.print_ready, False)
        markup = a.data.decode("utf-8")
        checker = InspectHTML()
        checker.feed(markup)
        self.assertTrue(checker.csp)
        self.assertEqual(checker.scripts, 0)
        self.assertIn("source-book", checker.ids)
        self.assertIn("braille-pages", checker.ids)
        self.assertIn("braille-page-1", checker.ids)
        self.assertIn("#source-book", checker.links)
        self.assertIn("#braille-page-1", checker.links)
        self.assertIn("White king on e1", markup)
        self.assertIn("Canonical FEN", markup)
        self.assertIn("UNVERIFIED PREVIEW", markup)
        self.assertNotIn("<script>", markup)
        self.assertNotIn("<img src=x", markup)
        self.assertIn("&lt;script&gt;", markup)
        self.assertIn("&lt;strong&gt;", markup)
        self.assertTrue(all(href.startswith("#") for href in checker.links))

    def test_changed_book_is_not_attached_to_unrelated_pef(self):
        original, pef = make()
        mismatched = BookDocument(title="Changed", blocks=[Paragraph(text="Unknown")])
        with self.assertRaises(BrailleFactoryError):
            render_local_braille_html(mismatched, pef)

    def test_changed_pef_sha_is_rejected(self):
        original, pef = make()
        with self.assertRaises(BrailleFactoryError):
            render_local_braille_html(
                original, replace(pef, pef=pef.pef + b"UNSAFE"),
            )

    def test_fake_print_readiness_in_manifest_is_rejected(self):
        original, pef = make()
        with self.assertRaises(BrailleFactoryError):
            render_local_braille_html(
                original, replace(pef, manifest={**pef.manifest, "print_ready": True}),
            )


if __name__ == "__main__":
    unittest.main()
