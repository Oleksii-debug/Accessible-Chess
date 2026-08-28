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
from acs.gametree import Comment, PgnGame, VariationLine, parse_games
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.search_service import GameSearchQuery, GameSearchService


LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
_LANGUAGE_PREFIX = re.compile(r"^\[%cbh-lang [0-9]+\]\s*")
_CORE_TAGS = ("Event", "Site", "Date", "Round", "White", "Black", "Result")


def _environment_ready() -> bool:
    return all(
        os.environ.get(name)
        for name in (
            "LIBCBH_BRIDGE",
            "LIBCBH_ANNOTATION_DIR",
            "LIBCBH_NONSTANDARD_DIR",
        )
    )


def _normalized_comment(comment: Comment) -> tuple[str, str]:
    return comment.style.value, _LANGUAGE_PREFIX.sub("", comment.text)


def _line_signature(line: VariationLine):
    return (
        tuple(_normalized_comment(comment) for comment in line.leading_comments),
        tuple(
            (
                move.san,
                tuple(move.nags),
                tuple(_normalized_comment(comment) for comment in move.comments_before),
                tuple(_normalized_comment(comment) for comment in move.comments_after),
                tuple(_line_signature(variation) for variation in move.variations),
            )
            for move in line.moves
        ),
        tuple(_normalized_comment(comment) for comment in line.trailing_comments),
        line.result,
    )


def _walk_lines(line: VariationLine):
    yield line
    for move in line.moves:
        for variation in move.variations:
            yield from _walk_lines(variation)


def _annotation_counts(games: tuple[PgnGame, ...]) -> tuple[int, int, int]:
    nags = 0
    comments = 0
    language_markers = 0
    for game in games:
        for line in _walk_lines(game.line):
            comments += len(line.leading_comments) + len(line.trailing_comments)
            for comment in (*line.leading_comments, *line.trailing_comments):
                language_markers += int(bool(_LANGUAGE_PREFIX.match(comment.text)))
            for move in line.moves:
                nags += len(move.nags)
                comments += len(move.comments_before) + len(move.comments_after)
                for comment in (*move.comments_before, *move.comments_after):
                    language_markers += int(bool(_LANGUAGE_PREFIX.match(comment.text)))
    return nags, comments, language_markers


def _read_reference(path: Path) -> tuple[PgnGame, ...]:
    return tuple(parse_games(path.read_text(encoding="utf-8-sig")))


def _decoder_config() -> ExternalChessBaseDecoderConfig:
    bridge = Path(os.environ["LIBCBH_BRIDGE"])
    return ExternalChessBaseDecoderConfig(
        bridge,
        expected_backend_commit=LIBCBH_COMMIT,
        timeout_seconds=120,
        library_directory=bridge.parent,
    )


def _assert_core_tags(test: unittest.TestCase, actual: PgnGame, reference: PgnGame) -> None:
    for tag in _CORE_TAGS:
        test.assertEqual(actual.tags.get(tag), reference.tags.get(tag), tag)


@unittest.skipUnless(_environment_ready(), "pinned real libcbh semantic corpus is not configured")
class RealCbhSemanticCorpusTests(unittest.TestCase):
    def test_annotation_family_matches_reference_nags_and_text_comments_end_to_end(self) -> None:
        fixture = Path(os.environ["LIBCBH_ANNOTATION_DIR"])
        source = fixture / "TestBase.cbh"
        reference_path = fixture / "TestBaseExport.pgn"
        self.assertTrue(source.is_file())
        self.assertTrue(reference_path.is_file())

        decoded = decode_chessbase_external(source, _decoder_config())
        reference = _read_reference(reference_path)
        self.assertFalse(decoded.warnings)
        self.assertEqual(len(decoded.games), len(reference))
        self.assertEqual(len(reference), 4)

        reference_nags, reference_comments, _ = _annotation_counts(reference)
        decoded_nags, decoded_comments, decoded_language_markers = _annotation_counts(decoded.games)
        self.assertGreaterEqual(reference_nags, 20)
        self.assertGreaterEqual(reference_comments, 3)
        self.assertEqual(decoded_nags, reference_nags)
        self.assertEqual(decoded_comments, reference_comments)
        self.assertGreaterEqual(decoded_language_markers, 1)

        for index, (actual, expected) in enumerate(zip(decoded.games, reference)):
            with self.subTest(game=index):
                _assert_core_tags(self, actual, expected)
                self.assertEqual(_line_signature(actual.line), _line_signature(expected.line))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path = root / "annotation.acsdb"
            database = AcsDatabase(database_path)
            try:
                report = ChessBaseLibraryImportService(database, _decoder_config()).import_database(source)
                self.assertEqual(report.decoded_game_count, 4)
                self.assertEqual(report.imported_game_count, 4)
                self.assertEqual(report.warning_count, 0)
                self.assertEqual(report.source_format, "cbh")

                page = GameSearchService(database).search(
                    GameSearchQuery(player="Text annotation", source_name="TestBase")
                )
                self.assertEqual(len(page.items), 1)
                row = database.get_game(page.items[0].game_id)
                self.assertIsNotNone(row)
                assert row is not None
                stored_text_game = parse_games(row["pgn_text"])[0]
                self.assertEqual(
                    _line_signature(stored_text_game.line),
                    _line_signature(reference[-1].line),
                )

                stored_games = tuple(
                    parse_games(database.get_game(game_id)["pgn_text"])[0]
                    for game_id in report.library_result.game_ids
                )
                exported = root / "annotation-export.pgn"
                save_pgn_atomic(exported, stored_games)
                reopened = open_pgn(exported).games
                self.assertEqual(len(reopened), len(stored_games))
                for before, after in zip(stored_games, reopened):
                    self.assertTrue(same_game_record(before, after))
                self.assertEqual(database.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
            finally:
                database.close()

            reopened_database = AcsDatabase(database_path)
            try:
                self.assertEqual(reopened_database.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(reopened_database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 4)
            finally:
                reopened_database.close()

        print(
            "CBH_ANNOTATION_EVIDENCE="
            + json.dumps(
                {
                    "games": 4,
                    "reference_nags": reference_nags,
                    "reference_comments": reference_comments,
                    "decoded_language_markers": decoded_language_markers,
                    "tree_semantics": "PASS",
                    "library_search": "PASS",
                    "export_reopen": "PASS",
                    "acsdb_reopen": "PASS",
                },
                sort_keys=True,
            )
        )

    def test_nonstandard_start_family_matches_reference_setup_fen_and_tree(self) -> None:
        fixture = Path(os.environ["LIBCBH_NONSTANDARD_DIR"])
        source = fixture / "NonStandardStart.cbh"
        reference_path = fixture / "NonStandardStart.pgn"
        self.assertTrue(source.is_file())
        self.assertTrue(reference_path.is_file())

        decoded = decode_chessbase_external(source, _decoder_config())
        reference = _read_reference(reference_path)
        self.assertFalse(decoded.warnings)
        self.assertEqual(len(decoded.games), 1)
        self.assertEqual(len(reference), 1)

        actual = decoded.games[0]
        expected = reference[0]
        _assert_core_tags(self, actual, expected)
        self.assertEqual(actual.tags.get("SetUp"), "1")
        self.assertEqual(actual.tags.get("FEN"), expected.tags.get("FEN"))
        self.assertTrue(same_game_tree(actual, expected))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database_path = root / "nonstandard.acsdb"
            database = AcsDatabase(database_path)
            try:
                report = ChessBaseLibraryImportService(database, _decoder_config()).import_database(source)
                self.assertEqual(report.decoded_game_count, 1)
                self.assertEqual(report.imported_game_count, 1)
                row = database.get_game(report.library_result.game_ids[0])
                self.assertIsNotNone(row)
                assert row is not None
                self.assertEqual(row["start_fen"], expected.tags["FEN"])
                stored = parse_games(row["pgn_text"])[0]
                self.assertTrue(same_game_tree(stored, expected))
                exported = root / "nonstandard-export.pgn"
                save_pgn_atomic(exported, (stored,))
                reopened = open_pgn(exported).games[0]
                self.assertTrue(same_game_record(stored, reopened))
                self.assertEqual(database.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
            finally:
                database.close()

        print(
            "CBH_NONSTANDARD_EVIDENCE="
            + json.dumps(
                {
                    "games": 1,
                    "setup": actual.tags.get("SetUp"),
                    "fen": actual.tags.get("FEN"),
                    "tree_semantics": "PASS",
                    "library": "PASS",
                    "export_reopen": "PASS",
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
