from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
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
MAX_MISMATCH_EXAMPLES_PER_FIELD = 20
ROUNDTRIP_CHUNK_SIZE = 128
_TAG_LINE = re.compile(r'^\[([A-Za-z0-9_]+)\s+"((?:\\.|[^"\\])*)"\]\s*$')
MAPPED_FIELDS = (
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


def _is_meaningful_oracle_value(tag: str, value: str) -> bool:
    normalized = value.strip()
    if not normalized or normalized == "?":
        return False
    if tag == "Date" and normalized == "????.??.??":
        return False
    return True


def _unescape_pgn_tag(value: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value) and value[index + 1] in {'"', "\\"}:
            output.append(value[index + 1])
            index += 2
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _read_oracle_tags(path: Path) -> tuple[dict[str, str], ...]:
    games: list[dict[str, str]] = []
    current: dict[str, str] = {}
    in_movetext = False
    with path.open("r", encoding="utf-8-sig", newline=None) as handle:
        for raw_line in handle:
            line = raw_line.strip()
            match = _TAG_LINE.fullmatch(line)
            if match is not None:
                if in_movetext:
                    if not current:
                        raise AssertionError("TWIC oracle started a new header block without prior tags")
                    games.append(current)
                    current = {}
                    in_movetext = False
                name, encoded_value = match.groups()
                if name in current:
                    raise AssertionError(f"duplicate TWIC oracle tag in one game: {name}")
                current[name] = _unescape_pgn_tag(encoded_value)
                continue
            if current and not in_movetext and not line:
                in_movetext = True
    if current:
        games.append(current)
    return tuple(games)


def _read_stored_tags(pgn_text: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for raw_line in pgn_text.splitlines():
        line = raw_line.strip()
        if not line:
            if tags:
                break
            continue
        match = _TAG_LINE.fullmatch(line)
        if match is None:
            if tags:
                break
            continue
        name, encoded_value = match.groups()
        if name in tags:
            raise AssertionError(f"duplicate stored PGN tag: {name}")
        tags[name] = _unescape_pgn_tag(encoded_value)
    return tags


def _first_meaningful(games: tuple[dict[str, str], ...], tag: str) -> tuple[int, str] | None:
    for index, game in enumerate(games):
        value = game.get(tag, "")
        if _is_meaningful_oracle_value(tag, value):
            return index, value.strip()
    return None


def _search_contains(
    service: GameSearchService,
    query: GameSearchQuery,
    source_index: int,
) -> bool:
    cursor: int | None = None
    for _ in range((EXPECTED_GAMES // 200) + 3):
        page = service.search(replace(query, after_game_id=cursor, limit=200))
        if any(item.source_index == source_index for item in page.items):
            return True
        if not page.has_more or page.next_after_game_id is None:
            return False
        cursor = page.next_after_game_id
    raise AssertionError("Library Search paging exceeded deterministic corpus bound")


def _roundtrip_all(rows: list[object], root: Path) -> tuple[int, list[dict[str, object]]]:
    checked = 0
    mismatches: list[dict[str, object]] = []
    for start in range(0, len(rows), ROUNDTRIP_CHUNK_SIZE):
        chunk_rows = rows[start : start + ROUNDTRIP_CHUNK_SIZE]
        before: list[PgnGame] = []
        source_indexes: list[int] = []
        for row in chunk_rows:
            game = parse_games(str(row["pgn_text"]))[0]  # type: ignore[index]
            before.append(game)
            source_indexes.append(int(row["source_index"]))  # type: ignore[index]
        export_path = root / f"metadata-roundtrip-{start:04d}.pgn"
        save_pgn_atomic(export_path, tuple(before))
        reopened = tuple(open_pgn(export_path).games)
        if len(reopened) != len(before):
            mismatches.append(
                {
                    "chunk_start": start,
                    "kind": "count",
                    "expected": len(before),
                    "actual": len(reopened),
                }
            )
            continue
        for offset, (expected, actual) in enumerate(zip(before, reopened)):
            checked += 1
            if not same_game_record(expected, actual) and len(mismatches) < 20:
                mismatches.append(
                    {
                        "source_index": source_indexes[offset],
                        "kind": "record_identity",
                    }
                )
    return checked, mismatches


def main() -> int:
    summary: dict[str, object] = {
        "authority_base_sha": os.environ.get("V2_METADATA_BASE_SHA"),
        "corpus": "TWIC 1134 CBV + independent TWIC PGN header oracle",
        "expected_games": EXPECTED_GAMES,
        "metadata_fields": list(MAPPED_FIELDS),
        "metadata_difference_counts": {field: 0 for field in MAPPED_FIELDS},
        "metadata_compared_counts": {field: 0 for field in MAPPED_FIELDS},
        "oracle_unavailable_counts": {field: 0 for field in MAPPED_FIELDS},
        "metadata_mismatch_examples": {field: [] for field in MAPPED_FIELDS},
        "search_filters": {},
        "export_reopen": "NOT_RUN",
        "provenance": "NOT_RUN",
        "acsdb_integrity": "NOT_RUN",
        "not_exposed_fields": list(chessbase_metadata_unavailable_fields()),
        "fatal_error": None,
    }
    verdict = 0

    try:
        cbv_path = Path(_require_env("UNCBV_FIXTURE"))
        pgn_path = Path(_require_env("TWIC_PGN_FIXTURE"))
        bridge = Path(_require_env("LIBCBH_BRIDGE"))
        uncbv = Path(_require_env("UNCBV_BINARY"))
        uncbv_sha = _require_env("UNCBV_BINARY_SHA256")
        cbv_sha = _require_env("TWIC_CBV_SHA256")

        oracle_games = _read_oracle_tags(pgn_path)
        summary["oracle_game_count"] = len(oracle_games)
        if len(oracle_games) != EXPECTED_GAMES:
            raise AssertionError(f"TWIC PGN count mismatch: {len(oracle_games)} != {EXPECTED_GAMES}")

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
                summary["decoded_game_count"] = report.decoded_game_count
                summary["imported_game_count"] = report.imported_game_count
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
                source_row = database.conn.execute(
                    "SELECT source_name, source_format, sha256 FROM sources WHERE id=?",
                    (source_id,),
                ).fetchone()
                if source_row is None:
                    raise AssertionError("published source row is missing")
                summary["source_id"] = source_id
                summary["original_source_name"] = cbv_path.name
                summary["original_source_sha256"] = cbv_sha
                summary["stored_source_name"] = str(source_row["source_name"])
                summary["stored_source_format"] = str(source_row["source_format"])
                summary["stored_source_sha256"] = str(source_row["sha256"])
                provenance_ok = (
                    str(source_row["source_name"]) == cbv_path.name
                    and str(source_row["sha256"]) == cbv_sha
                )

                rows = database.conn.execute(
                    "SELECT id, source_index, pgn_text, white, black, event, site, game_date, round, result, eco, opening "
                    "FROM games WHERE source_id=? ORDER BY source_index",
                    (source_id,),
                ).fetchall()
                rows = list(rows)
                if len(rows) != EXPECTED_GAMES:
                    raise AssertionError(f"ACSDB row count mismatch: {len(rows)}")
                contiguous = [int(row["source_index"]) for row in rows] == list(range(EXPECTED_GAMES))
                summary["source_index_range"] = [0, EXPECTED_GAMES - 1]
                summary["source_index_contiguous"] = contiguous
                provenance_ok = provenance_ok and contiguous
                summary["provenance"] = "PASS" if provenance_ok else "FAIL"
                if not provenance_ok:
                    verdict = 1

                difference_counts = {field: 0 for field in MAPPED_FIELDS}
                compared_counts = {field: 0 for field in MAPPED_FIELDS}
                unavailable_counts = {field: 0 for field in MAPPED_FIELDS}
                mismatch_examples: dict[str, list[dict[str, object]]] = {
                    field: [] for field in MAPPED_FIELDS
                }
                opening_oracle_present = 0
                opening_decoded_present = 0

                for index, row in enumerate(rows):
                    oracle = oracle_games[index]
                    actual_tags = _read_stored_tags(str(row["pgn_text"]))
                    for tag in MAPPED_FIELDS:
                        expected = oracle.get(tag, "")
                        if not _is_meaningful_oracle_value(tag, expected):
                            unavailable_counts[tag] += 1
                            continue
                        compared_counts[tag] += 1
                        actual = actual_tags.get(tag, "")
                        if not _metadata_equal(tag, expected, actual):
                            difference_counts[tag] += 1
                            if len(mismatch_examples[tag]) < MAX_MISMATCH_EXAMPLES_PER_FIELD:
                                mismatch_examples[tag].append(
                                    {
                                        "source_index": index,
                                        "expected": expected,
                                        "actual": actual,
                                    }
                                )
                    oracle_opening = oracle.get("Opening", "").strip()
                    decoded_opening = actual_tags.get("Opening", "").strip()
                    opening_oracle_present += int(bool(oracle_opening and oracle_opening != "?"))
                    opening_decoded_present += int(bool(decoded_opening and decoded_opening != "?"))

                summary["metadata_difference_counts"] = difference_counts
                summary["metadata_compared_counts"] = compared_counts
                summary["oracle_unavailable_counts"] = unavailable_counts
                summary["metadata_mismatch_examples"] = mismatch_examples
                summary["opening_oracle_present"] = opening_oracle_present
                summary["opening_decoded_present"] = opening_decoded_present
                if any(difference_counts.values()):
                    verdict = 1

                search = GameSearchService(database)
                search_filters: dict[str, str] = {}
                search_specs: list[tuple[str, str, str]] = []
                player_probe = _first_meaningful(oracle_games, "White") or _first_meaningful(oracle_games, "Black")
                if player_probe is not None:
                    index, value = player_probe
                    search_filters["player"] = "PASS" if _search_contains(
                        search, GameSearchQuery(player=value, source_id=source_id), index
                    ) else "FAIL"
                else:
                    search_filters["player"] = "NO_ORACLE_VALUE"
                for label, tag, query_field in (
                    ("event", "Event", "event"),
                    ("site", "Site", "site"),
                    ("game_date", "Date", "game_date"),
                    ("result", "Result", "result"),
                    ("eco", "ECO", "eco"),
                ):
                    probe = _first_meaningful(oracle_games, tag)
                    if probe is None:
                        search_filters[label] = "NO_ORACLE_VALUE"
                        continue
                    index, value = probe
                    kwargs = {query_field: value, "source_id": source_id}
                    search_filters[label] = "PASS" if _search_contains(
                        search, GameSearchQuery(**kwargs), index
                    ) else "FAIL"
                source_search = search.search(GameSearchQuery(source_name=cbv_path.name, limit=10))
                search_filters["source_name"] = "PASS" if any(
                    item.source_id == source_id for item in source_search.items
                ) else "FAIL"
                search_filters["round"] = "NOT_EXPOSED_BY_CURRENT_D07_QUERY"
                search_filters["white_elo"] = "NOT_EXPOSED_BY_CURRENT_D07_QUERY"
                search_filters["black_elo"] = "NOT_EXPOSED_BY_CURRENT_D07_QUERY"
                summary["search_filters"] = search_filters
                if any(value == "FAIL" for value in search_filters.values()):
                    verdict = 1

                checked, roundtrip_mismatches = _roundtrip_all(rows, root)
                summary["export_reopen_checked_games"] = checked
                summary["export_reopen_mismatch_examples"] = roundtrip_mismatches
                summary["export_reopen"] = (
                    "PASS" if checked == EXPECTED_GAMES and not roundtrip_mismatches else "FAIL"
                )
                if summary["export_reopen"] != "PASS":
                    verdict = 1

                quick_check = str(database.conn.execute("PRAGMA quick_check").fetchone()[0])
                summary["acsdb_integrity"] = "PASS" if quick_check.lower() == "ok" else f"FAIL:{quick_check}"
                if quick_check.lower() != "ok":
                    verdict = 1
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
        summary["capabilities"] = capability_rows
    except Exception as exc:
        verdict = 1
        summary["fatal_error"] = f"{type(exc).__name__}: {exc}"

    summary["overall_verdict"] = "PASS" if verdict == 0 else "FAIL"
    Path("chessbase-metadata-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return verdict


if __name__ == "__main__":
    raise SystemExit(main())
