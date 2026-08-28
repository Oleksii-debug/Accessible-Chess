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
    # The independent libcbh PGN exporter line-wraps long brace comments. CBH
    # TextBefore/TextAfter records carry the same words without that wrapping.
    # Collapse formatting whitespace only; word content and comment style remain
    # exact semantic evidence. Language preservation is checked separately.
    text = _LANGUAGE_PREFIX.sub("", comment.text)
    return comment.style.value, " ".join(text.split())


def _normalized_person(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    if "," not in text:
        return text.casefold()
    last, first = text.split(",", 1)
    return " ".join((first.strip(), last.strip())).casefold()


def _line_content_signature(line: VariationLine):
    """Compare chess/text semantics while normalizing PGN pre-first-move placement.

    A CBH TextBefore annotation on the first move is represented by Accessible
    Chess as ``first_move.comments_before``. The independent PGN export writes
    the same text before the first move number, which the generic PGN parser
    models as ``line.leading_comments``. Treat those placements as one semantic
    pre-first-move slot. NAG values are deliberately compared elsewhere without
    normalization.
    """

    if not line.moves:
        return (
            tuple(_normalized_comment(comment) for comment in line.leading_comments),
            (),
            tuple(_normalized_comment(comment) for comment in line.trailing_comments),
            line.result,
        )

    leading = tuple(_normalized_comment(comment) for comment in line.leading_comments)
    moves = []
    for index, move in enumerate(line.moves):
        before = tuple(_normalized_comment(comment) for comment in move.comments_before)
        if index == 0:
            before = leading + before
        moves.append(
            (
                move.san,
                before,
                tuple(_normalized_comment(comment) for comment in move.comments_after),
                tuple(_line_content_signature(variation) for variation in move.variations),
            )
        )
    return (
        (),
        tuple(moves),
        tuple(_normalized_comment(comment) for comment in line.trailing_comments),
        line.result,
    )


def _nag_mismatches(
    actual: VariationLine,
    expected: VariationLine,
    *,
    path: str = "root",
) -> list[dict[str, object]]:
    mismatches: list[dict[str, object]] = []
    for move_index, (actual_move, expected_move) in enumerate(zip(actual.moves, expected.moves)):
        move_path = f"{path}/move[{move_index}]/{expected_move.san}"
        if tuple(actual_move.nags) != tuple(expected_move.nags):
            mismatches.append(
                {
                    "path": move_path,
                    "actual": list(actual_move.nags),
                    "reference": list(expected_move.nags),
                }
            )
        for variation_index, (actual_variation, expected_variation) in enumerate(
            zip(actual_move.variations, expected_move.variations)
        ):
            mismatches.extend(
                _nag_mismatches(
                    actual_variation,
                    expected_variation,
                    path=f"{move_path}/variation[{variation_index}]",
                )
            )
    return mismatches


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


def _assert_core_tags(test: unittest.TestCase, actual: PgnGame, reference: PgnGame) -> list[dict[str, str]]:
    normalized_name_differences: list[dict[str, str]] = []
    for tag in _CORE_TAGS:
        actual_value = actual.tags.get(tag)
        reference_value = reference.tags.get(tag)
        if tag in {"White", "Black"}:
            test.assertEqual(_normalized_person(actual_value), _normalized_person(reference_value), tag)
            if actual_value != reference_value:
                normalized_name_differences.append(
                    {"tag": tag, "actual": actual_value or "", "reference": reference_value or ""}
                )
        else:
            test.assertEqual(actual_value, reference_value, tag)
    return normalized_name_differences


def _stored_games(database: AcsDatabase, source_id: int) -> tuple[PgnGame, ...]:
    page = GameSearchService(database).search(GameSearchQuery(source_id=source_id, limit=50))
    ordered = sorted(page.items, key=lambda item: item.source_index)
    games: list[PgnGame] = []
    for item in ordered:
        row = database.get_game(item.game_id)
        if row is None:
            raise AssertionError(f"missing stored game id {item.game_id}")
        games.append(parse_games(row["pgn_text"])[0])
    return tuple(games)


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

        all_nag_mismatches: list[dict[str, object]] = []
        normalized_name_differences: list[dict[str, object]] = []
        for index, (actual, expected) in enumerate(zip(decoded.games, reference)):
            with self.subTest(game=index):
                for difference in _assert_core_tags(self, actual, expected):
                    normalized_name_differences.append({"game": index, **difference})
                self.assertEqual(
                    _line_content_signature(actual.line),
                    _line_content_signature(expected.line),
                )
                for mismatch in _nag_mismatches(actual.line, expected.line):
                    all_nag_mismatches.append({"game": index, **mismatch})

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
                    GameSearchQuery(player="annotation", source_name="TestBase")
                )
                self.assertGreaterEqual(len(page.items), 1)
                self.assertTrue(any(item.source_index == 3 for item in page.items))

                stored_games = _stored_games(database, report.library_result.source_id)
                self.assertEqual(len(stored_games), 4)
                self.assertEqual(
                    _line_content_signature(stored_games[-1].line),
                    _line_content_signature(reference[-1].line),
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

        evidence = {
            "games": 4,
            "reference_nags": reference_nags,
            "reference_comments": reference_comments,
            "decoded_language_markers": decoded_language_markers,
            "normalized_name_differences": normalized_name_differences,
            "nag_mismatches": all_nag_mismatches,
            "comment_whitespace_policy": "collapse exporter line wrapping only",
            "text_and_move_semantics": "PASS",
            "library_search": "PASS",
            "export_reopen_internal_identity": "PASS",
            "acsdb_reopen": "PASS",
        }
        print("CBH_ANNOTATION_EVIDENCE=" + json.dumps(evidence, sort_keys=True, ensure_ascii=False))
        self.assertFalse(
            all_nag_mismatches,
            "real CBH NAG semantics differ from independent reference: "
            + json.dumps(all_nag_mismatches, sort_keys=True),
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
        name_differences = _assert_core_tags(self, actual, expected)
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
                row = database.get_game(report.library_result.first_game_id)
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
                    "normalized_name_differences": name_differences,
                    "tree_semantics": "PASS",
                    "library": "PASS",
                    "export_reopen": "PASS",
                },
                sort_keys=True,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
