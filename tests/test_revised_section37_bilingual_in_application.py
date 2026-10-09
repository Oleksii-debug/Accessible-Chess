"""Section 37 bilingual REAL user books -> actual Version2Application Books route.

Exercises one application route rather than calling format parsers in isolation.
No GUI/NVDA hardware automation is claimed by this test.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.chesscore import Board
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application
from tools.revised_section37_bilingual_workbook_pack import load_advanced_workbook, make_pack


class BilingualOwnerBooksProductReadback(unittest.TestCase):
    def test_all_twelve_original_workbook_uci_variants_are_legal_in_canonical_chess_model(self):
        data = load_advanced_workbook()
        for lesson in data["lessons"]:
            with self.subTest(lesson=lesson["lesson_id"], rating=lesson["rating_lichess_puzzle"]):
                board = Board(lesson["fen_before_opponent_move"])
                fen_before = board.fen()
                # Original Lichess puzzles begin with one previous opponent move.
                first_san = board.push_text(lesson["opponent_previous_move_uci"])
                self.assertTrue(first_san)
                self.assertNotEqual(board.fen(), fen_before)
                self.assertEqual(len(board.undo_stack), 1)
                for uci in lesson["solution_after_opponent_uci"]:
                    self.assertTrue(board.push_text(uci))
                self.assertEqual(
                    len(board.undo_stack),
                    1 + len(lesson["solution_after_opponent_uci"]),
                )
                self.assertTrue(board.fen())
                # Source verification must never mutate a second chess model.
                for _ in range(len(lesson["solution_after_opponent_uci"]) + 1):
                    board.undo()
                self.assertEqual(board.fen(), fen_before)

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
                    self.assertTrue(prepared.document.title)
                    self.assertTrue(
                        prepared.document.title.startswith("Advanced Chess Laboratory")
                        or prepared.document.title.startswith("Майстерська шахова лабораторія")
                        or source.suffix == ".txt",  # Plain TXT has no semantic title declaration.
                    )
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
                        warning_count = first.commit_prepared_book_open(
                            Version2Application.prepare_book_open(source)
                        )
                        self.assertEqual(warning_count, 0)
                        self.assertEqual(first.shell.current_route.route_id, "books")
                        self.assertIsNotNone(first.books)
                        self.assertGreater(len(first.reader.document.blocks), 20)
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

    def test_original_uk_en_pdf_is_explicitly_not_falsely_claimed_as_native_book_import(self):
        # PDF is generated for accessible external viewers in a separate job.
        # Current canonical Book open does not include a PDF ingress adapter.
        with tempfile.TemporaryDirectory(prefix="section37-pdf-native-truth-") as tmp:
            source = Path(tmp) / "advanced-uk.pdf"
            source.write_bytes(b"%PDF-1.4\\nnot a full PDF because only extension guard runs")
            with self.assertRaisesRegex(ValueError, "unsupported book source"):
                Version2Application.prepare_book_open(source)

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
