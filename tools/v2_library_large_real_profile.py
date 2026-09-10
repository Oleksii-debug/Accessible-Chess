from __future__ import annotations

"""Real-corpus large Library profile for D07 schema-v6.

This is evidence, not a second importer or search implementation. It downloads one
previously qualified CC0 Lichess source, parses complete games through the canonical
PGN service in bounded chunks, then exercises the canonical LibraryImportService,
GameSearchService, ACSDB reopen/open-game path, and PGN export service.

Wall-clock values are recorded for comparison but are never used as absolute pass/fail
thresholds. Correctness, integrity, paging, atomic cancellation, and corpus identity
are the gates.
"""

from dataclasses import dataclass
import cProfile
import hashlib
import io
import json
from pathlib import Path
import pstats
import statistics
import subprocess
import tempfile
import time
from typing import Iterator
from urllib.request import Request, urlopen

import zstandard

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.game_identity import same_game_tree
from acs.gametree import PgnGame, parse_games
from acs.library_import_service import (
    LibraryImportCancelledError,
    LibraryImportProgress,
    LibraryImportService,
)
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.search_service import GameSearchPage, GameSearchQuery, GameSearchService


@dataclass(frozen=True, slots=True)
class CorpusSpec:
    name: str
    url: str
    sha256: str
    license: str
    published_games: int


STANDARD = CorpusSpec(
    name="lichess-standard-rated-2013-01",
    url="https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst",
    sha256="aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635",
    license="CC0",
    published_games=121_332,
)

TARGET_GAMES = 100_001
PARSE_CHUNK_GAMES = 5_000
PAGE_LIMIT = 200
EXPORT_GAMES = 100
CANCEL_AFTER_GAMES = 1_000
CANCEL_BATCH_GAMES = 5_000
PROFILE_GAMES = 2_000
SEARCH_REPEATS = 5
DOWNLOAD_LIMIT = 32 * 1024 * 1024
DOWNLOAD_CHUNK = 1024 * 1024


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _rss_peak_bytes() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value * 1024


def _scan_comment_state(line: str, inside_brace: bool) -> bool:
    for char in line:
        if inside_brace:
            if char == "}":
                inside_brace = False
        elif char == ";":
            break
        elif char == "{":
            inside_brace = True
    return inside_brace


def _records(stream: io.TextIOBase, limit: int) -> Iterator[tuple[int, str]]:
    """Split only on complete Event-tag boundaries, matching prior real-corpus QA."""
    current: list[str] = []
    in_brace = False
    ordinal = 0
    for line in stream:
        if current and not in_brace and line.startswith('[Event "'):
            record = "".join(current).strip()
            if record:
                yield ordinal, record + "\n"
                ordinal += 1
                if ordinal >= limit:
                    return
            current = [line]
            in_brace = _scan_comment_state(line, False)
            continue
        current.append(line)
        in_brace = _scan_comment_state(line, in_brace)
    if current and ordinal < limit:
        record = "".join(current).strip()
        if record:
            yield ordinal, record + "\n"


def _download(spec: CorpusSpec, destination: Path) -> int:
    request = Request(
        spec.url,
        headers={"User-Agent": "Accessible-Chess-D07-Large-Real-Performance/1"},
    )
    digest = hashlib.sha256()
    total = 0
    response = urlopen(request, timeout=60)
    with response, destination.open("wb") as output:
        while True:
            chunk = response.read(DOWNLOAD_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > DOWNLOAD_LIMIT:
                raise RuntimeError("compressed corpus exceeds bounded profile download")
            digest.update(chunk)
            output.write(chunk)
    actual = digest.hexdigest()
    if actual != spec.sha256:
        raise AssertionError(f"corpus digest mismatch: {actual}")
    return total


def _open_zstd(path: Path):
    raw = path.open("rb")
    reader = zstandard.ZstdDecompressor().stream_reader(raw, closefd=False)
    text = io.TextIOWrapper(reader, encoding="utf-8", errors="strict", newline="")
    return raw, text


def _close_zstd(raw, text) -> None:
    try:
        text.close()
    finally:
        raw.close()


def _parse_real_subset(
    compressed: Path,
    root: Path,
    *,
    limit: int,
) -> tuple[tuple[PgnGame, ...], str, int, float, int, int]:
    """Parse a >64 MiB logical source via bounded canonical PGN-file chunks."""
    started = time.perf_counter()
    digest = hashlib.sha256()
    normalized_bytes = 0
    global_warning_count = 0
    warning_games = 0
    games: list[PgnGame] = []
    raw, text = _open_zstd(compressed)
    chunk_path = root / "parse-chunk.pgn"
    chunk_records: list[str] = []

    def flush() -> None:
        nonlocal global_warning_count, warning_games
        if not chunk_records:
            return
        payload = "\n".join(record.rstrip("\n") for record in chunk_records) + "\n"
        chunk_path.write_text(payload, encoding="utf-8", newline="\n")
        opened = open_pgn(chunk_path)
        if len(opened.games) != len(chunk_records):
            raise AssertionError(
                f"canonical chunk parser returned {len(opened.games)} games "
                f"for {len(chunk_records)} complete records"
            )
        global_warning_count += len(opened.global_warnings)
        warning_games += opened.warning_games
        base = len(games)
        for offset, game in enumerate(opened.games):
            game.source_index = base + offset
            games.append(game)
        chunk_records.clear()

    try:
        for ordinal, record in _records(text, limit):
            encoded = record.encode("utf-8")
            digest.update(encoded)
            normalized_bytes += len(encoded)
            chunk_records.append(record)
            if len(chunk_records) >= PARSE_CHUNK_GAMES:
                flush()
            if ordinal + 1 >= limit:
                break
        flush()
    finally:
        _close_zstd(raw, text)
        if chunk_path.exists():
            chunk_path.unlink()

    if len(games) != limit:
        raise AssertionError(f"expected {limit} real games, parsed {len(games)}")
    return (
        tuple(games),
        digest.hexdigest(),
        normalized_bytes,
        time.perf_counter() - started,
        global_warning_count,
        warning_games,
    )


def _path_bytes(path: Path) -> int:
    total = 0
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        if candidate.exists():
            total += candidate.stat().st_size
    return total


def _median_seconds(callable_) -> tuple[object, float, tuple[float, ...]]:
    first = callable_()
    samples: list[float] = []
    last = first
    for _ in range(SEARCH_REPEATS):
        started = time.perf_counter()
        last = callable_()
        samples.append(time.perf_counter() - started)
    return last, statistics.median(samples), tuple(samples)


def _first_nonblank(
    database: AcsDatabase,
    source_id: int,
    column: str,
    *,
    complete_date: bool = False,
) -> tuple[int, str]:
    predicate = f"{column} IS NOT NULL AND TRIM({column})<>''"
    if complete_date:
        predicate += " AND search_date_key(game_date) IS NOT NULL"
    row = database.conn.execute(
        f"SELECT id, {column} FROM games "
        f"WHERE source_id=? AND {predicate} ORDER BY id LIMIT 1",
        (source_id,),
    ).fetchone()
    if row is None:
        raise AssertionError(f"real corpus did not expose required {column} metadata")
    return int(row[0]), str(row[1])


def _search_measurement(
    service: GameSearchService,
    query: GameSearchQuery,
    *,
    expected_game_id: int | None = None,
) -> dict[str, object]:
    page, median, samples = _median_seconds(lambda: service.search(query))
    assert isinstance(page, GameSearchPage)
    if expected_game_id is not None and expected_game_id not in {
        item.game_id for item in page.items
    }:
        raise AssertionError("real metadata query did not return its source game")
    return {
        "median_seconds": median,
        "samples_seconds": samples,
        "returned": len(page.items),
        "has_more": page.has_more,
    }


def _page_all(
    service: GameSearchService,
    source_id: int,
) -> tuple[int, int, float]:
    cursor: int | None = None
    seen = 0
    pages = 0
    previous = 0
    started = time.perf_counter()
    while True:
        page = service.search(
            GameSearchQuery(
                source_id=source_id,
                after_game_id=cursor,
                limit=PAGE_LIMIT,
            )
        )
        pages += 1
        for item in page.items:
            if item.game_id <= previous:
                raise AssertionError("keyset paging did not advance strictly")
            previous = item.game_id
            seen += 1
        if not page.has_more:
            if page.next_after_game_id is not None:
                raise AssertionError("terminal page unexpectedly exposed a cursor")
            break
        if page.next_after_game_id is None:
            raise AssertionError("non-terminal page omitted its cursor")
        cursor = page.next_after_game_id
    return seen, pages, time.perf_counter() - started


def _open_game_measurement(
    database: AcsDatabase,
    game_id: int,
) -> dict[str, object]:
    def open_one():
        row = database.get_game(game_id)
        if row is None:
            raise AssertionError("profile target game disappeared")
        parsed = parse_games(row["pgn_text"])
        if len(parsed) != 1:
            raise AssertionError("stored canonical PGN did not reopen as one game")
        return parsed[0]

    game, median, samples = _median_seconds(open_one)
    assert isinstance(game, PgnGame)
    return {
        "median_seconds": median,
        "samples_seconds": samples,
        "game_id": game_id,
    }


def _export_measurement(
    database: AcsDatabase,
    source_id: int,
    destination: Path,
) -> dict[str, object]:
    page = GameSearchService(database).search(
        GameSearchQuery(source_id=source_id, limit=EXPORT_GAMES)
    )
    if len(page.items) != EXPORT_GAMES:
        raise AssertionError("could not select bounded real export sample")
    games: list[PgnGame] = []
    for item in page.items:
        row = database.get_game(item.game_id)
        if row is None:
            raise AssertionError("export sample game disappeared")
        parsed = parse_games(row["pgn_text"])
        if len(parsed) != 1:
            raise AssertionError("export sample stored PGN was not one game")
        games.append(parsed[0])

    started = time.perf_counter()
    save_pgn_atomic(destination, games)
    reopened = open_pgn(destination)
    elapsed = time.perf_counter() - started
    if len(reopened.games) != len(games):
        raise AssertionError("export/reopen sample count mismatch")
    for expected, actual in zip(games, reopened.games):
        if expected.tags != actual.tags or not same_game_tree(expected, actual):
            raise AssertionError("export/reopen changed canonical real game")
    return {
        "games": len(games),
        "elapsed_seconds": elapsed,
        "bytes": destination.stat().st_size,
        "status": "PASS",
    }


def _cancel_measurement(
    database: AcsDatabase,
    games: tuple[PgnGame, ...],
    *,
    source_sha256: str,
    expected_durable_games: int,
) -> dict[str, object]:
    requested_at: float | None = None

    def progress(item: LibraryImportProgress) -> None:
        nonlocal requested_at
        if item.processed_games >= CANCEL_AFTER_GAMES and requested_at is None:
            requested_at = time.perf_counter()

    def cancel() -> bool:
        return requested_at is not None

    started = time.perf_counter()
    try:
        LibraryImportService(database).import_games(
            games[:CANCEL_BATCH_GAMES],
            source_name="cancel-latency-real-subset.pgn",
            source_format="pgn",
            source_sha256=source_sha256,
            cancel_check=cancel,
            progress_callback=progress,
        )
    except LibraryImportCancelledError:
        caught_at = time.perf_counter()
    else:
        raise AssertionError("requested cancellation did not stop the import")

    if requested_at is None:
        raise AssertionError("cancellation request point was never reached")
    durable_games = int(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
    if durable_games != expected_durable_games:
        raise AssertionError("cancelled batch published partial games")
    attempt = database.list_import_attempts(limit=1)[0]
    if attempt["status"] != "failed" or attempt["source_id"] is not None:
        raise AssertionError("cancelled batch did not retain a sanitized failed attempt")
    return {
        "request_after_games": CANCEL_AFTER_GAMES,
        "batch_games": CANCEL_BATCH_GAMES,
        "request_to_exception_seconds": caught_at - requested_at,
        "call_elapsed_seconds": caught_at - started,
        "durable_game_count_after": durable_games,
        "status": "PASS",
    }


def _profile_import_hot_path(
    games: tuple[PgnGame, ...],
    *,
    root: Path,
    source_sha256: str,
) -> dict[str, object]:
    profile_db = root / "profile-sample.acsdb"
    profiler = cProfile.Profile()
    database = AcsDatabase(profile_db)
    try:
        profiler.enable()
        started = time.perf_counter()
        LibraryImportService(database).import_games(
            games[:PROFILE_GAMES],
            source_name="real-profile-sample.pgn",
            source_format="pgn",
            source_sha256=source_sha256,
        )
        elapsed = time.perf_counter() - started
        profiler.disable()
    finally:
        database.close()

    report = io.StringIO()
    pstats.Stats(profiler, stream=report).strip_dirs().sort_stats("cumulative").print_stats(25)
    return {
        "games": PROFILE_GAMES,
        "elapsed_seconds": elapsed,
        "games_per_second": PROFILE_GAMES / elapsed,
        "top_cumulative": report.getvalue(),
    }


def _integrity(database: AcsDatabase, expected_games: int) -> dict[str, object]:
    started = time.perf_counter()
    version = database.verify_integrity()
    elapsed = time.perf_counter() - started
    if version != ACSDB_SCHEMA_VERSION:
        raise AssertionError(f"integrity returned schema {version}")
    games = int(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
    folds = int(database.conn.execute("SELECT COUNT(*) FROM game_search_fold").fetchone()[0])
    dirty = int(database.conn.execute("SELECT COUNT(*) FROM game_search_fold_dirty").fetchone()[0])
    if (games, folds, dirty) != (expected_games, expected_games, 0):
        raise AssertionError(
            f"canonical/derivative mismatch games={games} folds={folds} dirty={dirty}"
        )
    return {
        "schema": version,
        "games": games,
        "search_fold_rows": folds,
        "dirty_rows": dirty,
        "verify_seconds": elapsed,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="accessible-chess-d07-large-real-") as raw_root:
        root = Path(raw_root)
        compressed = root / "standard.pgn.zst"
        database_path = root / "library.acsdb"
        export_path = root / "export-sample.pgn"

        baseline_rss = _rss_peak_bytes()
        compressed_bytes = _download(STANDARD, compressed)
        (
            games,
            subset_sha256,
            subset_bytes,
            parse_seconds,
            global_warning_count,
            warning_games,
        ) = _parse_real_subset(compressed, root, limit=TARGET_GAMES)
        after_parse_rss = _rss_peak_bytes()

        hot_path = _profile_import_hot_path(
            games,
            root=root,
            source_sha256=subset_sha256,
        )

        create_started = time.perf_counter()
        database = AcsDatabase(database_path)
        create_seconds = time.perf_counter() - create_started
        try:
            import_started = time.perf_counter()
            result = LibraryImportService(database).import_games(
                games,
                source_name=f"{STANDARD.name}-first-{TARGET_GAMES}.pgn",
                source_format="pgn",
                source_sha256=subset_sha256,
                source_warning_count=global_warning_count,
            )
            import_seconds = time.perf_counter() - import_started
            after_import_rss = _rss_peak_bytes()
            if result.game_count != TARGET_GAMES:
                raise AssertionError("Library import count mismatch")
            integrity_before = _integrity(database, TARGET_GAMES)
            disk_live_bytes = _path_bytes(database_path)
        finally:
            database.close()

        disk_closed_bytes = _path_bytes(database_path)
        reopen_started = time.perf_counter()
        reopened = AcsDatabase(database_path)
        reopen_seconds = time.perf_counter() - reopen_started
        try:
            service = GameSearchService(reopened)

            player_game_id, player = _first_nonblank(reopened, result.source_id, "white")
            event_game_id, event = _first_nonblank(reopened, result.source_id, "event")
            date_game_id, game_date = _first_nonblank(
                reopened, result.source_id, "game_date", complete_date=True
            )
            eco_game_id, eco = _first_nonblank(reopened, result.source_id, "eco")

            player_search = _search_measurement(
                service,
                GameSearchQuery(
                    player=player,
                    source_id=result.source_id,
                    limit=PAGE_LIMIT,
                ),
                expected_game_id=player_game_id,
            )
            event_search = _search_measurement(
                service,
                GameSearchQuery(
                    event=event,
                    source_id=result.source_id,
                    limit=PAGE_LIMIT,
                ),
                expected_game_id=event_game_id,
            )
            exact_date_search = _search_measurement(
                service,
                GameSearchQuery(
                    game_date=game_date,
                    source_id=result.source_id,
                    limit=PAGE_LIMIT,
                ),
                expected_game_id=date_game_id,
            )
            range_date_search = _search_measurement(
                service,
                GameSearchQuery(
                    date_from=game_date,
                    date_to=game_date,
                    source_id=result.source_id,
                    limit=PAGE_LIMIT,
                ),
                expected_game_id=date_game_id,
            )
            eco_search = _search_measurement(
                service,
                GameSearchQuery(
                    eco=eco,
                    source_id=result.source_id,
                    limit=PAGE_LIMIT,
                ),
                expected_game_id=eco_game_id,
            )

            seen, pages, paging_seconds = _page_all(service, result.source_id)
            if seen != TARGET_GAMES:
                raise AssertionError(f"keyset paging saw {seen}, expected {TARGET_GAMES}")

            middle = reopened.conn.execute(
                "SELECT id FROM games WHERE source_id=? AND source_index=?",
                (result.source_id, TARGET_GAMES // 2),
            ).fetchone()
            if middle is None:
                raise AssertionError("middle real game was not persisted")
            open_game = _open_game_measurement(reopened, int(middle[0]))

            export_subset = _export_measurement(reopened, result.source_id, export_path)
            cancellation = _cancel_measurement(
                reopened,
                games,
                source_sha256=subset_sha256,
                expected_durable_games=TARGET_GAMES,
            )
            integrity_after = _integrity(reopened, TARGET_GAMES)
        finally:
            reopened.close()

        summary = {
            "status": "PASS",
            "phase": "baseline-profile",
            "product_sha": _git_head(),
            "schema": ACSDB_SCHEMA_VERSION,
            "corpus": {
                "name": STANDARD.name,
                "license": STANDARD.license,
                "published_games": STANDARD.published_games,
                "compressed_sha256": STANDARD.sha256,
                "compressed_bytes": compressed_bytes,
                "profile_games": TARGET_GAMES,
                "normalized_subset_sha256": subset_sha256,
                "normalized_subset_bytes": subset_bytes,
                "global_warning_count": global_warning_count,
                "warning_games": warning_games,
            },
            "timing": {
                "database_create_seconds": create_seconds,
                "parse_seconds": parse_seconds,
                "import_seconds": import_seconds,
                "import_games_per_second": TARGET_GAMES / import_seconds,
                "reopen_seconds": reopen_seconds,
                "paging_seconds": paging_seconds,
                "paging_pages": pages,
            },
            "memory": {
                "baseline_peak_rss_bytes": baseline_rss,
                "after_parse_peak_rss_bytes": after_parse_rss,
                "after_import_peak_rss_bytes": after_import_rss,
            },
            "disk": {
                "live_db_wal_shm_bytes": disk_live_bytes,
                "closed_db_wal_shm_bytes": disk_closed_bytes,
                "closed_bytes_per_game": disk_closed_bytes / TARGET_GAMES,
            },
            "search": {
                "player": {"value": player, **player_search},
                "event": {"value": event, **event_search},
                "date_exact": {"value": game_date, **exact_date_search},
                "date_range_single_day": {"value": game_date, **range_date_search},
                "eco": {"value": eco, **eco_search},
            },
            "opening_game": open_game,
            "export_subset": export_subset,
            "cancellation": cancellation,
            "integrity_before_close": integrity_before,
            "integrity_after_reopen": integrity_after,
            "hot_path_profile": hot_path,
            "nonclaims": [
                "wall-clock values are evidence, not absolute CI thresholds",
                "not a 500k/1M claim",
                "not a new PGN parser or second search implementation",
                "not Windows/NVDA release acceptance",
            ],
        }
        Path("v2-library-large-real-profile.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(
            "V2_LIBRARY_LARGE_REAL_PROFILE="
            + json.dumps(summary, sort_keys=True, ensure_ascii=False)
        )


if __name__ == "__main__":
    main()
