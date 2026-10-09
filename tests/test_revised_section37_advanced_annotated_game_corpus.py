"""Four genuine above-2200 Lichess games with original CC0 PGN/RAV/analysis."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.lawful_corpus_registry import load_catalog, verified_local_source
from acs.library_import_service import LibraryImportService
from acs.library_source_service import LibrarySourceCatalogService
from acs.pgn_roundtrip import parse_pgn_text

ROOT = Path(__file__).resolve().parents[1]
ID = "lichess_cc0_high_level_4_original_annotated_games"


class AuthenticHighLevelPGNTests(unittest.TestCase):
    def _real_source(self):
        sources = {x["id"]: x for x in load_catalog()}
        record = sources[ID]
        self.assertEqual(record["license"].split(" ")[0], "CC0-1.0")
        self.assertEqual(record["redistribution"], "permitted")
        self.assertEqual(record["acquisition"], "VENDORED_SOURCE_VERIFIED")
        pg = ROOT / record["local_source"]
        verified_local_source(pg, record)
        raw = pg.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), record["sha256"])
        manifest = json.loads((ROOT / record["source_manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["game_count"], 4)
        self.assertTrue(manifest["selected_from_original_100"])
        self.assertTrue(manifest["player_rating_is_not_FIDE_ELO"])
        self.assertTrue(manifest["not_gm_title_claim"])
        self.assertEqual(manifest["original_game_pgn_source_sha256"], record["sha256"])
        self.assertEqual(manifest["source_git_blob"], "d7b86f83c1a355fa511420a36dbdc656a3cc6fef")
        self.assertTrue(all(
            g["original_online_white_rating"] >= 2200
            and g["original_online_black_rating"] >= 2200
            for g in manifest["game_source_ids"]
        ))
        return record, raw, manifest

    def test_original_cc0_full_game_annotations_preserved_in_real_source(self):
        record, raw, manifest = self._real_source()
        text = raw.decode("utf-8", errors="strict")
        self.assertEqual(text.count('[Event "'), 4)
        self.assertGreaterEqual(text.count("[%eval "), 60)
        self.assertGreaterEqual(text.count("("), 30)
        self.assertGreaterEqual(text.count("{"), 50)
        self.assertTrue(all(
            item["contains_original_engine_annotations"]
            for item in manifest["game_source_ids"]
        ))
        parsed = parse_pgn_text(text, strict=False)
        self.assertEqual(len(parsed), 4)
        self.assertTrue(all(game.line.moves for game in parsed))
        self.assertTrue(all(
            item["source_game_url"].split("#")[0].replace("/black", "").replace("/white", "") in text
            for item in manifest["game_source_ids"]
        ))

    def test_real_above_first_category_game_analysis_imports_to_canonical_library_and_reopens(self):
        record, raw, manifest = self._real_source()
        games = parse_pgn_text(raw.decode("utf-8"), strict=False)
        self.assertEqual(len(games), 4)
        for number, game in enumerate(games):
            game.source_index = number
        with tempfile.TemporaryDirectory(prefix="acs-high-level-annotated-pgn-") as directory:
            path = Path(directory) / "actual-high-level-chess.acsdb"
            with AcsDatabase(path) as db:
                imported = LibraryImportService(db).import_games(
                    games,
                    source_name="CC0 Lichess actual 2200+ online games, original PGN annotations",
                    source_format="pgn",
                    source_sha256=record["sha256"],
                )
                self.assertEqual(imported.game_count, 4)
                self.assertFalse(imported.reused)
                db.verify_integrity()
            with AcsDatabase(path) as db:
                source = LibrarySourceCatalogService(db).get_source(imported.source_id)
                self.assertIsNotNone(source)
                self.assertEqual(source.game_count, 4)
                self.assertEqual(source.source_sha256, record["sha256"])
                page = LibrarySourceCatalogService(db).source_games(imported.source_id, limit=8)
                self.assertEqual(tuple(x.source_index for x in page.items), tuple(range(4)))
                self.assertFalse(page.has_more)
                replay = LibraryImportService(db).import_games(
                    games,
                    source_name="same authentic CC0 high-level games",
                    source_format="PGN",
                    source_sha256=record["sha256"].upper(),
                )
                self.assertTrue(replay.reused)
                db.verify_integrity()


if __name__ == "__main__":
    unittest.main()
