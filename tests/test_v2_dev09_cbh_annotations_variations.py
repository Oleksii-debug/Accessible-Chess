from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.chessbase_decoder import ExternalChessBaseDecoderConfig, decode_chessbase_external
from acs.chessbase_library_import import ChessBaseLibraryImportService
from acs.gametree import Comment, PgnGame, VariationLine, parse_games
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.search_service import GameSearchQuery, GameSearchService


LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
_LANGUAGE_PREFIX = re.compile(r"^\[%cbh-lang [0-9]+\]\s*")
_CORE_TAGS = ("Event", "Site", "Round", "Result")


def _environment_ready() -> bool:
    return all(
        os.environ.get(name)
        for name in (
            "LIBCBH_BRIDGE",
            "LIBCBH_ANNOTATION_DIR",
            "LIBCBH_VARIATION_DIR",
            "LIBCBH_UNUSUAL_DIR",
        )
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _family_hashes(directory: Path, stem: str) -> dict[str, str]:
    files = sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.name.startswith(stem + ".")
    )
    if not files:
        raise AssertionError(f"missing real CBH family for {stem}")
    return {path.name: _sha256(path) for path in files}


def _normalized_person(value: str | None) -> str:
    if not value:
        return ""
    text = " ".join(value.split())
    if "," not in text:
        return text.casefold()
    last, first = text.split(",", 1)
    return " ".join((first.strip(), last.strip())).casefold()


def _normalized_date(value: str | None) -> str:
    # libcbh's integer date DTO uses zero for an unknown month/day, while the
    # independent PGN oracle writes PGN's conventional "??" placeholder. This
    # is a bounded representation normalization, not invention of a date.
    if not value:
        return ""
    parts = value.split(".")
    if len(parts) != 3:
        return value
    return ".".join("??" if part == "00" else part for part in parts)


def _normalized_comment(comment: Comment) -> tuple[str, str]:
    # ChessBase/libcbh PGN oracles may wrap brace-comment text differently.
    # Collapse formatting whitespace only; words and comment style stay exact.
    text = _LANGUAGE_PREFIX.sub("", comment.text)
    return comment.style.value, " ".join(text.split())


def _line_semantics(line: VariationLine):
    # A CBH TextBefore on the first move maps to comments_before, while a PGN
    # exporter writes the same semantic text before the first move number and
    # the canonical PGN parser represents it as line.leading_comments.
    leading = tuple(_normalized_comment(comment) for comment in line.leading_comments)
    moves = []
    for index, move in enumerate(line.moves):
        before = tuple(_normalized_comment(comment) for comment in move.comments_before)
        if index == 0:
            before = leading + before
        moves.append(
            (
                move.san,
                tuple(move.nags),
                before,
                tuple(_normalized_comment(comment) for comment in move.comments_after),
                tuple(_line_semantics(variation) for variation in move.variations),
            )
        )
    return (
        () if line.moves else leading,
        tuple(moves),
        tuple(_normalized_comment(comment) for comment in line.trailing_comments),
        line.result,
    )


def _assert_game_semantics(test: unittest.TestCase, actual: PgnGame, expected: PgnGame) -> None:
    for tag in _CORE_TAGS:
        test.assertEqual(actual.tags.get(tag), expected.tags.get(tag), tag)
    test.assertEqual(
        _normalized_date(actual.tags.get("Date")),
        _normalized_date(expected.tags.get("Date")),
        "Date",
    )
    test.assertEqual(
        _normalized_person(actual.tags.get("White")),
        _normalized_person(expected.tags.get("White")),
        "White",
    )
    test.assertEqual(
        _normalized_person(actual.tags.get("Black")),
        _normalized_person(expected.tags.get("Black")),
        "Black",
    )
    test.assertEqual(_line_semantics(actual.line), _line_semantics(expected.line))


def _annotation_counts(games: tuple[PgnGame, ...]) -> tuple[int, int, int]:
    nags = 0
    comments = 0
    language_markers = 0

    def walk(line: VariationLine) -> None:
        nonlocal nags, comments, language_markers
        for comment in (*line.leading_comments, *line.trailing_comments):
            comments += 1
            language_markers += int(bool(_LANGUAGE_PREFIX.match(comment.text)))
        for move in line.moves:
            nags += len(move.nags)
            for comment in (*move.comments_before, *move.comments_after):
                comments += 1
                language_markers += int(bool(_LANGUAGE_PREFIX.match(comment.text)))
            for variation in move.variations:
                walk(variation)

    for game in games:
        walk(game.line)
    return nags, comments, language_markers


def _variation_stats(games: tuple[PgnGame, ...]) -> dict[str, int]:
    stats = {
        "variation_lines": 0,
        "max_depth": 0,
        "max_siblings": 0,
        "comments_in_variations": 0,
        "nags_in_variations": 0,
    }

    def walk(line: VariationLine, depth: int) -> None:
        stats["max_depth"] = max(stats["max_depth"], depth)
        if depth:
            stats["comments_in_variations"] += len(line.leading_comments) + len(line.trailing_comments)
        for move in line.moves:
            stats["max_siblings"] = max(stats["max_siblings"], len(move.variations))
            if depth:
                stats["comments_in_variations"] += len(move.comments_before) + len(move.comments_after)
                stats["nags_in_variations"] += len(move.nags)
            for variation in move.variations:
                stats["variation_lines"] += 1
                walk(variation, depth + 1)

    for game in games:
        walk(game.line, 0)
    return stats


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
    after: int | None = None
    items = []
    while True:
        page = service.search(
            GameSearchQuery(source_id=source_id, after_game_id=after, limit=50)
        )
        items.extend(page.items)
        if not page.has_more:
            break
        if page.next_after_game_id is None:
            raise AssertionError("Library paging reported has_more without a cursor")
        after = page.next_after_game_id

    games: list[PgnGame] = []
    for item in sorted(items, key=lambda value: value.source_index):
        row = database.get_game(item.game_id)
        if row is None:
            raise AssertionError(f"missing stored game id {item.game_id}")
        games.append(parse_games(str(row["pgn_text"]))[0])
    return tuple(games)


def _assert_library_export_reopen(
    test: unittest.TestCase,
    source: Path,
    reference: tuple[PgnGame, ...],
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        database_path = root / "cbh-annotations-variations.acsdb"
        database = AcsDatabase(database_path)
        try:
            report = ChessBaseLibraryImportService(database, _decoder_config()).import_database(source)
            test.assertEqual(report.decoded_game_count, len(reference))
            test.assertEqual(report.imported_game_count, len(reference))
            test.assertEqual(report.warning_count, 0)
            test.assertEqual(report.source_format, "cbh")
            stored = _stored_games(database, report.library_result.source_id)
            test.assertEqual(len(stored), len(reference))
            for index, (actual, expected) in enumerate(zip(stored, reference)):
                with test.subTest(stored_game=index):
                    _assert_game_semantics(test, actual, expected)

            exported = root / "cbh-export.pgn"
            save_pgn_atomic(exported, stored)
            reopened = open_pgn(exported).games
            test.assertEqual(len(reopened), len(stored))
            for index, (actual, expected) in enumerate(zip(reopened, reference)):
                with test.subTest(reopened_game=index):
                    _assert_game_semantics(test, actual, expected)
            test.assertEqual(database.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
            test.assertEqual(database.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            database.close()

        reopened_database = AcsDatabase(database_path)
        try:
            test.assertEqual(reopened_database.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
            test.assertEqual(reopened_database.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            test.assertEqual(
                int(reopened_database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]),
                len(reference),
            )
        finally:
            reopened_database.close()


@unittest.skipUnless(_environment_ready(), "pinned real libcbh D09 corpus is not configured")
class Dev09RealCbhAnnotationsVariationsTests(unittest.TestCase):
    def test_real_annotation_family_matches_independent_pgn_end_to_end(self) -> None:
        fixture = Path(os.environ["LIBCBH_ANNOTATION_DIR"])
        source = fixture / "TestBase.cbh"
        reference_path = fixture / "TestBaseExport.pgn"
        before_hashes = _family_hashes(fixture, "TestBase")

        reference = tuple(parse_games(reference_path.read_text(encoding="utf-8-sig")))
        decoded = decode_chessbase_external(source, _decoder_config())
        self.assertEqual(len(reference), 4)
        self.assertEqual(len(decoded.games), 4)
        self.assertFalse(decoded.warnings)

        for index, (actual, expected) in enumerate(zip(decoded.games, reference)):
            with self.subTest(game=index):
                self.assertEqual(actual.source_index, index)
                _assert_game_semantics(self, actual, expected)

        reference_counts = _annotation_counts(reference)
        decoded_counts = _annotation_counts(decoded.games)
        self.assertEqual(reference_counts[:2], (29, 3))
        self.assertEqual(decoded_counts[:2], reference_counts[:2])
        self.assertGreaterEqual(decoded_counts[2], 1, "CBH language identity must remain observable")

        source_evidence = next(item for item in decoded.source.files if item.extension == ".cbh")
        self.assertEqual(source_evidence.path.name, "TestBase.cbh")
        self.assertEqual(source_evidence.sha256, _sha256(source))
        _assert_library_export_reopen(self, source, reference)
        self.assertEqual(_family_hashes(fixture, "TestBase"), before_hashes)

    def test_real_recursive_variations_preserve_siblings_nested_comments_and_nags(self) -> None:
        fixture = Path(os.environ["LIBCBH_VARIATION_DIR"])
        source = fixture / "WithVariations.cbh"
        reference_path = fixture / "GamesWithVariations.pgn"
        before_hashes = _family_hashes(fixture, "WithVariations")

        reference = tuple(parse_games(reference_path.read_text(encoding="utf-8-sig")))
        decoded = decode_chessbase_external(source, _decoder_config())
        self.assertGreater(len(reference), 0)
        self.assertEqual(len(decoded.games), len(reference))
        self.assertFalse(decoded.warnings)

        for index, (actual, expected) in enumerate(zip(decoded.games, reference)):
            with self.subTest(game=index):
                self.assertEqual(actual.source_index, index)
                _assert_game_semantics(self, actual, expected)

        expected_stats = _variation_stats(reference)
        actual_stats = _variation_stats(decoded.games)
        self.assertGreater(expected_stats["variation_lines"], 0)
        self.assertGreaterEqual(expected_stats["max_depth"], 2, "oracle must contain nested RAV")
        self.assertGreaterEqual(expected_stats["max_siblings"], 2, "oracle must contain sibling RAV")
        self.assertGreater(expected_stats["comments_in_variations"], 0)
        self.assertGreater(expected_stats["nags_in_variations"], 0)
        self.assertEqual(actual_stats, expected_stats)

        source_evidence = next(item for item in decoded.source.files if item.extension == ".cbh")
        self.assertEqual(source_evidence.path.name, "WithVariations.cbh")
        self.assertEqual(source_evidence.sha256, _sha256(source))
        _assert_library_export_reopen(self, source, reference)
        self.assertEqual(_family_hashes(fixture, "WithVariations"), before_hashes)

    def test_real_unusual_start_boundary_is_honestly_partial_or_preserved(self) -> None:
        # QA PR #362 independently established this pinned UnusualStartBytes
        # family as a backend boundary: current libcbh may publish zero games.
        # D09 does not take ownership of that decoder defect. We still exercise
        # the lawful corpus here so annotation work cannot silently turn the
        # known boundary into fabricated games or mutate its source family.
        fixture = Path(os.environ["LIBCBH_UNUSUAL_DIR"])
        source = fixture / "UnusualStartBytes.cbh"
        reference_path = fixture / "UnusualStart.pgn"
        before_hashes = _family_hashes(fixture, "UnusualStartBytes")

        reference = tuple(parse_games(reference_path.read_text(encoding="utf-8-sig")))
        decoded = decode_chessbase_external(source, _decoder_config())
        self.assertEqual(len(reference), 9)
        self.assertGreaterEqual(sum(1 for game in reference if not game.line.moves), 1)

        source_evidence = next(item for item in decoded.source.files if item.extension == ".cbh")
        self.assertEqual(source_evidence.path.name, "UnusualStartBytes.cbh")
        self.assertEqual(source_evidence.sha256, _sha256(source))
        self.assertEqual(_family_hashes(fixture, "UnusualStartBytes"), before_hashes)

        if not decoded.games:
            # Known external-backend limitation: do not invent the nine games
            # or promote a zero-ply capability that the backend did not expose.
            return

        self.assertEqual(len(decoded.games), 9)
        self.assertFalse(decoded.warnings)
        for index, (actual, expected) in enumerate(zip(decoded.games, reference)):
            with self.subTest(game=index):
                self.assertEqual(actual.source_index, index)
                _assert_game_semantics(self, actual, expected)

        zero_ply = [game for game in decoded.games if not game.line.moves]
        self.assertGreaterEqual(len(zero_ply), 1)
        for game in zero_ply:
            self.assertEqual(game.line.result, game.tags.get("Result"))
        _assert_library_export_reopen(self, source, reference)


if __name__ == "__main__":
    unittest.main()
