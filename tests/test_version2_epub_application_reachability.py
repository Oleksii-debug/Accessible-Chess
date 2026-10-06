from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_epub_import import BookEpubImportError, BookEpubImportErrorCode
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import Diagram, Game, Paragraph
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application


_CONTAINER = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''


def _epub(chapter: bytes) -> bytes:
    opf = b'''<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="bookid"
 xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
  <metadata>
    <dc:identifier id="bookid">urn:acs:application-reachability-fixture</dc:identifier>
    <dc:title>Application EPUB</dc:title>
    <dc:language>uk</dc:language>
    <dc:rights>Test fixture</dc:rights>
    <meta property="dcterms:modified">2026-10-05T00:00:00Z</meta>
  </metadata>
  <manifest>
    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>'''
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_STORED
        archive.writestr(mimetype, b"application/epub+zip")
        archive.writestr("META-INF/container.xml", _CONTAINER, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("OEBPS/Text/ch1.xhtml", chapter, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("OEBPS/nav.xhtml", b'<html xmlns="http://www.w3.org/1999/xhtml"><body><nav/></body></html>', compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


class Version2EpubApplicationReachabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.progress = BookProgressStore(self.root / "book-progress.json")
        self.app = Version2Application(
            self.database,
            progress_store=self.progress,
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_: None,
            board_position_projector=lambda _fen: {"ok": True},
        )

    def _write_epub(self, name: str, chapter: bytes) -> Path:
        path = self.root / name
        path.write_bytes(_epub(chapter))
        return path

    def test_epub_is_reachable_through_real_book_open_and_persists_semantic_cursor(self) -> None:
        chapter = f'''<html lang="uk"><body>
<h1 id="chapter">Розділ EPUB</h1>
<p>Доступний текст книги.</p>
<img id="position" alt="Початкова позиція" data-acs-fen="{Board.START}"/>
<p>Після позиції.</p>
</body></html>'''.encode("utf-8")
        source = self._write_epub("навчання.epub", chapter)

        warning_count = self.app.open_book(source)

        self.assertEqual(warning_count, 0)
        self.assertEqual(self.app.shell.current_route.route_id, "books")
        self.assertEqual(self.app.reader.document.title, "Application EPUB")
        self.assertEqual(self.app.reader.document.language, "uk")
        self.assertEqual(self.app.reader.document.source_rights, "Test fixture")
        readable = [
            block.text
            for block in self.app.reader.document.blocks
            if isinstance(block, Paragraph)
        ]
        self.assertIn("Доступний текст книги.", readable)
        self.assertIn("Після позиції.", readable)
        self.assertTrue(self.app.book_key.startswith("epub-sha256:"))
        self.assertTrue(self.progress.has(self.app.book_key))
        self.assertEqual(self.app.reader.location().kind, "Heading")

        position = self.app.reader.next_position()
        self.assertEqual(position.kind, "Diagram")
        diagram = self.app.reader.document.blocks[position.index]
        self.assertIsInstance(diagram, Diagram)
        self.assertEqual(diagram.fen, Board.START)
        self.app.save_book_progress()

        restarted = Version2Application(
            self.database,
            progress_store=self.progress,
            engine_assistance=self.app.engine_assistance,
            board_dispatch=lambda *_: None,
            board_position_projector=lambda _fen: {"ok": True},
        )
        restarted.open_book(source)
        self.assertEqual(restarted.reader.location(), position)
        self.assertEqual(restarted.reader.document.blocks[position.index].fen, Board.START)

    def test_epub_semantic_position_opens_on_canonical_board_and_returns_exactly(self) -> None:
        chapter = f'''<html><body>
<h1>Board flow</h1>
<p>Before.</p>
<img id="position" alt="Початкова позиція" data-acs-fen="{Board.START}"/>
<p>After.</p>
</body></html>'''.encode("utf-8")
        source = self._write_epub("board-flow.epub", chapter)
        projected: list[str] = []
        self.app._board_position_projector = (
            lambda fen: projected.append(fen) or {"ok": True}
        )

        self.app.open_book(source)
        origin = self.app.reader.next_position()
        self.app.save_book_progress()

        result = self.app.browser_command("books", "book.open_position")

        self.assertEqual(result["kind"], "delegated")
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.assertEqual(projected[-1], Board.START)

        returned = self.app.browser_command("review", "book.return")
        self.assertEqual(returned["kind"], "review")
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual(self.app.shell.current_route.route_id, "books")
        self.assertEqual(self.app.reader.location(), origin)
        self.assertEqual(
            self.progress.restore(self.app.book_key, self.app.reader.document).location(),
            origin,
        )

    def test_shell_book_open_reaches_epub_through_dialog_and_hides_local_path(self) -> None:
        source = self._write_epub(
            "навчання з пробілом.epub",
            b"<html><body><h1>Shell EPUB</h1><p>Reachable through dialog.</p></body></html>",
        )
        self.app.open_book_dialog = lambda: source

        result = self.app.browser_command("shell", "book.open")

        self.assertEqual(result["kind"], "delegated")
        self.assertEqual(self.app.shell.current_route.route_id, "books")
        self.assertEqual(self.app.reader.document.headings()[0].text, "Shell EPUB")
        self.assertTrue(self.app.book_key.startswith("epub-sha256:"))
        self.assertTrue(self.progress.has(self.app.book_key))
        rendered = json.dumps(self.app.snapshot(), ensure_ascii=False)
        self.assertNotIn(str(self.root), rendered)

    def test_uppercase_epub_extension_uses_same_canonical_ingress(self) -> None:
        source = self._write_epub(
            "UPPER.EPUB",
            b"<html><body><h1>Uppercase EPUB</h1><p>Readable.</p></body></html>",
        )

        warning_count = self.app.open_book(source)

        self.assertEqual(warning_count, 0)
        self.assertEqual(self.app.shell.current_route.route_id, "books")
        self.assertEqual(self.app.reader.document.headings()[0].text, "Uppercase EPUB")
        self.assertTrue(self.app.book_key.startswith("epub-sha256:"))

    def test_oversize_epub_fails_before_import_and_preserves_current_book(self) -> None:
        stable = self._write_epub(
            "stable-before-oversize.epub",
            b"<html><body><h1>Stable</h1><p>Keep me.</p></body></html>",
        )
        self.app.open_book(stable)
        reader_before = self.app.reader
        key_before = self.app.book_key
        route_before = self.app.shell.current_route.route_id
        snapshot_before = reader_before.snapshot()

        oversize = self.root / "oversize.epub"
        oversize.write_bytes(b"x" * 17)
        with patch("acs.version2_application.MAX_EPUB_SOURCE_BYTES", 16):
            with self.assertRaisesRegex(ValueError, "source exceeds the supported byte limit"):
                self.app.open_book(oversize)

        self.assertIs(self.app.reader, reader_before)
        self.assertEqual(self.app.book_key, key_before)
        self.assertEqual(self.app.shell.current_route.route_id, route_before)
        self.assertEqual(self.app.reader.snapshot(), snapshot_before)

    def test_malformed_explicit_epub_chess_content_never_replaces_current_book(self) -> None:
        valid = self._write_epub(
            "valid.epub",
            b"<html><body><h1>Stable</h1><p>Keep this book open.</p></body></html>",
        )
        self.app.open_book(valid)
        reader_before = self.app.reader
        key_before = self.app.book_key
        route_before = self.app.shell.current_route.route_id
        snapshot_before = reader_before.snapshot()

        invalid = self._write_epub(
            "invalid.epub",
            b'<html><body><p>Before</p><div data-acs-fen="8/8/8/8/8/8/8/8 w - - 0 1"></div></body></html>',
        )
        with self.assertRaises(BookEpubImportError) as caught:
            self.app.open_book(invalid)

        self.assertEqual(caught.exception.code, BookEpubImportErrorCode.MALFORMED_CHESS_CONTENT)
        self.assertIs(self.app.reader, reader_before)
        self.assertEqual(self.app.book_key, key_before)
        self.assertEqual(self.app.shell.current_route.route_id, route_before)
        self.assertEqual(self.app.reader.snapshot(), snapshot_before)

    def test_shell_malformed_epub_fails_closed_without_replacing_current_book(self) -> None:
        stable = self._write_epub(
            "stable-shell.epub",
            b"<html><body><h1>Stable shell book</h1><p>Keep this state.</p></body></html>",
        )
        self.app.open_book(stable)
        reader_before = self.app.reader
        key_before = self.app.book_key
        route_before = self.app.shell.current_route.route_id
        snapshot_before = reader_before.snapshot()

        invalid = self._write_epub(
            "invalid-shell.epub",
            b'<html><body><div data-acs-fen="8/8/8/8/8/8/8/8 w - - 0 1"></div></body></html>',
        )
        self.app.open_book_dialog = lambda: invalid
        self.app.record_focus(f"book-block-{self.app.reader.index}")
        focus_before = self.app.snapshot()["screen"]["focus_target"]

        result = self.app.browser_command("shell", "book.open")

        self.assertEqual(result["kind"], "error")
        self.assertNotIn(str(self.root), json.dumps(result, ensure_ascii=False))
        self.assertEqual(self.app.snapshot()["screen"]["focus_target"], focus_before)
        self.assertIs(self.app.reader, reader_before)
        self.assertEqual(self.app.book_key, key_before)
        self.assertEqual(self.app.shell.current_route.route_id, route_before)
        self.assertEqual(self.app.reader.snapshot(), snapshot_before)

    def test_same_path_changed_epub_bytes_do_not_reuse_stale_progress_identity(self) -> None:
        source = self._write_epub(
            "same-path.epub",
            b"<html><body><h1>First</h1><p>One.</p><p>Two.</p></body></html>",
        )
        self.app.open_book(source)
        first_key = self.app.book_key
        self.app.reader.next_block()
        first_location = self.app.reader.location()
        self.app.save_book_progress()
        self.assertEqual(self.progress.restore(first_key, self.app.reader.document).location(), first_location)

        source.write_bytes(
            _epub(b"<html><body><h1>Second</h1><p>Replacement content.</p></body></html>")
        )
        self.app.open_book(source)

        self.assertNotEqual(self.app.book_key, first_key)
        self.assertEqual(self.app.reader.location().kind, "Heading")
        self.assertEqual(self.app.reader.document.headings()[0].text, "Second")
        self.assertTrue(self.progress.has(first_key))
        self.assertTrue(self.progress.has(self.app.book_key))

    def test_corrupt_epub_container_is_atomic_against_current_book_state(self) -> None:
        valid = self._write_epub(
            "stable.epub",
            b"<html><body><h1>Stable book</h1><p>Remain open.</p></body></html>",
        )
        self.app.open_book(valid)
        reader_before = self.app.reader
        key_before = self.app.book_key
        route_before = self.app.shell.current_route.route_id
        snapshot_before = reader_before.snapshot()

        corrupt = self.root / "corrupt.epub"
        corrupt.write_bytes(b"not-an-epub-container")
        with self.assertRaises(BookEpubImportError) as caught:
            self.app.open_book(corrupt)

        self.assertEqual(caught.exception.code, BookEpubImportErrorCode.UNSUPPORTED_CONTAINER)
        self.assertIs(self.app.reader, reader_before)
        self.assertEqual(self.app.book_key, key_before)
        self.assertEqual(self.app.shell.current_route.route_id, route_before)
        self.assertEqual(self.app.reader.snapshot(), snapshot_before)

    def test_unmarked_pgn_inside_epub_remains_selectable_reading_text(self) -> None:
        source = self._write_epub(
            "quoted.epub",
            b'''<html><body><h1>Quoted game</h1><pre>[Event "Quoted"]
[White "A"]
[Black "B"]
[Result "*"]

1. d4 d5 *</pre></body></html>''',
        )
        self.app.open_book(source)

        self.assertFalse(any(isinstance(block, Game) for block in self.app.reader.document.blocks))
        readable = "\n".join(
            block.text
            for block in self.app.reader.document.blocks
            if isinstance(block, Paragraph)
        )
        self.assertIn('[Event "Quoted"]', readable)


if __name__ == "__main__":
    unittest.main()
