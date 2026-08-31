from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.chessbase_decoder import ExternalChessBaseDecoderConfig, decode_chessbase_external
from acs.chessbase_integrity import capture_integrity_snapshot, verify_integrity_snapshot
from acs.chessbase_library_import import ChessBaseLibraryImportService
from acs.game_identity import same_game_record, same_game_tree
from acs.gametree import Comment, PgnGame, VariationLine, parse_games
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.search_service import GameSearchItem, GameSearchQuery, GameSearchService


LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
_SEARCH_PAGE_LIMIT = 200


def _ready() -> bool:
    return bool(os.environ.get("LIBCBH_BRIDGE") and os.environ.get("LIBCBH_BIEL_DIR"))


def _config() -> ExternalChessBaseDecoderConfig:
    bridge = Path(os.environ["LIBCBH_BRIDGE"])
    return ExternalChessBaseDecoderConfig(
        bridge,
        expected_backend_commit=LIBCBH_COMMIT,
        timeout_seconds=180,
        library_directory=bridge.parent,
    )


def _read_reference(path: Path) -> tuple[PgnGame, ...]:
    return tuple(parse_games(path.read_text(encoding="utf-8-sig")))


def _walk_lines(line: VariationLine):
    yield line
    for move in line.moves:
        for variation in move.variations:
            yield from _walk_lines(variation)


def _feature_profile(games: tuple[PgnGame, ...]) -> dict[str, int]:
    variations = 0
    nags = 0
    comments = 0
    plies = 0
    max_mainline_plies = 0
    for game in games:
        max_mainline_plies = max(max_mainline_plies, len(game.line.moves))
        for line in _walk_lines(game.line):
            comments += len(line.leading_comments) + len(line.trailing_comments)
            plies += len(line.moves)
            for move in line.moves:
                variations += len(move.variations)
                nags += len(move.nags)
                comments += len(move.comments_before) + len(move.comments_after)
    return {
        "games": len(games),
        "plies": plies,
        "variations": variations,
        "nags": nags,
        "comments": comments,
        "max_mainline_plies": max_mainline_plies,
    }


def _source_items(database: AcsDatabase, source_id: int) -> tuple[tuple[GameSearchItem, ...], int]:
    service = GameSearchService(database)
    items: list[GameSearchItem] = []
    after_game_id: int | None = None
    page_count = 0
    while True:
        page = service.search(
            GameSearchQuery(
                source_id=source_id,
                after_game_id=after_game_id,
                limit=_SEARCH_PAGE_LIMIT,
            )
        )
        page_count += 1
        if page.items:
            if items and page.items[0].game_id <= items[-1].game_id:
                raise AssertionError("Biel full-family keyset paging did not advance")
            items.extend(page.items)
        if not page.has_more:
            if page.next_after_game_id is not None:
                raise AssertionError("terminal Biel Search page published a cursor")
            break
        next_cursor = page.next_after_game_id
        if next_cursor is None:
            raise AssertionError("non-terminal Biel Search page omitted its cursor")
        if after_game_id is not None and next_cursor <= after_game_id:
            raise AssertionError("Biel Search cursor did not advance")
        after_game_id = next_cursor
    return tuple(items), page_count


def _stored_games(database: AcsDatabase, items: tuple[GameSearchItem, ...]) -> tuple[PgnGame, ...]:
    ordered = sorted(items, key=lambda item: item.source_index)
    games: list[PgnGame] = []
    for item in ordered:
        row = database.get_game(item.game_id)
        if row is None:
            raise AssertionError(f"missing stored Biel game {item.game_id}")
        parsed = parse_games(row["pgn_text"])
        if len(parsed) != 1:
            raise AssertionError(f"stored Biel game {item.game_id} is not one canonical record")
        games.append(parsed[0])
    return tuple(games)


@unittest.skipUnless(_ready(), "pinned real libcbh Biel full-family corpus is not configured")
class RealCbhBielFullFamilyTests(unittest.TestCase):
    def test_all_games_match_reference_and_survive_library_export_reopen(self) -> None:
        fixture = Path(os.environ["LIBCBH_BIEL_DIR"])
        source = fixture / "BielMTO.cbh"
        reference_path = fixture / "BielMTO.pgn"
        self.assertTrue(source.is_file())
        self.assertTrue(reference_path.is_file())

        reference = _read_reference(reference_path)
        self.assertGreaterEqual(len(reference), 100)
        reference_sha256 = hashlib.sha256(reference_path.read_bytes()).hexdigest()
        reference_profile = _feature_profile(reference)

        before = capture_integrity_snapshot(source)
        self.assertGreaterEqual(len(before.files), 2)
        primary = next(item for item in before.files if item.role == "primary_source")
        component_extensions = sorted(item.extension for item in before.files if item.role != "primary_source")

        decoded = decode_chessbase_external(source, _config())
        self.assertFalse(decoded.warnings)
        self.assertEqual(len(decoded.games), len(reference))
        decoded_profile = _feature_profile(decoded.games)
        self.assertEqual(decoded_profile, reference_profile)

        for index, (actual, expected) in enumerate(zip(decoded.games, reference)):
            with self.subTest(game=index):
                self.assertTrue(
                    same_game_tree(actual, expected),
                    f"real Biel GameTree mismatch at source index {index}",
                )

        verify_integrity_snapshot(before)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path = root / "biel-full-family.acsdb"
            database = AcsDatabase(database_path)
            try:
                report = ChessBaseLibraryImportService(database, _config()).import_database(source)
                self.assertEqual(report.source_format, "cbh")
                self.assertEqual(report.source_sha256, primary.sha256)
                self.assertEqual(report.decoded_game_count, len(reference))
                self.assertEqual(report.imported_game_count, len(reference))
                self.assertEqual(report.warning_count, 0)

                items, search_page_count = _source_items(database, report.library_result.source_id)
                self.assertEqual(len(items), len(reference))
                self.assertEqual(
                    [item.source_index for item in sorted(items, key=lambda item: item.source_index)],
                    list(range(len(reference))),
                )

                stored = _stored_games(database, items)
                self.assertEqual(len(stored), len(reference))
                for index, (stored_game, expected) in enumerate(zip(stored, reference)):
                    with self.subTest(stored_game=index):
                        self.assertTrue(
                            same_game_tree(stored_game, expected),
                            f"stored Biel GameTree mismatch at source index {index}",
                        )

                exported = root / "biel-full-family-export.pgn"
                save_pgn_atomic(exported, stored)
                reopened = open_pgn(exported).games
                self.assertEqual(len(reopened), len(stored))
                for index, (before_export, after_export) in enumerate(zip(stored, reopened)):
                    with self.subTest(exported_game=index):
                        self.assertTrue(
                            same_game_record(before_export, after_export),
                            f"Biel export/reopen record mismatch at source index {index}",
                        )

                self.assertEqual(database.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(database.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                database_bytes = database_path.stat().st_size
                exported_bytes = exported.stat().st_size
                source_id = report.library_result.source_id
            finally:
                database.close()

            reopened_database = AcsDatabase(database_path)
            try:
                self.assertEqual(reopened_database.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(reopened_database.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(
                    reopened_database.conn.execute("SELECT COUNT(*) FROM games WHERE source_id = ?", (source_id,)).fetchone()[0],
                    len(reference),
                )
            finally:
                reopened_database.close()

        after = verify_integrity_snapshot(before)
        self.assertEqual(after, before)

        print(
            "CBH_BIEL_FULL_FAMILY_EVIDENCE="
            + json.dumps(
                {
                    "games": len(reference),
                    "primary_sha256": primary.sha256,
                    "reference_pgn_sha256": reference_sha256,
                    "integrity_file_count": len(before.files),
                    "component_extensions": component_extensions,
                    "reference_profile": reference_profile,
                    "decoded_profile": decoded_profile,
                    "all_game_trees": "PASS",
                    "library_source_search": "PASS",
                    "search_page_limit": _SEARCH_PAGE_LIMIT,
                    "search_page_count": search_page_count,
                    "export_reopen_all_records": "PASS",
                    "acsdb_quick_check": "PASS",
                    "acsdb_foreign_key_check": "PASS",
                    "acsdb_reopen": "PASS",
                    "source_family_immutable": "PASS",
                    "database_bytes": database_bytes,
                    "exported_bytes": exported_bytes,
                },
                sort_keys=True,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
