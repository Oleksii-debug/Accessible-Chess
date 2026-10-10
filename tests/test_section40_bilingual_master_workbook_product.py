"""Section 40 real advanced Section37 workbook in the actual offline product Books menu."""
from __future__ import annotations
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import BookDocument
from acs.chesscore import Board
from acs.full_product_ui_shell import UILanguage
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_starter_content_application import Version2StarterContentApplication
from acs import section40_bilingual_master_workbook_runtime as runtime


class GenuineTwelveAdvancedWorkbookProductTests(unittest.TestCase):
    def test_embedded_source_is_identical_to_original_section37_json_file(self):
        root = Path(__file__).resolve().parents[1]
        original = (root / runtime.ORIGINAL_SOURCE_PATH).read_bytes()
        digest = hashlib.sha1(
            b"blob " + str(len(original)).encode("ascii") + bytes((0,)) + original
        ).hexdigest()
        self.assertEqual(digest, runtime.ORIGINAL_SOURCE_GIT_BLOB)
        self.assertEqual(original.decode("utf-8"), runtime._ORIGINAL_SOURCE_TEXT)
        data = runtime._canonical_source()
        self.assertEqual(len(data["lessons"]), 12)
        self.assertEqual(data["language_codes"], ["uk", "en"])

    def test_ukrainian_english_chess_truth_and_exact_twelve_exercises_match(self):
        uk, ukrainian_truth = runtime.build_real_bilingual_master_workbook(language="uk")
        en, english_truth = runtime.build_real_bilingual_master_workbook(language="en")
        self.assertEqual(ukrainian_truth, english_truth)
        self.assertEqual(uk.language, "uk")
        self.assertEqual(en.language, "en")
        self.assertEqual(len(uk.exercises()), 12)
        self.assertEqual(len(en.exercises()), 12)
        self.assertEqual(
            [e.fen for e in uk.exercises()],
            [e.fen for e in en.exercises()],
        )
        for document in (uk, en):
            self.assertEqual(BookDocument.from_dict(document.as_dict()).as_dict(), document.as_dict())
            self.assertEqual(
                len([block for block in document.blocks if block.kind == "Position"]), 12,
            )
            for block in document.exercises():
                self.assertEqual(Board(block.fen).fen(), block.fen)
            original_positions = [
                block for block in document.blocks if block.kind == "Position"
            ]
            self.assertEqual(len(original_positions), 12)
            self.assertTrue(all(
                original.caption and
                ("Position before" in original.caption if document.language == "en"
                 else "Позиція перед" in original.caption)
                for original in original_positions
            ))

    def test_actual_program_books_menu_can_open_training_and_board_offline(self):
        with tempfile.TemporaryDirectory(prefix="acs-section40-original-12-") as temp:
            root = Path(temp)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                def application():
                    return Version2StarterContentApplication(
                        database,
                        progress_store=BookProgressStore(root / "books-progress.json"),
                        engine_assistance=EngineAssistedWorkflowService(analysis),
                        board_dispatch=lambda *_: None,
                        board_position_projector=lambda fen: {"ok": True, "fen": fen},
                    )
                first = application()
                try:
                    first.browser_command("shell", "screen.books")
                    items = first.snapshot()["books"]["starter_materials"]
                    self.assertEqual(
                        items["authentic_advanced_bilingual_workbook_lessons"], 12,
                    )
                    self.assertIn(
                        runtime.MATERIAL_ID,
                        [item["material_id"] for item in items["items"]],
                    )
                    answer = first.browser_command(
                        "books", "book.open_starter_material",
                        {"material_id": runtime.MATERIAL_ID},
                    )
                    self.assertEqual(answer["kind"], "render")
                    self.assertTrue(answer["payload"]["focus_target"])
                    self.assertIn(
                        "Майстерська шахова лабораторія",
                        answer["payload"]["announcement"],
                    )
                    self.assertEqual(first.book_key, runtime.BOOK_KEY_PREFIX + ":uk")
                    for _ in range(7):
                        first.browser_command("books", "book.next")
                    self.assertEqual(first.reader.location().kind, "Exercise")
                    self.assertTrue(first._start_training_from_current_book())
                    self.assertEqual(first.reader.location().kind, "Exercise")
                    first.save_book_progress()
                    second = application()
                    try:
                        second.browser_command("shell", "screen.books")
                        reopened = second.browser_command(
                            "books", "book.open_starter_material",
                            {"material_id": runtime.MATERIAL_ID},
                        )
                        self.assertEqual(reopened["kind"], "render")
                        self.assertEqual(second.reader.location().kind, "Exercise")
                        result = second.browser_command("books", "book.open_position")
                        self.assertEqual(result["kind"], "delegated")
                        self.assertEqual(second.shell.current_route.route_id, "board")
                        self.assertEqual(second.reader.location().kind, "Exercise")
                    finally:
                        second.shutdown()
                finally:
                    first.shutdown()
            finally:
                analysis.close()
                database.close()

    def test_english_owner_screen_reader_books_open_has_exact_original_chess_truth(self):
        with tempfile.TemporaryDirectory(prefix="acs-source37-english-menu-") as temp:
            root = Path(temp)
            db = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    db,
                    progress_store=BookProgressStore(root / "books.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda fen: {"ok": True, "fen": fen},
                )
                try:
                    app.shell.set_language(UILanguage.EN)
                    app.browser_command("shell", "screen.books")
                    current = app.snapshot()["books"]["starter_materials"]
                    ours = [item for item in current["items"]
                            if item["material_id"] == runtime.MATERIAL_ID]
                    self.assertEqual(len(ours), 1)
                    self.assertIn("Advanced Chess Laboratory", ours[0]["title"])
                    opened = app.browser_command(
                        "books", "book.open_starter_material",
                        {"material_id": runtime.MATERIAL_ID},
                    )
                    self.assertEqual(opened["kind"], "render")
                    self.assertIn("Advanced Chess Laboratory",
                                  opened["payload"]["announcement"])
                    self.assertTrue(opened["payload"]["focus_target"])
                    self.assertEqual(app.book_key, runtime.BOOK_KEY_PREFIX + ":en")
                    self.assertEqual(app.reader.document.language, "en")
                    self.assertEqual(len(app.reader.document.exercises()), 12)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                db.close()

    def test_invalid_source_cannot_publish_new_program_workbook(self):
        with patch.object(runtime, "_ORIGINAL_SOURCE_TEXT", "{}"):
            with self.assertRaisesRegex(ValueError, "Git source identity"):
                runtime.build_real_bilingual_master_workbook()
        with self.assertRaisesRegex(ValueError, "language"):
            runtime.build_real_bilingual_master_workbook(language="ru")


if __name__ == "__main__":
    unittest.main()
