from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.chessbase_decoder import ExternalChessBaseDecoderConfig, decode_chessbase_external
from acs.chessbase_library_import import ChessBaseLibraryImportService
from acs.game_identity import same_game_record, same_game_tree
from acs.gametree import PgnGame, parse_games
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.search_service import GameSearchQuery, GameSearchService


LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
PRODUCT_AUTHORITY = "575ec0088982d2f90adb47c040a5714d68186b0e"
_CORE_TAGS = ("Event", "Site", "Date", "Round", "Result")


def _environment_ready() -> bool:
    return all(
        os.environ.get(name)
        for name in (
            "LIBCBH_BRIDGE",
            "LIBCBH_UNUSUAL_DIR",
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
        if path.is_file() and path.name.startswith("UnusualStartBytes.")
    )
    if not files:
        raise AssertionError("pinned UnusualStartBytes family is missing")
    return {path.name: _sha256(path) for path in files}


def _normalized_person(value: str | None) -> str:
    if not value:
        return ""
    text = " ".join(value.split())
    if "," not in text:
        return text.casefold()
    last, first = text.split(",", 1)
    return " ".join((first.strip(), last.strip())).casefold()


def _assert_core_metadata(test: unittest.TestCase, actual: PgnGame, expected: PgnGame) -> None:
    for tag in _CORE_TAGS:
        test.assertEqual(actual.tags.get(tag), expected.tags.get(tag), tag)
    test.assertEqual(_normalized_person(actual.tags.get("White")), _normalized_person(expected.tags.get("White")), "White")
    test.assertEqual(_normalized_person(actual.tags.get("Black")), _normalized_person(expected.tags.get("Black")), "Black")


def _decoder_config() -> ExternalChessBaseDecoderConfig:
    bridge = Path(os.environ["LIBCBH_BRIDGE"])
    return ExternalChessBaseDecoderConfig(
        bridge,
        expected_backend_commit=LIBCBH_COMMIT,
        timeout_seconds=120,
        library_directory=bridge.parent,
    )


def _stored_games(database: AcsDatabase, source_id: int) -> tuple[PgnGame, ...]:
    service = GameSearchService(database)
    page = service.search(GameSearchQuery(source_id=source_id, limit=20))
    ordered = sorted(page.items, key=lambda item: item.source_index)
    games: list[PgnGame] = []
    for item in ordered:
        row = database.get_game(item.game_id)
        if row is None:
            raise AssertionError(f"missing stored game id {item.game_id}")
        games.append(parse_games(str(row["pgn_text"]))[0])
    return tuple(games)


@unittest.skipUnless(_environment_ready(), "pinned real libcbh unusual-start corpus is not configured")
class RealCbhUnusualStartTests(unittest.TestCase):
    def test_nine_real_unusual_start_byte_games_match_reference_end_to_end(self) -> None:
        fixture = Path(os.environ["LIBCBH_UNUSUAL_DIR"])
        source = fixture / "UnusualStartBytes.cbh"
        reference_path = fixture / "UnusualStart.pgn"
        self.assertTrue(source.is_file())
        self.assertTrue(reference_path.is_file())

        reference = tuple(parse_games(reference_path.read_text(encoding="utf-8-sig")))
        self.assertEqual(len(reference), 9)
        self.assertTrue(any(len(game.line.moves) == 0 for game in reference), "reference must retain the zero-ply game")

        before_hashes = _family_hashes(fixture)
        decoded = decode_chessbase_external(source, _decoder_config())
        self.assertEqual(len(decoded.games), 9)
        self.assertEqual(len(decoded.warnings), 0)

        metadata_differences: list[dict[str, object]] = []
        for index, (actual, expected) in enumerate(zip(decoded.games, reference)):
            with self.subTest(game=index):
                _assert_core_metadata(self, actual, expected)
                self.assertTrue(same_game_tree(actual, expected), f"GameTree mismatch at real game {index}")
                for tag in ("White", "Black"):
                    if actual.tags.get(tag) != expected.tags.get(tag):
                        metadata_differences.append(
                            {
                                "game": index,
                                "tag": tag,
                                "actual": actual.tags.get(tag, ""),
                                "reference": expected.tags.get(tag, ""),
                            }
                        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path = root / "unusual-start.acsdb"
            database = AcsDatabase(database_path)
            try:
                report = ChessBaseLibraryImportService(database, _decoder_config()).import_database(source)
                self.assertEqual(report.decoded_game_count, 9)
                self.assertEqual(report.imported_game_count, 9)
                self.assertEqual(report.warning_count, 0)
                self.assertEqual(report.source_format, "cbh")

                source_page = GameSearchService(database).search(
                    GameSearchQuery(source_id=report.library_result.source_id, limit=20)
                )
                self.assertEqual(len(source_page.items), 9)
                self.assertEqual([item.source_index for item in source_page.items], list(range(9)))

                player_page = GameSearchService(database).search(
                    GameSearchQuery(player="Suchin", source_name="UnusualStartBytes", limit=20)
                )
                self.assertGreaterEqual(len(player_page.items), 2)

                stored = _stored_games(database, report.library_result.source_id)
                self.assertEqual(len(stored), 9)
                for index, (actual, expected) in enumerate(zip(stored, reference)):
                    with self.subTest(stored_game=index):
                        _assert_core_metadata(self, actual, expected)
                        self.assertTrue(same_game_tree(actual, expected))

                exported = root / "unusual-start-export.pgn"
                export_fingerprint = save_pgn_atomic(exported, stored)
                reopened_export = open_pgn(exported).games
                self.assertEqual(len(reopened_export), 9)
                for index, (before, after) in enumerate(zip(stored, reopened_export)):
                    with self.subTest(export_game=index):
                        self.assertTrue(same_game_record(before, after))

                self.assertEqual(database.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(database.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                game_count = int(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
                source_count = int(database.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
                self.assertEqual(game_count, 9)
                self.assertEqual(source_count, 1)
            finally:
                database.close()

            reopened_database = AcsDatabase(database_path)
            try:
                self.assertEqual(reopened_database.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(reopened_database.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(reopened_database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 9)
                reopened_stored = _stored_games(reopened_database, report.library_result.source_id)
                self.assertEqual(len(reopened_stored), 9)
                for index, (actual, expected) in enumerate(zip(reopened_stored, reference)):
                    with self.subTest(reopened_db_game=index):
                        self.assertTrue(same_game_tree(actual, expected))
            finally:
                reopened_database.close()

        after_hashes = _family_hashes(fixture)
        self.assertEqual(after_hashes, before_hashes, "real unusual-start source family mutated")

        evidence = {
            "product_authority": PRODUCT_AUTHORITY,
            "libcbh_commit": LIBCBH_COMMIT,
            "source_sha256": _sha256(source),
            "reference_pgn_sha256": _sha256(reference_path),
            "games": 9,
            "zero_ply_games": sum(1 for game in reference if len(game.line.moves) == 0),
            "decode_warnings": len(decoded.warnings),
            "metadata_name_order_differences": metadata_differences,
            "all_decoded_trees_match": True,
            "library_search": "PASS",
            "stored_trees_match": True,
            "export_reopen": "PASS",
            "export_sha256": export_fingerprint.sha256,
            "acsdb_reopen": "PASS",
            "source_immutable": True,
        }
        print("CBH_UNUSUAL_START_EVIDENCE=" + json.dumps(evidence, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
