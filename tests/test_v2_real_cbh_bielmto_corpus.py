from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from acs.acsdb import AcsDatabase
from acs.chessbase_decoder import ExternalChessBaseDecoderConfig, decode_chessbase_external
from acs.chessbase_library_import import ChessBaseLibraryImportService
from acs.game_identity import same_game_record, same_game_tree
from acs.gametree import PgnGame, VariationLine, parse_games
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.search_service import GameSearchQuery, GameSearchService


LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
PRODUCT_AUTHORITY = "575ec0088982d2f90adb47c040a5714d68186b0e"


def _environment_ready() -> bool:
    return all(
        os.environ.get(name)
        for name in (
            "LIBCBH_BRIDGE",
            "LIBCBH_NORMAL_DIR",
        )
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _family_hashes(directory: Path) -> dict[str, str]:
    files = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.name.startswith("BielMTO.")
    )
    if not files:
        raise AssertionError("pinned BielMTO family is missing")
    return {path.name: _sha256(path) for path in files}


def _decoder_config() -> ExternalChessBaseDecoderConfig:
    bridge = Path(os.environ["LIBCBH_BRIDGE"])
    return ExternalChessBaseDecoderConfig(
        bridge,
        expected_backend_commit=LIBCBH_COMMIT,
        timeout_seconds=300,
        library_directory=bridge.parent,
    )


def _stored_games(database: AcsDatabase, source_id: int) -> tuple[PgnGame, ...]:
    rows = database.conn.execute(
        "SELECT source_index, pgn_text FROM games WHERE source_id = ? ORDER BY source_index",
        (source_id,),
    ).fetchall()
    games: list[PgnGame] = []
    for expected_index, row in enumerate(rows):
        source_index = int(row["source_index"])
        if source_index != expected_index:
            raise AssertionError(
                f"non-contiguous source_index: expected {expected_index}, got {source_index}"
            )
        parsed = parse_games(str(row["pgn_text"]))
        if len(parsed) != 1:
            raise AssertionError(f"stored row {source_index} does not contain exactly one game")
        games.append(parsed[0])
    return tuple(games)


def _feature_profile(games: tuple[PgnGame, ...]) -> dict[str, int]:
    profile = {
        "games": len(games),
        "moves": 0,
        "variations": 0,
        "max_variation_depth": 0,
        "nags": 0,
        "comments": 0,
        "setup_fen_games": 0,
        "unicode_games": 0,
        "max_mainline_plies": 0,
    }

    def visit_line(line: VariationLine, depth: int) -> None:
        profile["max_variation_depth"] = max(profile["max_variation_depth"], depth)
        profile["comments"] += len(line.leading_comments) + len(line.trailing_comments)
        for move in line.moves:
            profile["moves"] += 1
            profile["nags"] += len(move.nags)
            profile["comments"] += len(move.comments_before) + len(move.comments_after)
            for variation in move.variations:
                profile["variations"] += 1
                visit_line(variation, depth + 1)

    for game in games:
        if game.tags.get("SetUp") == "1" or game.tags.get("FEN"):
            profile["setup_fen_games"] += 1
        text_values = list(game.tags.values())
        text_values.extend(comment.text for comment in game.line.leading_comments)
        text_values.extend(comment.text for comment in game.line.trailing_comments)
        if any(any(ord(character) > 127 for character in value) for value in text_values):
            profile["unicode_games"] += 1
        profile["max_mainline_plies"] = max(profile["max_mainline_plies"], len(game.line.moves))
        visit_line(game.line, 0)
    return profile


def _max_rss_kib() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if os.name == "posix" and value > 0:
        return value
    return None


@unittest.skipUnless(_environment_ready(), "pinned real libcbh BielMTO corpus is not configured")
class RealCbhBielMTOCorpusTests(unittest.TestCase):
    def test_exhaustive_bielmto_semantic_library_export_reopen_integrity(self) -> None:
        started = time.monotonic()
        fixture = Path(os.environ["LIBCBH_NORMAL_DIR"])
        source = fixture / "BielMTO.cbh"
        reference_path = fixture / "BielMTO.pgn"
        self.assertTrue(source.is_file())
        self.assertTrue(reference_path.is_file())

        reference = tuple(parse_games(reference_path.read_text(encoding="utf-8-sig")))
        self.assertGreater(len(reference), 10, "BielMTO must remain a non-trivial real corpus")
        reference_profile = _feature_profile(reference)
        print("CBH_BIELMTO_REFERENCE_PROFILE=" + json.dumps(reference_profile, sort_keys=True))

        before_hashes = _family_hashes(fixture)
        decoded = decode_chessbase_external(source, _decoder_config())
        decoded_profile = _feature_profile(tuple(decoded.games))

        decoded_tree_mismatches = [
            index
            for index, (actual, expected) in enumerate(zip(decoded.games, reference))
            if not same_game_tree(actual, expected)
        ]
        decoded_record_mismatches = [
            index
            for index, (actual, expected) in enumerate(zip(decoded.games, reference))
            if not same_game_record(actual, expected)
        ]

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path = root / "bielmto.acsdb"
            database = AcsDatabase(database_path)
            try:
                report = ChessBaseLibraryImportService(database, _decoder_config()).import_database(source)
                self.assertIsNotNone(report.library_result)
                assert report.library_result is not None
                source_id = report.library_result.source_id

                source_search = GameSearchService(database).search(
                    GameSearchQuery(source_name="BielMTO", limit=200)
                )
                self.assertGreater(len(source_search.items), 0, "real Library source search returned no games")
                self.assertTrue(all(item.source_id == source_id for item in source_search.items))

                stored = _stored_games(database, source_id)
                stored_tree_mismatches = [
                    index
                    for index, (actual, expected) in enumerate(zip(stored, reference))
                    if not same_game_tree(actual, expected)
                ]
                stored_record_mismatches = [
                    index
                    for index, (actual, expected) in enumerate(zip(stored, reference))
                    if not same_game_record(actual, expected)
                ]

                exported = root / "bielmto-export.pgn"
                export_fingerprint = save_pgn_atomic(exported, stored)
                reopened_export = tuple(open_pgn(exported).games)
                export_mismatches = [
                    index
                    for index, (before, after) in enumerate(zip(stored, reopened_export))
                    if not same_game_record(before, after)
                ]

                quick_check = str(database.conn.execute("PRAGMA quick_check").fetchone()[0])
                foreign_key_errors = database.conn.execute("PRAGMA foreign_key_check").fetchall()
                database_game_count = int(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
                database_source_count = int(database.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
            finally:
                database.close()

            reopened_database = AcsDatabase(database_path)
            try:
                reopened_quick_check = str(reopened_database.conn.execute("PRAGMA quick_check").fetchone()[0])
                reopened_foreign_key_errors = reopened_database.conn.execute("PRAGMA foreign_key_check").fetchall()
                reopened_game_count = int(
                    reopened_database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
                )
                reopened_stored = _stored_games(reopened_database, source_id)
                reopened_tree_mismatches = [
                    index
                    for index, (actual, expected) in enumerate(zip(reopened_stored, reference))
                    if not same_game_tree(actual, expected)
                ]
            finally:
                reopened_database.close()

            database_bytes = database_path.stat().st_size

        after_hashes = _family_hashes(fixture)
        elapsed_seconds = round(time.monotonic() - started, 3)
        evidence = {
            "product_authority": PRODUCT_AUTHORITY,
            "libcbh_commit": LIBCBH_COMMIT,
            "source_sha256": _sha256(source),
            "reference_pgn_sha256": _sha256(reference_path),
            "family_file_count": len(before_hashes),
            "reference_games": len(reference),
            "decoded_games": len(decoded.games),
            "decode_warning_count": len(decoded.warnings),
            "warning_codes": sorted({warning.code for warning in decoded.warnings}),
            "reference_profile": reference_profile,
            "decoded_profile": decoded_profile,
            "decoded_tree_mismatch_count": len(decoded_tree_mismatches),
            "decoded_tree_mismatch_sample": decoded_tree_mismatches[:20],
            "decoded_record_mismatch_count": len(decoded_record_mismatches),
            "decoded_record_mismatch_sample": decoded_record_mismatches[:20],
            "imported_games": report.imported_game_count,
            "import_warning_count": report.warning_count,
            "stored_games": len(stored),
            "stored_tree_mismatch_count": len(stored_tree_mismatches),
            "stored_tree_mismatch_sample": stored_tree_mismatches[:20],
            "stored_record_mismatch_count": len(stored_record_mismatches),
            "stored_record_mismatch_sample": stored_record_mismatches[:20],
            "library_source_search_results": len(source_search.items),
            "exported_games": len(reopened_export),
            "export_record_mismatch_count": len(export_mismatches),
            "export_record_mismatch_sample": export_mismatches[:20],
            "export_sha256": export_fingerprint.sha256,
            "quick_check": quick_check,
            "foreign_key_errors": len(foreign_key_errors),
            "database_games": database_game_count,
            "database_sources": database_source_count,
            "reopened_quick_check": reopened_quick_check,
            "reopened_foreign_key_errors": len(reopened_foreign_key_errors),
            "reopened_games": reopened_game_count,
            "reopened_stored_games": len(reopened_stored),
            "reopened_tree_mismatch_count": len(reopened_tree_mismatches),
            "reopened_tree_mismatch_sample": reopened_tree_mismatches[:20],
            "database_bytes": database_bytes,
            "elapsed_seconds": elapsed_seconds,
            "max_rss_kib": _max_rss_kib(),
            "source_immutable": after_hashes == before_hashes,
        }
        print("CBH_BIELMTO_EVIDENCE=" + json.dumps(evidence, sort_keys=True, ensure_ascii=False))

        self.assertEqual(len(decoded.games), len(reference), "real CBH decode count differs from independent PGN")
        self.assertEqual(len(decoded.warnings), 0, "real CBH decode emitted loss warnings")
        self.assertEqual(decoded_tree_mismatches, [], "decoded GameTree semantics differ from independent PGN")
        self.assertEqual(decoded_record_mismatches, [], "decoded record semantics differ from independent PGN")
        self.assertEqual(report.decoded_game_count, len(reference))
        self.assertEqual(report.imported_game_count, len(reference))
        self.assertEqual(report.warning_count, 0)
        self.assertEqual(len(stored), len(reference))
        self.assertEqual(stored_tree_mismatches, [])
        self.assertEqual(stored_record_mismatches, [])
        self.assertEqual(len(reopened_export), len(stored))
        self.assertEqual(export_mismatches, [])
        self.assertEqual(quick_check, "ok")
        self.assertEqual(foreign_key_errors, [])
        self.assertEqual(database_game_count, len(reference))
        self.assertEqual(database_source_count, 1)
        self.assertEqual(reopened_quick_check, "ok")
        self.assertEqual(reopened_foreign_key_errors, [])
        self.assertEqual(reopened_game_count, len(reference))
        self.assertEqual(len(reopened_stored), len(reference))
        self.assertEqual(reopened_tree_mismatches, [])
        self.assertEqual(after_hashes, before_hashes, "real BielMTO source family mutated")


if __name__ == "__main__":
    unittest.main()
