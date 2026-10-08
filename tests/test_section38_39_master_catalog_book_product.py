"""25 original master-level UA/EN genre entries are usable inside Books, not
just named by a project document. No copyrighted third-party books copied.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.bookdocument import BookDocument, Heading, Paragraph
from acs.bookreader import BookReader
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.full_product_ui_shell import UILanguage
from acs.section38_39_professional_catalog_book import (
    MATERIAL_ID, BOOK_KEY_UK, BOOK_KEY_EN,
    build_professional_genre_book, source_bytes, professional_genres,
)
from acs.version2_starter_content_application import Version2StarterContentApplication


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "docs/corpus/SECTION38_39_MASTER_GENRES_UA_EN_SOURCE_MATRIX.json"


class ProfessionalCatalogProductTests(unittest.TestCase):
    def test_windows_packaged_module_matches_qualified_docs_bytes_exactly(self):
        source = source_bytes()
        original = CANONICAL.read_bytes()
        self.assertEqual(source, original)
        self.assertEqual(
            hashlib.sha256(source).hexdigest(), hashlib.sha256(original).hexdigest()
        )
        records = professional_genres()
        self.assertEqual(len(records), 25)
        self.assertEqual(len({g["id"] for g in records}), 25)

    def test_readable_uk_en_heading_navigation_and_book_progress_snapshots(self):
        ids = tuple(g["id"] for g in professional_genres())
        self.assertEqual(len(ids), 25)
        for language in ("uk", "en"):
            with self.subTest(language=language):
                doc = build_professional_genre_book(language=language)
                self.assertEqual(doc.language, language)
                self.assertIn("25", doc.title)
                self.assertIs(type(doc), BookDocument)
                headings = [x for x in doc.blocks if isinstance(x, Heading)]
                self.assertEqual(len(headings), 26)
                self.assertEqual([h.source_anchor for h in headings[1:]],
                                 ["section38:master:genre:" + x for x in ids])
                self.assertTrue(all(isinstance(b, (Heading, Paragraph))
                                    for b in doc.blocks))
                self.assertFalse(any("COPYRIGHTED FULL" in b.text.upper()
                                     for b in doc.blocks))
                reader = BookReader(doc)
                first = reader.next_heading()
                self.assertEqual(first.kind, "Heading")
                reader.save_return_point("after-first-master-genre")
                snap = reader.snapshot()
                restored = BookReader.restore_snapshot(
                    BookDocument.from_dict(doc.as_dict()), snap
                )
                self.assertEqual(restored.location(), first)
                self.assertEqual(restored.restore_return_point(
                    "after-first-master-genre"), first)
                # Navigate ALL 25 genre headings with the same keyboard-next
                # semantic navigation method used by accessible Books, not
                # just check one index in a static catalogue.
                traversed = [first.source_anchor]
                for _ in range(24):
                    item = restored.next_heading()
                    traversed.append(item.source_anchor)
                    self.assertEqual(item.kind, "Heading")
                self.assertEqual(
                    traversed,
                    ["section38:master:genre:" + ident for ident in ids],
                )
                with self.assertRaises(LookupError):
                    restored.next_heading()
                restored.restore_return_point("after-first-master-genre")
                self.assertEqual(restored.location(), first)
                self.assertEqual(
                    len([x for x in doc.blocks if isinstance(x, Paragraph)
                         and "NOT VERIFIED" in x.text]), 25 if language == "en" else 0
                )
        with self.assertRaises(ValueError):
            build_professional_genre_book(language="ru")

    def test_actual_bilingual_books_keyboard_commands_can_navigate_all_twenty_five(self):
        ordered = tuple(genre["id"] for genre in professional_genres())
        for language_code, language in (
            ("uk", UILanguage.UA), ("en", UILanguage.EN),
        ):
            with self.subTest(language=language_code):
                with tempfile.TemporaryDirectory(prefix="acs-master-genre-webview-") as temp:
                    root = Path(temp)
                    database = AcsDatabase(root / "library.acsdb")
                    analysis = AnalysisService(lambda: None)
                    try:
                        app = Version2StarterContentApplication(
                            database, language=language,
                            progress_store=BookProgressStore(root / "books.json"),
                            engine_assistance=EngineAssistedWorkflowService(analysis),
                            board_dispatch=lambda *_: None,
                            board_position_projector=lambda fen: {"fen": fen},
                        )
                        try:
                            app.browser_command("shell", "screen.books")
                            first = app.browser_command(
                                "books", "book.open_starter_material",
                                {"material_id": MATERIAL_ID},
                            )
                            self.assertEqual(first["kind"], "render")
                            self.assertEqual(
                                first["payload"]["snapshot"]["document"]["lang"],
                                language_code,
                            )
                            for index, source_id in enumerate(ordered, 1):
                                rendered = app.browser_command(
                                    "books", "book.next_heading"
                                )
                                self.assertEqual(rendered["kind"], "render")
                                payload = rendered["payload"]
                                block = payload["snapshot"]["block"]
                                self.assertEqual(
                                    block["source_anchor"],
                                    "section38:master:genre:" + source_id,
                                )
                                self.assertEqual(block["heading_level"], 2)
                                self.assertEqual(block["role"], "heading")
                                self.assertEqual(
                                    payload["focus_target"],
                                    block["dom_id"],
                                    "NVDA keyboard focus must follow real Book heading",
                                )
                                self.assertTrue(block["title"])
                                self.assertIn(str(index), block["title"])
                        finally:
                            app.shutdown()
                    finally:
                        analysis.close()

    def test_actual_v2_books_catalogue_opens_expert_25_genre_guide_in_both_languages(self):
        with tempfile.TemporaryDirectory(prefix="acs-masters-genre-books-product-") as temp:
            root = Path(temp)
            analysis = AnalysisService(lambda: None)
            try:
                db_uk = AcsDatabase(root / "library.acsdb")
                app_uk = Version2StarterContentApplication(
                    db_uk,
                    progress_store=BookProgressStore(root / "read-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda fen: {"fen": fen},
                )
                try:
                    app_uk.browser_command("shell", "screen.books")
                    listing = app_uk.snapshot()["books"]["starter_materials"]["items"]
                    self.assertEqual(sum(x["material_id"] == MATERIAL_ID for x in listing), 1)
                    selected = app_uk.browser_command(
                        "books", "book.open_starter_material",
                        {"material_id": MATERIAL_ID},
                    )
                    self.assertEqual(selected["kind"], "render")
                    self.assertEqual(app_uk.book_key, BOOK_KEY_UK)
                    self.assertEqual(app_uk.reader.document.language, "uk")
                    self.assertEqual(len(app_uk.reader.document.headings()), 26)
                    location = app_uk.reader.next_heading()
                    app_uk.save_book_progress()
                finally:
                    app_uk.shutdown()

                # The original application shuts down and closes its ACSDB.
                # Reopen the exact on-disk database for a genuine restart.
                db_en = AcsDatabase(root / "library.acsdb")
                app_en = Version2StarterContentApplication(
                    db_en, language=UILanguage.EN,
                    progress_store=BookProgressStore(root / "read-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda fen: {"fen": fen},
                )
                try:
                    app_en.browser_command("shell", "screen.books")
                    listing = app_en.snapshot()["books"]["starter_materials"]["items"]
                    label = next(x["title"] for x in listing if x["material_id"] == MATERIAL_ID)
                    self.assertIn("Advanced chess", label)
                    selected = app_en.browser_command(
                        "books", "book.open_starter_material",
                        {"material_id": MATERIAL_ID},
                    )
                    self.assertEqual(selected["kind"], "render")
                    self.assertEqual(app_en.book_key, BOOK_KEY_EN)
                    self.assertEqual(app_en.reader.document.language, "en")
                    self.assertEqual(len(app_en.reader.document.headings()), 26)
                    self.assertEqual(app_en.reader.next_heading().kind, "Heading")
                finally:
                    app_en.shutdown()
                recovered = BookProgressStore(root / "read-progress.json").restore(
                    BOOK_KEY_UK, build_professional_genre_book(language="uk")
                )
                self.assertEqual(recovered.location(), location)
            finally:
                analysis.close()


if __name__ == "__main__":
    unittest.main()
