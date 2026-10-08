"""Section 37 bilingual REAL user books -> actual Version2Application Books route.

Exercises one application route rather than calling format parsers in isolation.
No GUI/NVDA hardware automation is claimed by this test.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application
from tools.revised_section37_bilingual_workbook_pack import load_advanced_workbook, make_pack


class BilingualOwnerBooksProductReadback(unittest.TestCase):
    def test_all_ten_real_files_go_through_canonical_application_prepare_books(self):
        contents = make_pack(load_advanced_workbook())
        self.assertEqual(len(contents), 10)
        with tempfile.TemporaryDirectory(prefix="section37-owner-bilingual-") as tmp:
            root = Path(tmp)
            for name, raw in sorted(contents.items()):
                with self.subTest(book=name):
                    source = root / name
                    source.write_bytes(raw)
                    prepared = Version2Application.prepare_book_open(source)
                    self.assertGreater(len(prepared.document.blocks), 20)
                    self.assertTrue(prepared.book_key)
                    self.assertEqual(prepared.document.title.startswith("Advanced Chess Laboratory") or
                                     prepared.document.title.startswith("Майстерська шахова лабораторія"), True)
                    if source.suffix in (".md", ".html", ".epub"):
                        self.assertTrue(any(block.kind == "Position" for block in prepared.document.blocks))
                    if source.suffix in (".txt", ".docx"):
                        self.assertFalse(any(block.kind == "Position" for block in prepared.document.blocks))

    def test_ukrainian_and_english_epub_and_docx_open_in_actual_books_route_and_resume(self):
        files = make_pack(load_advanced_workbook())
        with tempfile.TemporaryDirectory(prefix="section37-owner-route-") as tmp:
            root = Path(tmp)
            db = AcsDatabase(root / "canonical-library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                helper = EngineAssistedWorkflowService(analysis)
                for lang in ("uk", "en"):
                    for fmt in (".epub", ".docx"):
                        source = root / f"section37-advanced-workbook-{lang}{fmt}"
                        source.write_bytes(files[source.name])
                        progress_path = root / ("progress-" + lang + fmt + ".json")

                        def app():
                            return Version2Application(
                                db,
                                progress_store=BookProgressStore(progress_path),
                                engine_assistance=helper,
                                board_dispatch=lambda *_: None,
                                board_position_projector=lambda fen: {"fen": fen},
                            )

                        first = app()
                        count = first.commit_prepared_book_open(
                            Version2Application.prepare_book_open(source)
                        )
                        self.assertIsInstance(count, int)
                        self.assertGreater(count, 20)
                        self.assertEqual(first.shell.current_route.route_id, "books")
                        self.assertIsNotNone(first.books)
                        before = first.reader.next_block()
                        self.assertIsNotNone(before)
                        first.save_book_progress()
                        resumed = app()
                        resumed.commit_prepared_book_open(
                            Version2Application.prepare_book_open(source)
                        )
                        self.assertEqual(resumed.shell.current_route.route_id, "books")
                        self.assertEqual(resumed.reader.location(), before)
                        self.assertIsNotNone(resumed.books.projection.snapshot())
            finally:
                analysis.close()
                db.close()

    def test_malformed_derived_epub_or_docx_never_becomes_owner_book(self):
        files = make_pack(load_advanced_workbook())
        with tempfile.TemporaryDirectory(prefix="section37-corrupt-uk-en-") as tmp:
            root = Path(tmp)
            for lang in ("uk", "en"):
                for fmt in (".epub", ".docx"):
                    source = root / f"corrupt-{lang}{fmt}"
                    payload = files[f"section37-advanced-workbook-{lang}{fmt}"]
                    source.write_bytes(payload[:min(65, len(payload))])
                    with self.subTest(source=source.name):
                        with self.assertRaises((ValueError, OSError, RuntimeError)):
                            Version2Application.prepare_book_open(source)


if __name__ == "__main__":
    unittest.main()
