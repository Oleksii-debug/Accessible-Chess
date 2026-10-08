"""Section 38.2/38.6: all five generated licensed high-level book formats
actually enter the SAME Windows Books Open path for English and Ukrainian.

Source is original-pinned Lichess CC0 puzzle content converted into derived QA
books, not independent original EPUB/DOCX/PDF by an external publisher.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.bookreader import BookReader
from acs.bookdocument import Position
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application
from tools.revised_section37_bilingual_workbook_pack import (
    load_advanced_workbook, make_pack,
)


class WindowsAdvancedBilingualBookOpenTests(unittest.TestCase):
    def test_genuine_source_derived_ten_files_open_and_resume_via_product_workflow(self):
        workbook = load_advanced_workbook()
        files = make_pack(workbook)
        self.assertEqual(len(files), 10)
        with tempfile.TemporaryDirectory(prefix="acs-section38-advanced-formats-") as temp:
            root = Path(temp)
            for lang in ("uk", "en"):
                for ext in ("md", "txt", "html", "docx", "epub"):
                    with self.subTest(language=lang, extension=ext):
                        filename = f"master-practice-{lang}.{ext}"
                        original = files[f"section37-advanced-workbook-{lang}.{ext}"]
                        (root / filename).write_bytes(original)
                        self.assertGreater(len(original), 250)
                        expected_sha = hashlib.sha256(original).hexdigest()
                        self.assertEqual(
                            hashlib.sha256((root / filename).read_bytes()).hexdigest(),
                            expected_sha,
                        )
                        prepared = Version2Application.prepare_book_open(root / filename)
                        self.assertTrue(prepared.book_key)
                        self.assertGreater(len(prepared.document.blocks), 20)
                        self.assertEqual(prepared.document.source_name, filename)
                        reader = BookReader(prepared.document)
                        origin = reader.location()
                        after = reader.next_block()
                        self.assertEqual(after.index, origin.index + 1)
                        reader.save_return_point("same_material_after_restart")
                        snap = reader.snapshot()
                        # Read original filesystem bytes again: no cached mock.
                        reopened = Version2Application.prepare_book_open(root / filename)
                        self.assertEqual(prepared.book_key, reopened.book_key)
                        restored = BookReader.restore_snapshot(reopened.document, snap)
                        self.assertEqual(restored.location(), after)
                        self.assertEqual(
                            restored.restore_return_point("same_material_after_restart"),
                            after,
                        )
                        if ext in ("md", "html", "epub"):
                            self.assertTrue(any(isinstance(b, Position)
                                                for b in reopened.document.blocks))
                            self.assertIsNotNone(restored.next_position())

    def test_english_epub_and_ukrainian_docx_reach_real_books_route(self):
        files = make_pack(load_advanced_workbook())
        with tempfile.TemporaryDirectory(prefix="acs-section38-books-ui-") as raw:
            root = Path(raw)
            db = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2Application(
                    db,
                    progress_store=BookProgressStore(root / "books.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda fen: {"fen": fen},
                )
                for language, suffix in (("en", "epub"), ("uk", "docx")):
                    with self.subTest(language=language, fmt=suffix):
                        source = root / f"advanced-{language}.{suffix}"
                        source.write_bytes(
                            files[f"section37-advanced-workbook-{language}.{suffix}"]
                        )
                        value = app.commit_prepared_book_open(
                            Version2Application.prepare_book_open(source)
                        )
                        self.assertIsInstance(value, int)
                        self.assertEqual(app.shell.current_route.route_id, "books")
                        self.assertGreater(len(app.reader.document.blocks), 20)
                        self.assertIsNotNone(app.books.projection.snapshot())
                        self.assertTrue(app.reader.document.title)
            finally:
                analysis.close()
                db.close()


if __name__ == "__main__":
    unittest.main()
