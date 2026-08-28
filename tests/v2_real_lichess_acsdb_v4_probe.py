from __future__ import annotations

from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import random
import resource
import tempfile
import time
from urllib.request import Request, urlopen

import zstandard

from acs.acsdb import AcsDatabase
from acs.game_identity import same_game_tree
from acs.gametree import PgnGame, parse_games
from acs.library_import_service import LibraryImportService
from acs.pgn_service import open_pgn
from acs.search_service import GameSearchItem, GameSearchQuery, GameSearchService


CORPUS_NAME = "lichess-standard-rated-2013-01"
CORPUS_URL = "https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst"
CORPUS_SHA256 = "aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635"
CORPUS_LICENSE = "CC0"
CORPUS_PUBLISHED_GAMES = 121_332
SUBSET_GAMES = 10_000
SEARCH_PAGE_LIMIT = 200
DOWNLOAD_LIMIT_BYTES = 32 * 1024 * 1024
DOWNLOAD_CHUNK = 1024 * 1024
RANDOM_SEED = 20260828
SAMPLE_RANDOM_GAMES = 32


def _scan_comment_state(line: str, inside_brace: bool) -> bool:
    for character in line:
        if inside_brace:
            if character == "}":
                inside_brace = False
            continue
        if character == ";":
            break
        if character == "{":
            inside_brace = True
    return inside_brace


def _write_complete_game_subset(source: io.TextIOBase, destination: Path, limit: int) -> int:
    """Segment complete PGN records only; chess semantics remain Product-owned."""

    current: list[str] = []
    inside_brace = False
    written = 0
    with destination.open("w", encoding="utf-8", newline="\n") as output:
        for line in source:
            if not inside_brace and line.startswith('[Event "') and current:
                record = "".join(current).strip()
                if record:
                    output.write(record)
                    output.write("\n\n")
                    written += 1
                    if written >= limit:
                        return written
                current = [line]
                inside_brace = _scan_comment_state(line, False)
                continue
            current.append(line)
            inside_brace = _scan_comment_state(line, inside_brace)

        if current and written < limit:
            record = "".join(current).strip()
            if record:
                output.write(record)
                output.write("\n")
                written += 1
    return written


def _download_verified(destination: Path) -> int:
    request = Request(CORPUS_URL, headers={"User-Agent": "Accessible-Chess-Real-Library-QA/1"})
    digest = hashlib.sha256()
    total = 0
    try:
        response = urlopen(request, timeout=60)
    except Exception as exc:
        raise RuntimeError(f"real corpus download failed: {type(exc).__name__}") from exc

    with response, destination.open("wb") as output:
        while True:
            chunk = response.read(DOWNLOAD_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > DOWNLOAD_LIMIT_BYTES:
                raise RuntimeError("compressed Lichess corpus exceeds QA download bound")
            digest.update(chunk)
            output.write(chunk)

    actual = digest.hexdigest()
    if actual != CORPUS_SHA256:
        raise AssertionError(f"Lichess corpus digest mismatch: {actual}")
    return total


def _make_subset(compressed: Path, subset: Path) -> int:
    with compressed.open("rb") as source:
        reader = zstandard.ZstdDecompressor().stream_reader(source)
        with reader, io.TextIOWrapper(reader, encoding="utf-8", errors="strict", newline="") as text:
            return _write_complete_game_subset(text, subset, SUBSET_GAMES)


def _paginate_source(database: AcsDatabase, source_id: int) -> tuple[tuple[GameSearchItem, ...], int, float]:
    service = GameSearchService(database)
    items: list[GameSearchItem] = []
    cursor: int | None = None
    pages = 0
    started = time.perf_counter()

    while True:
        page = service.search(
            GameSearchQuery(
                source_id=source_id,
                after_game_id=cursor,
                limit=SEARCH_PAGE_LIMIT,
            )
        )
        pages += 1
        if page.items:
            if items and page.items[0].game_id <= items[-1].game_id:
                raise AssertionError("real Library keyset paging did not advance")
            items.extend(page.items)
        if not page.has_more:
            if page.next_after_game_id is not None:
                raise AssertionError("terminal real Library page published a cursor")
            break
        if page.next_after_game_id is None:
            raise AssertionError("non-terminal real Library page omitted a cursor")
        if cursor is not None and page.next_after_game_id <= cursor:
            raise AssertionError("real Library keyset cursor did not advance")
        cursor = page.next_after_game_id

    return tuple(items), pages, time.perf_counter() - started


def _non_ascii(value: str | None) -> bool:
    return bool(value and any(ord(character) > 127 for character in value))


def _real_unicode_query(games: tuple[PgnGame, ...]) -> tuple[int, str, str] | None:
    # Prefer player names because a full-name player search normally has a small result set.
    fields = (("White", "player"), ("Black", "player"), ("Event", "event"), ("ECO", "eco"), ("Opening", "opening"))
    for index, game in enumerate(games):
        for tag, query_field in fields:
            value = game.tags.get(tag)
            if _non_ascii(value):
                assert value is not None
                return index, query_field, value
    return None


def _real_literal_query(games: tuple[PgnGame, ...]) -> tuple[int, str, str] | None:
    fields = (("White", "player"), ("Black", "player"), ("Event", "event"), ("ECO", "eco"), ("Opening", "opening"))
    for index, game in enumerate(games):
        for tag, query_field in fields:
            value = game.tags.get(tag)
            if value and any(marker in value for marker in ("%", "_", "\\")):
                return index, query_field, value
    return None


def _search_for_value(database: AcsDatabase, source_id: int, field: str, value: str) -> tuple[tuple[GameSearchItem, ...], float]:
    kwargs: dict[str, object] = {field: value, "source_id": source_id, "limit": SEARCH_PAGE_LIMIT}
    started = time.perf_counter()
    page = GameSearchService(database).search(GameSearchQuery(**kwargs))
    return page.items, time.perf_counter() - started


def _sample_indexes(total: int) -> tuple[int, ...]:
    if total < 2:
        return tuple(range(total))
    rng = random.Random(RANDOM_SEED)
    candidates = list(range(1, total - 1))
    count = min(SAMPLE_RANDOM_GAMES, len(candidates))
    return tuple(sorted({0, total - 1, *rng.sample(candidates, count)}))


def _assert_projection_integrity(database: AcsDatabase, expected_games: int) -> dict[str, int | str]:
    quick = str(database.conn.execute("PRAGMA quick_check").fetchone()[0])
    if quick != "ok":
        raise AssertionError(f"SQLite quick_check failed: {quick}")
    if database.conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise AssertionError("ACSDB foreign-key integrity failed")

    game_count = int(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
    fold_count = int(database.conn.execute("SELECT COUNT(*) FROM game_search_fold").fetchone()[0])
    missing_fold = int(
        database.conn.execute(
            """SELECT COUNT(*) FROM games AS g
               LEFT JOIN game_search_fold AS sf ON sf.game_id=g.id
               WHERE sf.game_id IS NULL"""
        ).fetchone()[0]
    )
    orphan_fold = int(
        database.conn.execute(
            """SELECT COUNT(*) FROM game_search_fold AS sf
               LEFT JOIN games AS g ON g.id=sf.game_id
               WHERE g.id IS NULL"""
        ).fetchone()[0]
    )
    if game_count != expected_games or fold_count != expected_games or missing_fold or orphan_fold:
        raise AssertionError(
            f"ACSDB v4 projection count mismatch games={game_count} fold={fold_count} "
            f"missing={missing_fold} orphan={orphan_fold}"
        )
    return {
        "quick_check": quick,
        "games": game_count,
        "search_fold_rows": fold_count,
        "missing_search_fold_rows": missing_fold,
        "orphan_search_fold_rows": orphan_fold,
    }


def _warning_stats(games: tuple[PgnGame, ...]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for game in games:
        for warning in game.warnings:
            counts[warning.split(":", 1)[0]] += 1
    return dict(sorted(counts.items()))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="accessible-chess-real-acsdb-v4-") as temporary:
        root = Path(temporary)
        compressed = root / "lichess.pgn.zst"
        subset = root / "lichess-first-10000.pgn"
        database_path = root / "library.acsdb"

        compressed_bytes = _download_verified(compressed)
        segmented = _make_subset(compressed, subset)
        if segmented != SUBSET_GAMES:
            raise AssertionError(f"expected {SUBSET_GAMES} complete games, got {segmented}")

        parse_started = time.perf_counter()
        opened = open_pgn(subset)
        parse_seconds = time.perf_counter() - parse_started
        games = opened.games
        if len(games) != SUBSET_GAMES:
            raise AssertionError(f"Product parser returned {len(games)} games")
        if opened.global_warnings:
            raise AssertionError(f"unexpected global PGN warnings: {opened.global_warnings}")

        unicode_case = _real_unicode_query(games)
        if unicode_case is None:
            raise AssertionError("10k real corpus contains no Unicode metadata in v4 searchable fields")
        literal_case = _real_literal_query(games)

        database = AcsDatabase(database_path)
        try:
            if database.schema_version != 4:
                raise AssertionError(f"expected ACSDB v4, got {database.schema_version}")

            import_started = time.perf_counter()
            result = LibraryImportService(database).import_games(
                games,
                source_name=f"{CORPUS_NAME}-first-{SUBSET_GAMES}.pgn",
                source_format="pgn",
                source_sha256=opened.source.sha256,
                source_warning_count=len(opened.global_warnings),
            )
            import_seconds = time.perf_counter() - import_started
            if result.game_count != SUBSET_GAMES:
                raise AssertionError(f"Library imported {result.game_count} games")

            integrity_before = _assert_projection_integrity(database, SUBSET_GAMES)
            items, page_count, enumerate_seconds = _paginate_source(database, result.source_id)
            if len(items) != SUBSET_GAMES:
                raise AssertionError(f"public Search enumerated {len(items)} games")
            indexes = [item.source_index for item in items]
            if indexes != list(range(SUBSET_GAMES)):
                raise AssertionError("public Search source_index sequence is not contiguous")
            item_by_source_index = {item.source_index: item for item in items}

            unicode_index, unicode_field, unicode_value = unicode_case
            unicode_probe_value = unicode_value.swapcase()
            unicode_items, unicode_seconds = _search_for_value(
                database, result.source_id, unicode_field, unicode_probe_value
            )
            if unicode_index not in {item.source_index for item in unicode_items}:
                raise AssertionError(
                    f"real Unicode {unicode_field} search did not find source index {unicode_index}"
                )

            literal_evidence: dict[str, object]
            if literal_case is not None:
                literal_index, literal_field, literal_value = literal_case
                literal_items, literal_seconds = _search_for_value(
                    database, result.source_id, literal_field, literal_value
                )
                if literal_index not in {item.source_index for item in literal_items}:
                    raise AssertionError(
                        f"real literal {literal_field} search did not find source index {literal_index}"
                    )
                literal_evidence = {
                    "observed": True,
                    "field": literal_field,
                    "value": literal_value,
                    "source_index": literal_index,
                    "elapsed_seconds": literal_seconds,
                }
            else:
                literal_evidence = {"observed": False}

            sample_results: list[dict[str, object]] = []
            for source_index in _sample_indexes(SUBSET_GAMES):
                item = item_by_source_index[source_index]
                row = database.get_game(item.game_id)
                if row is None:
                    raise AssertionError(f"missing stored game for source index {source_index}")
                stored = parse_games(row["pgn_text"])[0]
                reference = games[source_index]
                if stored.tags != reference.tags:
                    raise AssertionError(f"stored tags mismatch at source index {source_index}")
                if not same_game_tree(stored, reference):
                    raise AssertionError(f"stored GameTree mismatch at source index {source_index}")
                sample_results.append(
                    {
                        "source_index": source_index,
                        "game_id": item.game_id,
                        "white": item.white,
                        "black": item.black,
                        "event": item.event,
                        "result": item.result,
                    }
                )

            source_row = database.conn.execute(
                "SELECT source_name, source_format, sha256 FROM sources WHERE id=?",
                (result.source_id,),
            ).fetchone()
            if source_row is None:
                raise AssertionError("real Library source provenance row missing")
            if str(source_row["sha256"]) != opened.source.sha256:
                raise AssertionError("real Library subset provenance hash mismatch")
        finally:
            database.close()

        database_bytes_after_close = database_path.stat().st_size
        reopened = AcsDatabase(database_path)
        try:
            integrity_after = _assert_projection_integrity(reopened, SUBSET_GAMES)
            reopened_items, reopened_pages, reopened_enumerate_seconds = _paginate_source(
                reopened, result.source_id
            )
            if len(reopened_items) != SUBSET_GAMES:
                raise AssertionError("reopened public Search count mismatch")
            replay_unicode_items, _ = _search_for_value(
                reopened, result.source_id, unicode_field, unicode_probe_value
            )
            if unicode_index not in {item.source_index for item in replay_unicode_items}:
                raise AssertionError("reopened real Unicode Search mismatch")
        finally:
            reopened.close()

        peak_rss_kib = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        summary = {
            "status": "PASS",
            "product_candidate": "PR311@c26099870bbdc70a60cfb9aaf6bde59f447e490c",
            "corpus": {
                "name": CORPUS_NAME,
                "url": CORPUS_URL,
                "license": CORPUS_LICENSE,
                "published_games": CORPUS_PUBLISHED_GAMES,
                "compressed_sha256": CORPUS_SHA256,
                "compressed_bytes": compressed_bytes,
                "subset_games": SUBSET_GAMES,
                "subset_sha256": opened.source.sha256,
                "subset_bytes": opened.source.size,
            },
            "parser": {
                "games": len(games),
                "warning_games": opened.warning_games,
                "warning_classes": _warning_stats(games),
                "elapsed_seconds": parse_seconds,
            },
            "library": {
                "attempt_id": result.attempt_id,
                "source_id": result.source_id,
                "game_count": result.game_count,
                "warning_count": result.warning_count,
                "first_game_id": result.first_game_id,
                "last_game_id": result.last_game_id,
                "import_seconds": import_seconds,
                "keyset_pages": page_count,
                "enumerate_seconds": enumerate_seconds,
                "reopened_keyset_pages": reopened_pages,
                "reopened_enumerate_seconds": reopened_enumerate_seconds,
                "database_bytes_after_close": database_bytes_after_close,
                "peak_rss_kib_linux": peak_rss_kib,
            },
            "real_unicode_search": {
                "source_index": unicode_index,
                "field": unicode_field,
                "source_value": unicode_value,
                "query_value": unicode_probe_value,
                "elapsed_seconds": unicode_seconds,
                "status": "PASS",
            },
            "real_literal_metachar_search": literal_evidence,
            "integrity_before_close": integrity_before,
            "integrity_after_reopen": integrity_after,
            "sample_seed": RANDOM_SEED,
            "sampled_game_count": len(sample_results),
            "sampled_games": sample_results,
            "stored_tags_and_gametrees": "PASS",
            "public_search_full_enumeration": "PASS",
            "reopen": "PASS",
            "nonclaims": [
                "not a million-game readiness benchmark",
                "does not repair or close known PR311 position-write P1 findings",
                "does not independently re-claim PGN parser semantics owned by PGN-03",
                "does not provide Windows/NVDA acceptance",
            ],
        }
        Path("real-lichess-acsdb-v4-summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print("V2_REAL_LICHESS_ACSDB_V4=" + json.dumps(summary, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
