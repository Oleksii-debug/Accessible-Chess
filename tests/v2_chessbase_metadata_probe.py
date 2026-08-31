from __future__ import annotations

import json
import os
from pathlib import Path
import random
import re
import tempfile

from acs.acsdb import AcsDatabase
from acs.cbv_extractor import ExternalCbvExtractorConfig
from acs.chessbase_decoder import ExternalChessBaseDecoderConfig
from acs.chessbase_library_import import ChessBaseLibraryImportService
from acs.chessbase_metadata import (
    PINNED_LIBCBH_COMMIT,
    chessbase_metadata_capabilities,
    chessbase_metadata_unavailable_fields,
)
from acs.game_identity import same_game_record
from acs.gametree import PgnGame, parse_games
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.search_service import GameSearchQuery, GameSearchService


EXPECTED_GAMES = 6117
SEED = 20260831


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return value


def _normalized_person(value: str) -> tuple[str, ...]:
    return tuple(sorted(part.casefold() for part in re.findall(r"[^\W_]+", value, flags=re.UNICODE)))


def _metadata_equal(tag: str, expected: str, actual: str) -> bool:
    if tag in {"White", "Black"}:
        return _normalized_person(expected) == _normalized_person(actual)
    return expected == actual


def _sample_indices(count: int) -> list[int]:
    rng = random.Random(SEED)
    indexes = {0, count - 1}
    indexes.update(rng.sample(range(count), 62))
    return sorted(indexes)


def _first_with_tag(games: tuple[PgnGame, ...], tag: str) -> int | None:
    for index, game in enumerate(games):
        value = game.tags.get(tag, "").strip()
        if value and value != "?":
            return index
    return None


def main() -> int:
    cbv_path = Path(_require_env("UNCBV_FIXTURE"))
    pgn_path = Path(_require_env("TWIC_PGN_FIXTURE"))
    bridge = Path(_require_env("LIBCBH_BRIDGE"))
    uncbv = Path(_require_env("UNCBV_BINARY"))
    uncbv_sha = _require_env("UNCBV_BINARY_SHA256")
    cbv_sha = _require_env("TWIC_CBV_SHA256")

    oracle_games = tuple(open_pgn(pgn_path).games)
    if len(oracle_games) != EXPECTED_GAMES:
        raise AssertionError(f"TWIC PGN count mismatch: {len(oracle_games)} != {EXPECTED_GAMES}")

    indexes = _sample_indices(EXPECTED_GAMES)
    for tag in ("ECO", "Opening", "WhiteElo", "BlackElo"):
        index = _first_with_tag(oracle_games, tag)
        if index is not None:
            indexes.append(index)
    indexes = sorted(set(indexes))

    with tempfile.TemporaryDirectory(prefix="accessible-chess-metadata-") as temporary:
        root = Path(temporary)
        database_path = root / "metadata.acsdb"
        database = AcsDatabase(database_path)
        try:
            service = ChessBaseLibraryImportService(
                database,
                ExternalChessBaseDecoderConfig(
                    bridge,
                    expected_backend_commit=PINNED_LIBCBH_COMMIT,
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
            if report.source_sha256 != cbv_sha:
                raise AssertionError(
                    f"original CBV SHA mismatch: report={report.source_sha256} expected={cbv_sha}"
                )

            source_id = report.library_result.source_id
            rows = database.conn.execute(
                "SELECT id, source_index, pgn_text, white, black, event, site, game_date, round, result, eco, opening "
                "FROM games WHERE source_id=? ORDER BY source_index",
                (source_id,),
            ).fetchall()
            if len(rows) != EXPECTED_GAMES:
                raise AssertionError(f"ACSDB row count mismatch: {len(rows)}")
            if [int(row["source_index"]) for row in rows] != list(range(EXPECTED_GAMES)):
                raise AssertionError("source_index is not contiguous 0..6116")

            differences = {
                tag: 0
                for tag in (
                    "White",
                    "Black",
                    "Event",
                    "Site",
                    "Date",
                    "Round",
                    "Result",
                    "WhiteElo",
                    "BlackElo",
                    "ECO",
                )
            }
            opening_oracle_present = 0
            opening_decoded_present = 0
            stored_samples: list[PgnGame] = []
            sample_details: list[dict[str, object]] = []
            eco_search_probe: tuple[int, str] | None = None

            for index in indexes:
                oracle = oracle_games[index]
                stored = parse_games(str(rows[index]["pgn_text"]))[0]
                for tag in differences:
                    expected = oracle.tags.get(tag, "")
                    actual = stored.tags.get(tag, "")
                    if expected and expected != "?" and not _metadata_equal(tag, expected, actual):
                        differences[tag] += 1
                oracle_opening = oracle.tags.get("Opening", "").strip()
                decoded_opening = stored.tags.get("Opening", "").strip()
                opening_oracle_present += int(bool(oracle_opening and oracle_opening != "?"))
                opening_decoded_present += int(bool(decoded_opening and decoded_opening != "?"))

                eco = oracle.tags.get("ECO", "").strip()
                if eco and eco != "?" and eco_search_probe is None:
                    eco_search_probe = (index, eco)

                stored_samples.append(stored)
                sample_details.append(
                    {
                        "source_index": index,
                        "white": stored.tags.get("White"),
                        "black": stored.tags.get("Black"),
                        "event": stored.tags.get("Event"),
                        "site": stored.tags.get("Site"),
                        "date": stored.tags.get("Date"),
                        "round": stored.tags.get("Round"),
                        "result": stored.tags.get("Result"),
                        "white_elo": stored.tags.get("WhiteElo"),
                        "black_elo": stored.tags.get("BlackElo"),
                        "eco": stored.tags.get("ECO"),
                        "raw_cbh_eco": stored.tags.get("CBH_ECO"),
                        "opening": stored.tags.get("Opening"),
                    }
                )

            for tag, count in differences.items():
                if count:
                    raise AssertionError(f"real metadata mismatch for {tag}: {count} sampled games")
            if eco_search_probe is None:
                raise AssertionError("TWIC oracle did not provide any ECO coverage")

            search = GameSearchService(database)
            eco_index, eco_value = eco_search_probe
            eco_page = search.search(GameSearchQuery(eco=eco_value, source_id=source_id, limit=200))
            if not any(item.source_index == eco_index for item in eco_page.items):
                raise AssertionError(f"Library ECO search did not find source_index={eco_index} ECO={eco_value}")

            first = oracle_games[0]
            player_probe = first.tags.get("White", "").strip() or first.tags.get("Black", "").strip()
            player_page = search.search(GameSearchQuery(player=player_probe, source_id=source_id, limit=200))
            if not any(item.source_index == 0 for item in player_page.items):
                raise AssertionError("Library player search did not find source_index=0")

            source_page = search.search(GameSearchQuery(source_name=cbv_path.name, limit=10))
            if not source_page.items or not any(item.source_id == source_id for item in source_page.items):
                raise AssertionError("Library source-name search did not find original CBV source")

            export_path = root / "metadata-sample.pgn"
            save_pgn_atomic(export_path, tuple(stored_samples))
            reopened = tuple(open_pgn(export_path).games)
            if len(reopened) != len(stored_samples):
                raise AssertionError("metadata export/reopen count mismatch")
            for sample_index, (before, after) in enumerate(zip(stored_samples, reopened)):
                if not same_game_record(before, after):
                    raise AssertionError(f"metadata export/reopen mismatch at sample={sample_index}")

            quick_check = str(database.conn.execute("PRAGMA quick_check").fetchone()[0])
            if quick_check.lower() != "ok":
                raise AssertionError(f"ACSDB quick_check failed: {quick_check}")
        finally:
            database.close()

    capability_rows = [
        {
            "field": item.field,
            "status": item.status.value,
            "canonical_field": item.canonical_field,
            "evidence": item.evidence,
        }
        for item in chessbase_metadata_capabilities()
    ]
    summary = {
        "authority_base_sha": os.environ.get("V2_METADATA_BASE_SHA"),
        "corpus": "TWIC 1134 CBV + independent TWIC PGN oracle",
        "expected_games": EXPECTED_GAMES,
        "sample_count": len(indexes),
        "sample_indices": indexes,
        "metadata_difference_counts": differences,
        "opening_oracle_present_in_sample": opening_oracle_present,
        "opening_decoded_present_in_sample": opening_decoded_present,
        "not_exposed_fields": list(chessbase_metadata_unavailable_fields()),
        "capabilities": capability_rows,
        "original_source_name": cbv_path.name,
        "original_source_sha256": cbv_sha,
        "source_index_range": [0, EXPECTED_GAMES - 1],
        "library_player_search": "PASS",
        "library_eco_search": "PASS",
        "library_source_search": "PASS",
        "pgn_export_reopen": "PASS",
        "acsdb_integrity": "PASS",
        "sample_details": sample_details,
    }
    Path("chessbase-metadata-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
