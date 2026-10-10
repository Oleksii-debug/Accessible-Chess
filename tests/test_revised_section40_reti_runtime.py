"""Genuine original 1921 Reti UK/EN endgame study through product Books and Board."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import BookDocument, Exercise, Game, Position
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.pgn_roundtrip import parse_pgn_text
from acs.section40_historical_reti_dataset import original_reti_source_bytes, SOURCE_ID
from acs.section40_historical_reti_runtime import (
    HISTORICAL_RETI_MATERIAL_ID, HISTORICAL_RETI_BOOK_KEY,
    build_historical_reti_offline_material,
)
from acs.lawful_corpus_registry import load_catalog, read_verified_source_snapshot
from acs.version2_starter_content_application import Version2StarterContentApplication

ROOT = Path(__file__).resolve().parents[1]


class HistoricalRetiProductTests(unittest.TestCase):
    def test_original_source_study_semantics_and_rights_are_real(self):
        source = next(x for x in load_catalog(
            ROOT / "docs/corpus/revised_sections37_40_sources.json"
        ) if x.get("id") == SOURCE_ID)
        self.assertEqual(source["acquisition"], "VENDORED_SOURCE_VERIFIED")
        self.assertTrue(source["redistribution"].startswith("permitted"))
        self.assertEqual(original_reti_source_bytes(),
                         read_verified_source_snapshot(ROOT / source["local_source"], source))
        for lang in ("uk","en"):
            with self.subTest(language=lang):
                doc, truth = build_historical_reti_offline_material(language=lang)
                self.assertEqual(doc.language, lang)
                self.assertEqual(truth["fen"], "7K/8/k1P5/7p/8/8/8/8 w - - 0 1")
                self.assertEqual(truth["first_solution_san"], "Kg7")
                self.assertTrue(truth["original_study_not_rating"])
                self.assertEqual(truth["game_count"], 1)
                self.assertEqual(BookDocument.from_dict(doc.as_dict()).as_dict(), doc.as_dict())
                self.assertEqual(len([x for x in doc.blocks if isinstance(x, Exercise)]), 1)
                self.assertEqual(len([x for x in doc.blocks if isinstance(x, Position)]), 1)
                games = [x for x in doc.blocks if isinstance(x, Game)]
                self.assertEqual(len(games), 1)
                parsed = parse_pgn_text(games[0].pgn, strict=True)
                self.assertEqual(len(parsed), 1)
                self.assertEqual(len(parsed[0].line.moves), 11)
                self.assertEqual(parsed[0].tags["SetUp"], "1")

    def test_changing_language_never_changes_fen_or_original_pgn(self):
        uk, uk_truth = build_historical_reti_offline_material(language="uk")
        en, en_truth = build_historical_reti_offline_material(language="en")
        self.assertNotEqual(uk.title, en.title)
        self.assertEqual(uk_truth, en_truth)
        self.assertEqual(
            [x.fen for x in uk.blocks if isinstance(x, Position)],
            [x.fen for x in en.blocks if isinstance(x, Position)],
        )

    def test_existing_books_training_and_board_routes_accept_original_study(self):
        with tempfile.TemporaryDirectory(prefix="acs-historical-reti-books-") as raw:
            root=Path(raw)
            db=AcsDatabase(root/"library.acsdb")
            analysis=AnalysisService(lambda: None)
            try:
                app=Version2StarterContentApplication(
                    db,
                    progress_store=BookProgressStore(root/"progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda fen: {"ok": True, "fen": fen},
                )
                try:
                    app.browser_command("shell","screen.books")
                    materials=app.snapshot()["books"]["starter_materials"]
                    self.assertEqual(materials["original_study_count"],1)
                    self.assertIn(HISTORICAL_RETI_MATERIAL_ID,
                        [item["material_id"] for item in materials["items"]])
                    opened=app.browser_command("books","book.open_starter_material",
                        {"material_id":HISTORICAL_RETI_MATERIAL_ID})
                    self.assertEqual(opened["kind"],"render")
                    self.assertEqual(app.book_key,HISTORICAL_RETI_BOOK_KEY)
                    self.assertEqual(len(app.reader.document.exercises()),1)
                    nxt=app.browser_command("books","book.next_position")
                    self.assertEqual(nxt["kind"],"render")
                    self.assertEqual(app.reader.location().position_fen,
                        "7K/8/k1P5/7p/8/8/8/8 w - - 0 1")
                    board=app.browser_command("books","book.open_position")
                    self.assertEqual(board["kind"],"delegated")
                    self.assertTrue(app.book_workflow.active)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                db.close()


if __name__=="__main__":
    unittest.main()
