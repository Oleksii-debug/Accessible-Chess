from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.chessbase_decoder import ExternalChessBaseDecoderConfig, decode_chessbase_external
from acs.chessbase_library_import import ChessBaseLibraryImportService
from acs.game_identity import same_game_record, same_game_tree
from acs.gametree import PgnGame, VariationLine, parse_games
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.search_service import GameSearchQuery, GameSearchService


LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
_PROMOTION_RE = re.compile(r"=([QRBN])")
_CORE_TAGS = ("Event", "Site", "Date", "Round", "Result")


def _ready() -> bool:
    return bool(os.environ.get("LIBCBH_BRIDGE") and os.environ.get("LIBCBH_PROMOTIONS_DIR"))


def _config() -> ExternalChessBaseDecoderConfig:
    bridge = Path(os.environ["LIBCBH_BRIDGE"])
    return ExternalChessBaseDecoderConfig(
        bridge,
        expected_backend_commit=LIBCBH_COMMIT,
        timeout_seconds=120,
        library_directory=bridge.parent,
    )


def _read_reference(path: Path) -> tuple[PgnGame, ...]:
    return tuple(parse_games(path.read_text(encoding="utf-8-sig")))


def _walk_lines(line: VariationLine):
    yield line
    for move in line.moves:
        for variation in move.variations:
            yield from _walk_lines(variation)


def _promotion_histogram(games: tuple[PgnGame, ...]) -> dict[str, int]:
    histogram = {piece: 0 for piece in "QRBN"}
    for game in games:
        for line in _walk_lines(game.line):
            for move in line.moves:
                match = _PROMOTION_RE.search(move.san)
                if match:
                    histogram[match.group(1)] += 1
    return histogram


def _mainline_plies(game: PgnGame) -> int:
    return len(game.line.moves)


def _normalize_person(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    if "," not in text:
        return text.casefold()
    last, first = text.split(",", 1)
    return " ".join((first.strip(), last.strip())).casefold()


def _assert_metadata(test: unittest.TestCase, actual: PgnGame, expected: PgnGame) -> list[dict[str, str]]:
    name_order_differences: list[dict[str, str]] = []
    for tag in _CORE_TAGS:
        test.assertEqual(actual.tags.get(tag), expected.tags.get(tag), tag)
    for tag in ("White", "Black"):
        actual_value = actual.tags.get(tag)
        expected_value = expected.tags.get(tag)
        test.assertEqual(_normalize_person(actual_value), _normalize_person(expected_value), tag)
        if actual_value != expected_value:
            name_order_differences.append(
                {"tag": tag, "actual": actual_value or "", "reference": expected_value or ""}
            )
    return name_order_differences


def _stored_games(database: AcsDatabase, source_id: int) -> tuple[PgnGame, ...]:
    page = GameSearchService(database).search(GameSearchQuery(source_id=source_id, limit=1000))
    if page.has_more:
        raise AssertionError("promotion corpus unexpectedly exceeds one bounded QA page")
    ordered = sorted(page.items, key=lambda item: item.source_index)
    games: list[PgnGame] = []
    for item in ordered:
        row = database.get_game(item.game_id)
        if row is None:
            raise AssertionError(f"missing stored game {item.game_id}")
        games.append(parse_games(row["pgn_text"])[0])
    return tuple(games)


@unittest.skipUnless(_ready(), "pinned real libcbh promotion corpus is not configured")
class RealCbhPromotionsCorpusTests(unittest.TestCase):
    def test_many_promotions_matches_independent_pgn_and_survives_library_export_reopen(self) -> None:
        fixture = Path(os.environ["LIBCBH_PROMOTIONS_DIR"])
        source = fixture / "ManyPromotions.cbh"
        reference_path = fixture / "Promotions.pgn"
        self.assertTrue(source.is_file())
        self.assertTrue(reference_path.is_file())

        reference = _read_reference(reference_path)
        decoded = decode_chessbase_external(source, _config())
        self.assertFalse(decoded.warnings)
        self.assertEqual(len(decoded.games), len(reference))
        self.assertGreaterEqual(len(reference), 4)

        reference_histogram = _promotion_histogram(reference)
        decoded_histogram = _promotion_histogram(decoded.games)
        total_promotions = sum(reference_histogram.values())
        underpromotions = total_promotions - reference_histogram["Q"]
        self.assertGreaterEqual(total_promotions, 10)
        self.assertGreaterEqual(underpromotions, 10)
        self.assertGreater(reference_histogram["B"] + reference_histogram["N"] + reference_histogram["R"], 0)
        self.assertEqual(decoded_histogram, reference_histogram)
        max_mainline_plies = max(_mainline_plies(game) for game in reference)
        self.assertGreaterEqual(max_mainline_plies, 250)

        name_order_differences: list[dict[str, object]] = []
        for index, (actual, expected) in enumerate(zip(decoded.games, reference)):
            with self.subTest(game=index):
                self.assertTrue(
                    same_game_tree(actual, expected),
                    f"real promotion GameTree mismatch at source index {index}",
                )
                for difference in _assert_metadata(self, actual, expected):
                    name_order_differences.append({"game": index, **difference})

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path = root / "promotions.acsdb"
            database = AcsDatabase(database_path)
            try:
                report = ChessBaseLibraryImportService(database, _config()).import_database(source)
                self.assertEqual(report.decoded_game_count, len(reference))
                self.assertEqual(report.imported_game_count, len(reference))
                self.assertEqual(report.warning_count, 0)
                self.assertEqual(report.source_format, "cbh")

                source_page = GameSearchService(database).search(
                    GameSearchQuery(source_id=report.library_result.source_id, limit=1000)
                )
                self.assertEqual(len(source_page.items), len(reference))
                self.assertEqual(
                    [item.source_index for item in source_page.items],
                    list(range(len(reference))),
                )

                player_page = GameSearchService(database).search(
                    GameSearchQuery(player="Urh", source_name="ManyPromotions", limit=50)
                )
                self.assertGreaterEqual(len(player_page.items), 1)

                stored = _stored_games(database, report.library_result.source_id)
                self.assertEqual(len(stored), len(reference))
                for index, (stored_game, expected) in enumerate(zip(stored, reference)):
                    self.assertTrue(
                        same_game_tree(stored_game, expected),
                        f"stored promotion GameTree mismatch at source index {index}",
                    )

                exported = root / "promotions-export.pgn"
                save_pgn_atomic(exported, stored)
                reopened = open_pgn(exported).games
                self.assertEqual(len(reopened), len(stored))
                for before, after in zip(stored, reopened):
                    self.assertTrue(same_game_record(before, after))

                self.assertEqual(database.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                source_sha256 = report.source_sha256
                database_bytes = database_path.stat().st_size
            finally:
                database.close()

            reopened_database = AcsDatabase(database_path)
            try:
                self.assertEqual(reopened_database.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(
                    reopened_database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0],
                    len(reference),
                )
            finally:
                reopened_database.close()

        print(
            "CBH_PROMOTIONS_EVIDENCE="
            + json.dumps(
                {
                    "games": len(reference),
                    "source_sha256": source_sha256,
                    "promotion_histogram": reference_histogram,
                    "total_promotions": total_promotions,
                    "underpromotions": underpromotions,
                    "max_mainline_plies": max_mainline_plies,
                    "normalized_name_order_differences": name_order_differences,
                    "all_game_trees": "PASS",
                    "library_search": "PASS",
                    "export_reopen": "PASS",
                    "acsdb_reopen": "PASS",
                    "database_bytes": database_bytes,
                },
                sort_keys=True,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
