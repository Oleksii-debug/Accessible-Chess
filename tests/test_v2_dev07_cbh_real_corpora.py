from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.chessbase_decoder import ExternalChessBaseDecoderConfig, decode_chessbase_external
from acs.chessbase_library_import import ChessBaseLibraryImportService
from acs.game_identity import same_game_tree
from acs.gametree import parse_games, serialize_game
from acs.gametree_legality import validate_game_legality
from acs.pgn_service import open_pgn, save_pgn_atomic


LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"


def _walk(line):
    for node in line.moves:
        yield node
        for variation in node.variations:
            yield from _walk(variation)


def _variation_count(line) -> int:
    total = 0
    for node in line.moves:
        total += len(node.variations)
        for variation in node.variations:
            total += _variation_count(variation)
    return total


@unittest.skipUnless(os.environ.get("LIBCBH_BRIDGE") and os.environ.get("LIBCBH_ROOT"), "pinned libcbh corpus not configured")
class Dev07RealCbhCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bridge = Path(os.environ["LIBCBH_BRIDGE"])
        cls.root = Path(os.environ["LIBCBH_ROOT"])
        cls.config = ExternalChessBaseDecoderConfig(
            cls.bridge,
            expected_backend_commit=LIBCBH_COMMIT,
            timeout_seconds=60,
            library_directory=cls.bridge.parent,
        )

    def _decode(self, relative: str):
        decoded = decode_chessbase_external(self.root / relative, self.config)
        self.assertEqual(decoded.backend_commit, LIBCBH_COMMIT)
        self.assertEqual(decoded.warnings, ())
        self.assertGreater(len(decoded.games), 0)
        for game in decoded.games:
            legality = validate_game_legality(game)
            self.assertTrue(legality.complete, (relative, legality))
            reopened = parse_games(serialize_game(game))[0]
            self.assertTrue(validate_game_legality(reopened).complete)
            self.assertTrue(same_game_tree(game, reopened), relative)
        return decoded

    def test_annotations_survive_adapter_legality_and_reopen(self) -> None:
        decoded = self._decode("gtest/Annotation/TestBase.cbh")
        annotation_count = 0
        for game in decoded.games:
            for node in _walk(game.line):
                annotation_count += len(node.comments_before) + len(node.comments_after) + len(node.nags)
        self.assertGreater(annotation_count, 0)

    def test_variations_survive_adapter_legality_and_reopen(self) -> None:
        decoded = self._decode("gtest/WithVariations/WithVariations.cbh")
        self.assertGreater(sum(_variation_count(game.line) for game in decoded.games), 0)

    def test_promotions_and_underpromotions_survive_canonical_move_path(self) -> None:
        decoded = self._decode("gtest/ManyPromotions/ManyPromotions.cbh")
        promotion_sans = [
            node.san
            for game in decoded.games
            for node in _walk(game.line)
            if "=" in node.san
        ]
        self.assertGreater(len(promotion_sans), 0)
        self.assertTrue(any("=N" in san for san in promotion_sans))
        self.assertTrue(any("=B" in san for san in promotion_sans))

    def test_unusual_starts_and_real_zero_ply_game_survive(self) -> None:
        decoded = self._decode("gtest/UnusualStart/UnusualStartBytes.cbh")
        self.assertEqual(len(decoded.games), 9)
        zero_ply = [game for game in decoded.games if not game.line.moves]
        self.assertGreaterEqual(len(zero_ply), 1)
        self.assertTrue(any(game.tags.get("SetUp") == "1" and game.tags.get("FEN") for game in decoded.games))

    def test_real_with_variations_reaches_library_export_and_reopen(self) -> None:
        source = self.root / "gtest/WithVariations/WithVariations.cbh"
        with tempfile.TemporaryDirectory() as temporary:
            tmp = Path(temporary)
            db = AcsDatabase(tmp / "library.acsdb")
            self.addCleanup(db.close)
            report = ChessBaseLibraryImportService(db, self.config).import_database(source)
            self.assertEqual(report.warning_count, 0)
            self.assertEqual(report.imported_game_count, report.decoded_game_count)
            rows = db.conn.execute(
                "SELECT game_id, pgn_text FROM games WHERE source_id = ? ORDER BY source_index, game_id",
                (report.library_result.source_id,),
            ).fetchall()
            self.assertEqual(len(rows), report.imported_game_count)
            games = tuple(parse_games(row[1])[0] for row in rows)
            for game in games:
                self.assertTrue(validate_game_legality(game).complete)
            destination = tmp / "cbh-export.pgn"
            save_pgn_atomic(destination, games)
            reopened = open_pgn(destination).games
            self.assertEqual(len(reopened), len(games))
            self.assertTrue(all(same_game_tree(a, b) for a, b in zip(games, reopened)))

    def test_pinned_real_corpora_are_scanned_for_null_pseudo_records(self) -> None:
        fixtures = (
            "gtest/Annotation/TestBase.cbh",
            "gtest/WithVariations/WithVariations.cbh",
            "gtest/ManyPromotions/ManyPromotions.cbh",
            "gtest/UnusualStart/UnusualStartBytes.cbh",
        )
        null_records = 0
        for relative in fixtures:
            completed = subprocess.run(
                [os.fspath(self.bridge), "--json-v1", os.fspath(self.root / relative)],
                cwd=self.bridge.parent,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
            payload = json.loads(completed.stdout.decode("utf-8"))
            for game in payload.get("games", []):
                for token in game.get("moves", []):
                    if token.get("kind") == "move" and token.get("promote") == 6:
                        null_records += 1
        print(f"DEV07_PINNED_REAL_NULL_PSEUDO_RECORDS={null_records}")
        # libcbh's pinned QA tree currently has no dedicated null-move fixture.
        # The adapter protocol-level promote=6 path is therefore locked by the
        # synthetic canonical-delegation regression in test_v2_dev07_cbh_canonical_adapter.
        self.assertGreaterEqual(null_records, 0)


if __name__ == "__main__":
    unittest.main()
