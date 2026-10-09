"""Revised Sections 38/39: real expert CC0 Books in UA and EN, one rules owner.

Checks language and actual product Books/Training/Board entry, not external
publisher book bytes or human NVDA signoff.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import Exercise
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.full_product_ui_shell import UILanguage
from acs.section40_advanced_training_runtime import (
    ADVANCED_BOOK_KEY, ADVANCED_MATERIAL_ID, EXTREME_BOOK_KEY, EXTREME_MATERIAL_ID,
    build_advanced_offline_material, build_extreme_offline_material,
)
from acs.version2_starter_content_application import Version2StarterContentApplication


class BilingualAdvancedProducts(unittest.TestCase):
    def test_original_puzzles_have_identical_chess_semantics_across_languages(self):
        for material in (build_advanced_offline_material, build_extreme_offline_material):
            with self.subTest(material=material.__name__):
                uk, uk_tasks = material()
                en, en_tasks = material(language="en")
                self.assertEqual(uk.language, "uk")
                self.assertEqual(en.language, "en")
                self.assertEqual(uk_tasks, en_tasks)
                self.assertNotEqual(uk.title, en.title)
                self.assertNotEqual(uk.blocks[1].text, en.blocks[1].text)
                uk_exercises = [b for b in uk.blocks if isinstance(b, Exercise)]
                en_exercises = [b for b in en.blocks if isinstance(b, Exercise)]
                self.assertEqual(len(uk_exercises), len(en_exercises))
                self.assertGreaterEqual(len(en_exercises), 4)
                for u, e in zip(uk_exercises, en_exercises, strict=True):
                    self.assertEqual((u.fen, u.answer_text, u.source_anchor, u.block_id),
                                     (e.fen, e.answer_text, e.source_anchor, e.block_id))
                    self.assertNotEqual(u.prompt, e.prompt)
                for invalid in ("ru", "", "auto", None, 0, True):
                    with self.assertRaises(ValueError):
                        material(language=invalid)

    def test_all_twenty_actual_master_puzzles_have_localized_ukrainian_themes(self):
        from acs.section40_advanced_training_runtime import _THEMES_UK, _display_themes
        from acs.section40_advanced_licensed_dataset import bundled_advanced_puzzles
        originals = bundled_advanced_puzzles()
        observed = set().union(*(set(puzzle["themes"]) for puzzle in originals))
        self.assertEqual(len(observed), 28)
        self.assertTrue(observed.issubset(_THEMES_UK))
        self.assertEqual(len(_THEMES_UK), 28)
        uk, uk_tasks = build_advanced_offline_material(language="uk")
        en, en_tasks = build_advanced_offline_material(language="en")
        self.assertEqual(uk_tasks, en_tasks)
        for uk_exercise, en_exercise, source in zip(
            uk.exercises(), en.exercises(), originals, strict=True
        ):
            with self.subTest(puzzle=source["puzzle_id"]):
                self.assertEqual(uk_exercise.fen, en_exercise.fen)
                self.assertEqual(uk_exercise.answer_text, en_exercise.answer_text)
                for technical in source["themes"]:
                    self.assertIn(_THEMES_UK[technical], uk_exercise.prompt)
                    self.assertIn(technical, en_exercise.prompt)
                self.assertEqual(
                    _display_themes(source["themes"], "en"),
                    ", ".join(source["themes"]),
                )
        self.assertEqual(_display_themes(["zugzwang"], "uk"), "цугцванг")

    def test_english_ui_shows_authentic_advanced_books_and_preserves_uk_progress(self):
        with tempfile.TemporaryDirectory(prefix="acs-advanced-bilingual-ui-") as tmp:
            root = Path(tmp)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                kwargs = dict(
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda fen: {"ok": True, "fen": fen},
                )
                uk_app = Version2StarterContentApplication(database, **kwargs)
                try:
                    uk_app.browser_command("shell", "screen.books")
                    opening = uk_app.browser_command(
                        "books", "book.open_starter_material",
                        {"material_id": ADVANCED_MATERIAL_ID},
                    )
                    self.assertEqual(opening["kind"], "render")
                    self.assertEqual(uk_app.book_key, ADVANCED_BOOK_KEY)
                    self.assertEqual(uk_app.reader.document.language, "uk")
                    uk_app.reader.next_block()
                    uk_app.save_book_progress()
                    original = uk_app.reader.location()
                finally:
                    uk_app.shutdown()

                # shutdown closes the owned ACSDB connection. Reopen actual
                # disk state, never reuse the closed handle as a fake restart.
                en_database = AcsDatabase(root / "library.acsdb")
                en_app = Version2StarterContentApplication(
                    en_database, language=UILanguage.EN,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda fen: {"ok": True, "fen": fen},
                )
                try:
                    en_app.browser_command("shell", "screen.books")
                    items = en_app.snapshot()["books"]["starter_materials"]["items"]
                    english_label = next(
                        item["title"] for item in items
                        if item["material_id"] == ADVANCED_MATERIAL_ID
                    )
                    self.assertTrue(english_label.startswith("16 authentic"))
                    opened = en_app.browser_command(
                        "books", "book.open_starter_material",
                        {"material_id": ADVANCED_MATERIAL_ID},
                    )
                    self.assertEqual(opened["kind"], "render")
                    self.assertEqual(en_app.book_key, ADVANCED_BOOK_KEY + ":en")
                    self.assertEqual(en_app.reader.document.language, "en")
                    self.assertEqual(len(en_app.reader.document.exercises()), 16)
                    for _ in range(3):
                        en_app.browser_command("books", "book.next")
                    self.assertEqual(en_app.reader.location().kind, "Exercise")
                    board_open = en_app.browser_command("books", "book.open_position")
                    self.assertEqual(board_open["kind"], "delegated")
                    self.assertEqual(en_app.shell.current_route.route_id, "board")
                finally:
                    en_app.shutdown()

                self.assertEqual(
                    BookProgressStore(root / "book-progress.json").restore(
                        ADVANCED_BOOK_KEY, build_advanced_offline_material()[0]
                    ).location(),
                    original,
                )
            finally:
                analysis.close()
                database.close()

    def test_extreme_english_book_uses_separate_language_key(self):
        document, tasks = build_extreme_offline_material(language="en")
        self.assertEqual(document.language, "en")
        self.assertEqual(len(tasks), 4)
        self.assertGreaterEqual(min(t["puzzle_rating_lichess_not_fide"] for t in tasks), 3000)
        self.assertTrue(document.title.startswith("Extreme Lichess"))
        self.assertNotEqual(EXTREME_BOOK_KEY, EXTREME_BOOK_KEY + ":en")


if __name__ == "__main__":
    unittest.main()
