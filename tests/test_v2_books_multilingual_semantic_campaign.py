from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from acs.book_epub_import import import_epub_book
from acs.book_html_import import import_html_book
from acs.book_index import BookIndex
from acs.book_progress_store import BookProgressStore
from acs.book_text_import import import_text_book
from acs.bookdocument import BookDocument, Diagram, Game, Note, Position
from acs.bookreader import BookReader


TXT_SOURCE = (
    "Українська стратегія: Кінь на f3 контролює центр.\n"
    "Polski komentarz: Łódź, żółć i skoczek pozostają tekstem.\n"
    "English note: Strategy remains readable Unicode text.\n\n"
    "ASCII diagram (ordinary prose, not a semantic diagram):\n"
    "8 | . . . . k . . . |\n"
    "7 | . . . . . . . . |\n"
    "6 | . . . . . . . . |\n"
    "5 | . . . . . . . . |\n"
    "4 | . . . . . . . . |\n"
    "3 | . . . . . . . . |\n"
    "2 | . . . . . . . . |\n"
    "1 | . . . . K . . . |\n"
    "  +-----------------+\n"
    "    a b c d e f g h\n\n"
    "FEN-like prose: rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1.\n"
    "Move-like prose: 1. e4 e5 2. Nf3 Nc6 *.\n"
)
TXT_SHA256 = "0397bdfb41aa80083fa132b216c0c18abc83eaed8f1d25afbde4067f8f850c59"

MARKDOWN_SOURCE = (
    "# Український розділ\n\n"
    "Кінь і пішак — звичайний Unicode текст.\n\n"
    "## Polski rozdział\n\n"
    "- Łódź i skoczek\n"
    "- Żółć oraz końcówka\n\n"
    "## English section\n\n"
    "1. Strategy first\n"
    "2. Tactics second\n\n"
    "![Дошка — szachownica — board](images/board.png)\n\n"
    "```text\n"
    "[Event \"Quoted example, not semantic PGN\"]\n"
    "[Site \"Ordinary prose\"]\n"
    "[Date \"2026.09.10\"]\n"
    "[Round \"1\"]\n"
    "[White \"Text\"]\n"
    "[Black \"Text\"]\n"
    "[Result \"*\"]\n\n"
    "1. e4 e5 2. Nf3 Nc6 *\n"
    "```\n\n"
    "ASCII diagram: 8/8/8/8/8/8/8/8 is descriptive text only.\n"
)
MARKDOWN_SHA256 = "1d65d7db20c4b81861ace76c6d8c15a69ab2ecbf34aec1d04ef79d0b2c0964b6"

HTML_SOURCE = """<!doctype html>
<html lang="uk">
<head><title>Багатомовна книга</title><meta name="author" content="Accessible Chess QA"></head>
<body>
<h1 id="ua">Український розділ</h1>
<p>Кінь на f3 — Unicode; польське Łódź; English strategy.</p>
<h2 id="pl">Polski rozdział</h2>
<ul id="pl-list"><li>Żółć i skoczek</li><li>Końcówka bez zgadywania</li></ul>
<h2 id="en">English section</h2>
<ol start="3"><li>Strategy</li><li>Tactics</li></ol>
<img id="img" src="images/board.png" alt="Дошка — szachownica — board">
<p>FEN-like prose: rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1 is text only.</p>
<p>ASCII diagram below is ordinary reading material, not a semantic diagram.</p>
<pre>
8 | . . . . k . . . |
7 | . . . . . . . . |
6 | . . . . . . . . |
5 | . . . . . . . . |
4 | . . . . . . . . |
3 | . . . . . . . . |
2 | . . . . . . . . |
1 | . . . . K . . . |
  +-----------------+
    a b c d e f g h
</pre>
<p>The following valid PGN is quoted as ordinary prose and has no explicit HTML chess marker.</p>
<pre class="quoted-prose">
[Event "Quoted example, not semantic PGN"]
[Site "Ordinary prose"]
[Date "2026.09.10"]
[Round "1"]
[White "Text"]
[Black "Text"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 *
</pre>
</body></html>"""
HTML_SHA256 = "9fde4eb9ca96183790ce4ad3e46d371cbe1db22b76fb4e01e5b1e75b6350040b"

EPUB_SHA256 = "3b3a1b6befc680b85aea44c672939e3b73178b1cb31cad5f3055bf8c3ed17fcc"


def _zip_entry(name: str, data: str | bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    return info, raw


def _epub_source() -> bytes:
    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    opf = """<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">urn:accessible-chess:multilingual-campaign:v1</dc:identifier>
    <dc:title>Багатомовна книга EPUB</dc:title>
    <dc:creator>Accessible Chess QA</dc:creator>
    <dc:language>uk</dc:language>
    <dc:rights>Deterministic project QA fixture; no third-party corpus bytes.</dc:rights>
  </metadata>
  <manifest>
    <item id="ch1" href="chapter.xhtml" media-type="application/xhtml+xml"/>
    <item id="img" href="images/board.png" media-type="image/png"/>
  </manifest>
  <spine><itemref idref="ch1"/></spine>
</package>
"""
    chapter = HTML_SOURCE.replace(
        "<!doctype html>",
        '<?xml version="1.0" encoding="UTF-8"?>',
        1,
    ).replace(
        '<html lang="uk">',
        '<html xmlns="http://www.w3.org/1999/xhtml" lang="uk">',
        1,
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in (
            ("mimetype", b"application/epub+zip"),
            ("META-INF/container.xml", container_xml),
            ("OEBPS/content.opf", opf),
            ("OEBPS/chapter.xhtml", chapter),
            ("OEBPS/images/board.png", b"not-an-image-decoder-fixture"),
        ):
            info, raw = _zip_entry(name, data)
            archive.writestr(info, raw)
    return buffer.getvalue()


def _block_wire(document: BookDocument) -> list[dict[str, object]]:
    return [block.as_dict() for block in document.blocks]


class MultilingualSemanticReadingCampaign(unittest.TestCase):
    maxDiff = None

    def _assert_common_reading_identity(self, first, second) -> None:
        self.assertEqual(first.source_sha256, second.source_sha256)
        self.assertEqual(first.book_key, second.book_key)
        self.assertEqual(_block_wire(first.document), _block_wire(second.document))
        self.assertTrue(first.document.blocks)
        self.assertTrue(all(block.block_id for block in first.document.blocks))

        wire = first.document.as_dict()
        encoded = json.dumps(wire, ensure_ascii=False, sort_keys=True)
        restored = BookDocument.from_dict(json.loads(encoded))
        self.assertEqual(restored.as_dict(), wire)

        index = BookIndex(first.document)
        for query in ("КІНЬ", "ŁÓDŹ", "STRATEGY"):
            self.assertTrue(index.find(query), query)

        origin_entry = index.find("ŁÓDŹ")[0]
        reader = BookReader(first.document)
        origin = reader.go_to(origin_entry.target.index)
        reader.save_return_point("multilingual-origin")
        if origin.index + 1 < len(first.document.blocks):
            reader.next_block()
        elif origin.index:
            reader.previous_block()
        self.assertEqual(reader.restore_return_point("multilingual-origin"), origin)

        with tempfile.TemporaryDirectory() as directory:
            store = BookProgressStore(Path(directory) / "progress.json")
            store.save(first.book_key, reader)
            reopened = store.restore(second.book_key, second.document)
            self.assertEqual(reopened.location(), origin)
            self.assertEqual(
                reopened.restore_return_point("multilingual-origin"),
                origin,
            )

    def _assert_no_fabricated_chess(self, document: BookDocument, *, pgn_games: int) -> None:
        self.assertEqual(
            pgn_games,
            0,
            "ordinary prose without a format-specific chess marker must not become Game",
        )
        self.assertFalse(
            any(isinstance(block, (Game, Position, Diagram)) for block in document.blocks),
            "ordinary prose, FEN-like text, and ASCII diagrams must remain reading content",
        )

    def test_txt_unicode_identity_progress_and_no_chess_inference(self) -> None:
        self.assertEqual(sha256(TXT_SOURCE.encode("utf-8")).hexdigest(), TXT_SHA256)
        first = import_text_book(
            TXT_SOURCE,
            source_name="multilingual.txt",
            source_format="txt",
            title="Багатомовний TXT",
            language="uk",
        )
        second = import_text_book(
            TXT_SOURCE,
            source_name="multilingual.txt",
            source_format="txt",
            title="Багатомовний TXT",
            language="uk",
        )
        self.assertEqual(first.source_sha256, TXT_SHA256)
        self._assert_common_reading_identity(first, second)
        self._assert_no_fabricated_chess(first.document, pgn_games=first.pgn_games)

    def test_markdown_semantics_identity_progress_and_no_unmarked_chess(self) -> None:
        self.assertEqual(
            sha256(MARKDOWN_SOURCE.encode("utf-8")).hexdigest(),
            MARKDOWN_SHA256,
        )
        first = import_text_book(
            MARKDOWN_SOURCE,
            source_name="multilingual.md",
            source_format="markdown",
            language="uk",
        )
        second = import_text_book(
            MARKDOWN_SOURCE,
            source_name="multilingual.md",
            source_format="markdown",
            language="uk",
        )
        self.assertEqual(first.source_sha256, MARKDOWN_SHA256)
        self._assert_common_reading_identity(first, second)

        self.assertGreaterEqual(len(first.document.headings()), 3)
        self.assertGreaterEqual(len(first.document.lists()), 2)
        self.assertTrue(
            any(
                isinstance(block, Note)
                and block.note_type == "image"
                and "szachownica" in block.text
                for block in first.document.blocks
            )
        )
        self._assert_no_fabricated_chess(first.document, pgn_games=first.pgn_games)

    def test_html_semantics_identity_progress_and_no_unmarked_chess(self) -> None:
        self.assertEqual(sha256(HTML_SOURCE.encode("utf-8")).hexdigest(), HTML_SHA256)
        first = import_html_book(
            HTML_SOURCE,
            source_name="multilingual.html",
            available_assets={"images/board.png"},
        )
        second = import_html_book(
            HTML_SOURCE,
            source_name="multilingual.html",
            available_assets={"images/board.png"},
        )
        self.assertEqual(first.source_sha256, HTML_SHA256)
        self._assert_common_reading_identity(first, second)

        self.assertGreaterEqual(len(first.document.headings()), 3)
        self.assertGreaterEqual(len(first.document.lists()), 2)
        self.assertTrue(
            any(
                isinstance(block, Note)
                and block.note_type == "image"
                and "szachownica" in block.text
                for block in first.document.blocks
            )
        )
        self._assert_no_fabricated_chess(first.document, pgn_games=first.pgn_games)

    def test_epub_semantics_identity_progress_and_no_unmarked_chess(self) -> None:
        source = _epub_source()
        self.assertEqual(sha256(source).hexdigest(), EPUB_SHA256)
        first = import_epub_book(source, source_name="multilingual.epub")
        second = import_epub_book(source, source_name="multilingual.epub")
        self.assertEqual(first.source_sha256, EPUB_SHA256)
        self._assert_common_reading_identity(first, second)

        self.assertEqual(first.document.language, "uk")
        self.assertGreaterEqual(len(first.document.headings()), 3)
        self.assertGreaterEqual(len(first.document.lists()), 2)
        self.assertTrue(
            any(
                isinstance(block, Note)
                and block.note_type == "image"
                and "szachownica" in block.text
                for block in first.document.blocks
            )
        )
        self._assert_no_fabricated_chess(first.document, pgn_games=first.pgn_games)


if __name__ == "__main__":
    unittest.main()
