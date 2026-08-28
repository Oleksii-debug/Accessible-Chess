from __future__ import annotations

import json
import os
from pathlib import Path
import random
import re
import resource
import tempfile
import time

from acs.acsdb import AcsDatabase
from acs.cbv_extractor import ExternalCbvExtractorConfig
from acs.chessbase_decoder import ExternalChessBaseDecoderConfig
from acs.chessbase_library_import import ChessBaseLibraryImportService
from acs.game_identity import same_game_record, same_game_tree
from acs.gametree import PgnGame, VariationLine, parse_games
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.search_service import GameSearchQuery, GameSearchService

LIBCBH_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"
EXPECTED_GAMES = 6117
SEED = 20260828


def _walk(line: VariationLine, depth: int = 0) -> tuple[int, int, int]:
    comments = len(line.leading_comments) + len(line.trailing_comments)
    variations = 0
    max_depth = depth
    for move in line.moves:
        comments += len(move.comments_before) + len(move.comments_after)
        for variation in move.variations:
            variations += 1
            child_comments, child_variations, child_depth = _walk(variation, depth + 1)
            comments += child_comments
            variations += child_variations
            max_depth = max(max_depth, child_depth)
    return comments, variations, max_depth


def _non_ascii(game: PgnGame) -> bool:
    return any(any(ord(char) > 127 for char in value) for value in game.tags.values())


def _weird_date(game: PgnGame) -> bool:
    return re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", game.tags.get("Date", "")) is None


def _normalized_person(value: str) -> tuple[str, ...]:
    return tuple(sorted(part.casefold() for part in re.findall(r"[^\W_]+", value, flags=re.UNICODE)))


def _first_index(games: tuple[PgnGame, ...], predicate) -> int | None:
    for index, game in enumerate(games):
        if predicate(game):
            return index
    return None


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return value


def main() -> int:
    cbv_path = Path(_require_env("UNCBV_FIXTURE"))
    pgn_path = Path(_require_env("TWIC_PGN_FIXTURE"))
    bridge = Path(_require_env("LIBCBH_BRIDGE"))
    uncbv = Path(_require_env("UNCBV_BINARY"))
    uncbv_sha = _require_env("UNCBV_BINARY_SHA256")

    document = open_pgn(pgn_path)
    source_games = tuple(document.games)
    if len(source_games) != EXPECTED_GAMES:
        raise AssertionError(f"TWIC PGN count mismatch: {len(source_games)} != {EXPECTED_GAMES}")

    rng = random.Random(SEED)
    sample_indices = {0, EXPECTED_GAMES - 1}
    sample_indices.update(rng.sample(range(EXPECTED_GAMES), 16))

    coverage: dict[str, int | None] = {
        "unicode": _first_index(source_games, _non_ascii),
        "weird_date": _first_index(source_games, _weird_date),
        "comments": _first_index(source_games, lambda game: _walk(game.line)[0] > 0),
        "variations": _first_index(source_games, lambda game: _walk(game.line)[1] > 0),
        "nested_rav": _first_index(source_games, lambda game: _walk(game.line)[2] >= 2),
        "setup_fen": _first_index(source_games, lambda game: game.tags.get("SetUp") == "1"),
    }
    sample_indices.update(index for index in coverage.values() if index is not None)

    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="accessible-chess-real-corpus-") as temporary:
        root = Path(temporary)
        database_path = root / "twic1134.acsdb"
        database = AcsDatabase(database_path)
        try:
            service = ChessBaseLibraryImportService(
                database,
                ExternalChessBaseDecoderConfig(
                    bridge,
                    expected_backend_commit=LIBCBH_COMMIT,
                    timeout_seconds=180,
                    library_directory=bridge.parent,
                ),
                ExternalCbvExtractorConfig(
                    uncbv,
                    expected_backend_sha256=uncbv_sha,
                    timeout_seconds=300,
                    max_source_bytes=64 * 1024 * 1024,
                    max_extracted_bytes=256 * 1024 * 1024,
                ),
            )
            report = service.import_database(cbv_path)
            if report.decoded_game_count != EXPECTED_GAMES or report.imported_game_count != EXPECTED_GAMES:
                raise AssertionError(
                    f"CBV count mismatch: decoded={report.decoded_game_count} imported={report.imported_game_count}"
                )
            if report.library_result is None:
                raise AssertionError("CBV import did not publish a Library result")

            source_id = report.library_result.source_id
            rows = database.conn.execute(
                "SELECT id, source_index, pgn_text, white, black, event, site, game_date, round, result "
                "FROM games WHERE source_id=? ORDER BY source_index",
                (source_id,),
            ).fetchall()
            if len(rows) != EXPECTED_GAMES:
                raise AssertionError(f"ACSDB row count mismatch: {len(rows)}")
            indexes = [int(row["source_index"]) for row in rows]
            if indexes != list(range(EXPECTED_GAMES)):
                raise AssertionError("ACSDB source_index sequence is not contiguous 0..6116")
            quick_check = str(database.conn.execute("PRAGMA quick_check").fetchone()[0])
            if quick_check.lower() != "ok":
                raise AssertionError(f"ACSDB quick_check failed: {quick_check}")

            metadata_differences: dict[str, int] = {
                "Event": 0,
                "Site": 0,
                "Date": 0,
                "Round": 0,
                "White": 0,
                "Black": 0,
                "Result": 0,
            }
            stored_samples: list[PgnGame] = []
            source_samples: list[PgnGame] = []
            sample_records: list[dict[str, object]] = []
            for index in sorted(sample_indices):
                source_game = source_games[index]
                stored_game = parse_games(str(rows[index]["pgn_text"]))[0]
                if not same_game_tree(source_game, stored_game):
                    raise AssertionError(f"real CBV/PGN GameTree mismatch at source_index={index}")

                for tag in ("Event", "Site", "Date", "Round", "Result"):
                    if source_game.tags.get(tag, "") != stored_game.tags.get(tag, ""):
                        metadata_differences[tag] += 1
                for tag in ("White", "Black"):
                    if _normalized_person(source_game.tags.get(tag, "")) != _normalized_person(
                        stored_game.tags.get(tag, "")
                    ):
                        metadata_differences[tag] += 1

                comments, variations, depth = _walk(source_game.line)
                sample_records.append(
                    {
                        "source_index": index,
                        "white": source_game.tags.get("White"),
                        "black": source_game.tags.get("Black"),
                        "event": source_game.tags.get("Event"),
                        "date": source_game.tags.get("Date"),
                        "comments": comments,
                        "variations": variations,
                        "rav_depth": depth,
                    }
                )
                source_samples.append(source_game)
                stored_samples.append(stored_game)

            export_path = root / "sampled-export.pgn"
            save_pgn_atomic(export_path, tuple(stored_samples))
            reopened = tuple(open_pgn(export_path).games)
            if len(reopened) != len(stored_samples):
                raise AssertionError("sampled PGN export/reopen count mismatch")
            for index, (before, after) in enumerate(zip(stored_samples, reopened)):
                if not same_game_record(before, after):
                    raise AssertionError(f"sampled PGN export/reopen record mismatch at sample={index}")

            first_row = rows[0]
            player_probe = str(first_row["white"] or first_row["black"] or "").strip()
            if not player_probe:
                raise AssertionError("first real imported game has no searchable player")
            page = GameSearchService(database).search(
                GameSearchQuery(player=player_probe, source_id=source_id, limit=100)
            )
            if not any(item.source_index == 0 for item in page.items):
                raise AssertionError("Library search did not return the first real imported game")

            source_sha = report.source_sha256
            imported_status = report.status.value
            db_bytes = database_path.stat().st_size
        finally:
            database.close()

        reopened_database = AcsDatabase(database_path)
        try:
            if str(reopened_database.conn.execute("PRAGMA quick_check").fetchone()[0]).lower() != "ok":
                raise AssertionError("reopened ACSDB quick_check failed")
            reopened_count = int(
                reopened_database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
            )
            if reopened_count != EXPECTED_GAMES:
                raise AssertionError(f"reopened ACSDB game count mismatch: {reopened_count}")
        finally:
            reopened_database.close()

    elapsed = time.perf_counter() - started
    max_rss_kib = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    summary = {
        "authority_sha": os.environ.get("V2_AUTHORITY_SHA"),
        "corpus": "TWIC 1134",
        "cbv_source": "antoyo/uncbv pinned repository fixture tests/twic1134.cbv",
        "cbv_upstream_commit": os.environ.get("UNCBV_COMMIT"),
        "cbv_sha256": os.environ.get("TWIC_CBV_SHA256"),
        "pgn_source": "https://theweekinchess.com/zips/twic1134g.zip (transient QA only; not redistributed)",
        "pgn_zip_sha256": os.environ.get("TWIC_PGN_ZIP_SHA256"),
        "expected_games": EXPECTED_GAMES,
        "import_status": imported_status,
        "source_sha256": source_sha,
        "sample_count": len(sample_indices),
        "sample_indices": sorted(sample_indices),
        "coverage_indices": coverage,
        "metadata_difference_counts_within_sample": metadata_differences,
        "sample_records": sample_records,
        "tree_semantics": "PASS",
        "library_search": "PASS",
        "sample_export_reopen": "PASS",
        "acsdb_reopen_integrity": "PASS",
        "elapsed_seconds": round(elapsed, 3),
        "max_rss_kib": max_rss_kib,
        "database_bytes_before_close": db_bytes,
    }
    Path("real-corpus-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
