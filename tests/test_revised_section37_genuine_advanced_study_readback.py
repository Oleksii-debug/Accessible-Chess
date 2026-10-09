"""Real 1921 historical Reti authored study is not a Lichess game or fake study."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.pgn_roundtrip import parse_pgn_text
from acs.library_import_service import LibraryImportService
from acs.library_source_service import LibrarySourceCatalogService

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "tests/real_corpus/advanced_training/reti_1921_historical_study_bilingual.pgn"
FEN = "7K/8/k1P5/7p/8/8/8/8 w - - 0 1"


class HistoricAdvancedStudyTests(unittest.TestCase):
    def test_original_reti_study_not_fabricated_tournament_game_and_bilingual(self):
        content = STUDY.read_text(encoding="utf-8")
        self.assertIn('FEN "' + FEN + '"', content)
        self.assertIn('SetUp "1"', content)
        self.assertIn("Richard Reti", content)
        self.assertIn('1/2-1/2', content)
        self.assertIn("EN:", content)
        self.assertIn("UK:", content)
        self.assertIn("1921", content)
        self.assertIn("ARVES", content)
        self.assertNotIn("Lichess rating", content)
        games = parse_pgn_text(content, strict=False)
        self.assertEqual(len(games), 1)
        self.assertEqual(len(games[0].line.moves), 11)

    def test_true_historical_study_pgn_survives_real_canonical_library_restart(self):
        content = STUDY.read_bytes()
        games = parse_pgn_text(content.decode("utf-8"), strict=False)
        self.assertEqual(len(games), 1)
        games[0].source_index = 0
        digest = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory(prefix="section37-reti-original-") as temp:
            database_path = Path(temp) / "study-source.acsdb"
            with AcsDatabase(database_path) as db:
                inserted = LibraryImportService(db).import_games(
                    games, source_name="Reti original 1921 composed study with bilingual original annotations",
                    source_format="pgn", source_sha256=digest,
                )
                self.assertEqual(inserted.game_count, 1)
                self.assertFalse(inserted.reused)
                db.verify_integrity()
            with AcsDatabase(database_path) as db:
                source = LibrarySourceCatalogService(db).get_source(inserted.source_id)
                self.assertIsNotNone(source)
                self.assertEqual(source.source_sha256, digest)
                page = LibrarySourceCatalogService(db).source_games(inserted.source_id, limit=5)
                self.assertEqual(len(page.items), 1)
                repeated = LibraryImportService(db).import_games(
                    games, source_name="Original Reti study same bytes", source_format="PGN",
                    source_sha256=digest.upper(),
                )
                self.assertTrue(repeated.reused)
                db.verify_integrity()


if __name__ == "__main__":
    unittest.main()
