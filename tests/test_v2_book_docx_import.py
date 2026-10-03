from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_docx_import import BookDocxImportError, import_docx_book
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import Heading, ListBlock, Note, Paragraph
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application


def _docx(*, body: str, styles: str | None = None, extra=None) -> bytes:
    document = f'''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">
  <w:body>{body}</w:body>
</w:document>'''.encode("utf-8")
    default_styles = b'''<?xml version="1.0" encoding="UTF-8"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
</w:styles>'''
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("word/styles.xml", (styles.encode("utf-8") if isinstance(styles, str) else default_styles))
        for name, payload in (extra or {}).items():
            archive.writestr(name, payload)
    return buffer.getvalue()


BODY = '''
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Шахова книга DOCX</w:t></w:r></w:p>
<w:p><w:r><w:t>Перший доступний абзац.</w:t></w:r></w:p>
<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Пункт списку</w:t></w:r></w:p>
<w:p><w:r><w:t>Перед зображенням</w:t></w:r><w:r><wp:docPr id="1" name="Picture 1" descr="Діаграма без машинної позиції"/></w:r></w:p>
'''


class BookDocxImportTests(unittest.TestCase):
    def test_docx_projects_heading_text_list_and_image_alt_without_ai(self) -> None:
        result = import_docx_book(_docx(body=BODY), source_name="book.docx")
        self.assertTrue(result.book_key.startswith("docx-sha256:"))
        self.assertEqual("Шахова книга DOCX", result.document.title)
        self.assertTrue(any(isinstance(block, Heading) for block in result.document.blocks))
        self.assertTrue(any(isinstance(block, Paragraph) and "Перший" in block.text for block in result.document.blocks))
        self.assertTrue(any(isinstance(block, ListBlock) for block in result.document.blocks))
        notes = [block for block in result.document.blocks if isinstance(block, Note)]
        self.assertTrue(any("Діаграма без машинної позиції" in block.text for block in notes))
        self.assertTrue(any("no chess position was inferred" in warning for warning in result.warnings))
        self.assertEqual(0, result.positions)
        self.assertEqual(0, result.pgn_games)

    def test_docx_rejects_traversal_and_malformed_xml(self) -> None:
        with self.assertRaises(BookDocxImportError):
            import_docx_book(
                _docx(body=BODY, extra={"../escape.txt": b"x"}),
                source_name="unsafe.docx",
            )
        bad = BytesIO()
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("word/document.xml", b"<broken")
        with self.assertRaises(BookDocxImportError):
            import_docx_book(bad.getvalue(), source_name="bad.docx")


class Version2DocxReachabilityTests(unittest.TestCase):
    def test_real_open_book_route_accepts_docx_and_hides_local_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "навчальна книга.docx"
            source.write_bytes(_docx(body=BODY))
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            app = Version2Application(
                database,
                progress_store=BookProgressStore(root / "book-progress.json"),
                engine_assistance=EngineAssistedWorkflowService(analysis),
                board_dispatch=lambda *_: None,
                board_position_projector=lambda _fen: {"ok": True},
            )
            try:
                warnings = app.open_book(source)
                self.assertGreaterEqual(warnings, 1)
                self.assertEqual("books", app.shell.current_route.route_id)
                self.assertEqual("Шахова книга DOCX", app.reader.document.title)
                self.assertTrue(app.book_key.startswith("docx-sha256:"))
                rendered = json.dumps(app.snapshot(), ensure_ascii=False)
                self.assertNotIn(str(root), rendered)
                self.assertTrue(app.progress_store.has(app.book_key))
            finally:
                app.shutdown()
                analysis.close()
                database.close()


if __name__ == "__main__":
    unittest.main()
