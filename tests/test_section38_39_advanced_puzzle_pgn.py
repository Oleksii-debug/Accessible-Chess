"""20 original-source high-level Lichess puzzles -> PGN/FEN/SAN -> ACSDB restart."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.library_import_service import LibraryImportService
from acs.library_source_service import LibrarySourceCatalogService
from acs.pgn_roundtrip import parse_pgn_text
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.position_editor import PositionState
from tools.revised_section38_39_advanced_puzzle_pgn import (
    AdvancedPuzzlePgnError, build_advanced_pgn,
)


class AdvancedPuzzlePgnWindowsLibraryTests(unittest.TestCase):
    def test_original_20_genuine_expert_positions_survive_pgn_and_library_restart(self):
        original, receipt = build_advanced_pgn()
        self.assertEqual(receipt["puzzles"], 20)
        self.assertEqual(receipt["source_count"], 2)
        self.assertEqual(len(receipt["source_sha256"]), 2)
        self.assertGreaterEqual(receipt["min_puzzle_rating_lichess_not_fide"], 2200)
        self.assertGreaterEqual(receipt["max_puzzle_rating_lichess_not_fide"], 3000)
        self.assertIs(receipt["source_original_game_pgn"], False)
        self.assertIs(receipt["contains_copyrighted_external_books"], False)
        self.assertEqual(hashlib.sha256(original).hexdigest(), receipt["pgn_sha256"])
        self.assertEqual(len(original), receipt["pgn_bytes"])
        parsed = parse_pgn_text(original.decode("utf-8"), strict=True)
        self.assertEqual(len(parsed), 20)
        self.assertEqual(len({game.tags["PuzzleId"] for game in parsed}), 20)
        self.assertTrue(all(game.tags["SetUp"] == "1" for game in parsed))
        self.assertTrue(all(game.tags["PuzzleRatingSystem"] == "Lichess-puzzle-NOT-FIDE"
                            for game in parsed))
        self.assertTrue(all(len(game.line.moves) > 0 for game in parsed))
        for game in parsed:
            self.assertEqual(
                PositionState.from_fen(game.tags["FEN"]).to_fen(),
                game.tags["FEN"],
            )

        with tempfile.TemporaryDirectory(prefix="acs-advanced-pgn-restart-") as temp:
            directory = Path(temp)
            path = directory / "actual-master-positions.pgn"
            path.write_bytes(original)
            opened = open_pgn(path)
            self.assertEqual(len(opened.games), 20)
            output = directory / "canonical-roundtrip.pgn"
            save_pgn_atomic(output, opened.games)
            reopened = open_pgn(output)
            self.assertEqual(len(reopened.games), 20)
            for original_game, reopened_game in zip(opened.games, reopened.games, strict=True):
                self.assertEqual(original_game.tags["PuzzleId"], reopened_game.tags["PuzzleId"])
                self.assertEqual(original_game.tags["FEN"], reopened_game.tags["FEN"])
                self.assertEqual(
                    [move.san for move in original_game.line.moves],
                    [move.san for move in reopened_game.line.moves],
                )

            database_path = directory / "master-only.acsdb"
            with AcsDatabase(database_path) as database:
                first = LibraryImportService(database).import_games(
                    opened.games,
                    source_name="20 genuine Lichess high-difficulty puzzles",
                    source_format="pgn",
                    source_sha256=receipt["pgn_sha256"],
                )
                self.assertEqual(first.game_count, 20)
                database.verify_integrity()
            with AcsDatabase(database_path) as database:
                query = LibrarySourceCatalogService(database)
                persisted = query.get_source(first.source_id)
                self.assertEqual(persisted.game_count, 20)
                self.assertEqual(persisted.source_sha256, receipt["pgn_sha256"])
                results = query.source_games(first.source_id, limit=20)
                self.assertEqual(len(results.items), 20)
                self.assertFalse(results.has_more)
                second = LibraryImportService(database).import_games(
                    opened.games,
                    source_name="20 genuine Lichess high-difficulty puzzles",
                    source_format="pgn",
                    source_sha256=receipt["pgn_sha256"],
                )
                self.assertTrue(second.reused)
                self.assertEqual(second.source_id, first.source_id)
                database.verify_integrity()

    def test_section39_matrix_separates_genuine_original_and_advanced_derived(self):
        from tools.section39_real_format_qualification import build_report
        report = build_report()
        self.assertEqual(report["format_count"], 16)
        evidence = report["evidence"]["advanced_master_derived_qa"]
        self.assertEqual(evidence["qualified_puzzle_positions"], 20)
        self.assertEqual(evidence["source_kind"],
                         "CANONICAL_DERIVED_FROM_CHECKED_IN_CC0_PUZZLES")
        self.assertFalse(evidence["original_publisher_pgn_qualified"])
        self.assertFalse(evidence["external_author_original_full_corpus_sha_pass"])
        self.assertFalse(evidence["terminal_section_done"])
        self.assertFalse(report["terminal_done"])
        self.assertGreaterEqual(evidence["min_puzzle_rating"], 2200)
        self.assertGreaterEqual(evidence["max_puzzle_rating"], 3000)
        self.assertEqual(len(evidence["pgn_sha256"]), 64)

    def test_invalid_chess_moves_and_fake_rating_claims_fail_closed(self):
        from unittest.mock import patch
        from tools import revised_section38_39_advanced_puzzle_pgn as exporter
        valid, valid_manifest = build_advanced_pgn()
        self.assertEqual(len(valid_manifest["source_ids"]), 2)
        self.assertGreater(len(valid), 1000)
        authentic = exporter.build_advanced_offline_material

        def corrupt_source():
            book, tasks = authentic()
            copied = [dict(item) for item in tasks]
            copied[0]["full_solution_uci"] = ["a1a1"]
            return book, tuple(copied)

        with patch.object(exporter, "build_advanced_offline_material",
                          side_effect=corrupt_source):
            with self.assertRaises(AdvancedPuzzlePgnError):
                build_advanced_pgn()

        def degrade_rating():
            book, tasks = authentic()
            copied = [dict(item) for item in tasks]
            copied[0]["puzzle_rating_lichess_not_fide"] = 400
            return book, tuple(copied)

        with patch.object(exporter, "build_advanced_offline_material",
                          side_effect=degrade_rating):
            with self.assertRaises(AdvancedPuzzlePgnError):
                build_advanced_pgn()


if __name__ == "__main__":
    unittest.main()
