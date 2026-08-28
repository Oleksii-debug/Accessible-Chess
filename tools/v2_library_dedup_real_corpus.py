from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
from urllib.request import Request, urlopen

import zstandard

from acs.acsdb import AcsDatabase
from acs.library_import_service import LibraryImportService
from acs.pgn_service import open_pgn
from acs.search_service import GameSearchQuery, GameSearchService


CORPUS_NAME = "lichess-standard-rated-2013-01"
CORPUS_URL = "https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst"
CORPUS_SHA256 = "aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635"
CORPUS_LICENSE = "CC0"
CORPUS_PUBLISHED_GAMES = 121_332
SUBSET_GAMES = 5_000
DOWNLOAD_LIMIT_BYTES = 32 * 1024 * 1024
DOWNLOAD_CHUNK = 1024 * 1024
PAGE_LIMIT = 200


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
    """Transport-frame complete Event-delimited records; Product owns PGN semantics."""

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
    request = Request(CORPUS_URL, headers={"User-Agent": "Accessible-Chess-D07-Dedupe-QA/1"})
    digest = hashlib.sha256()
    total = 0
    response = urlopen(request, timeout=60)
    with response, destination.open("wb") as output:
        while True:
            chunk = response.read(DOWNLOAD_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > DOWNLOAD_LIMIT_BYTES:
                raise RuntimeError("compressed Lichess corpus exceeds D07 QA download bound")
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


def _enumerate_source(database: AcsDatabase, source_id: int) -> tuple[int, int]:
    service = GameSearchService(database)
    count = 0
    pages = 0
    cursor: int | None = None
    while True:
        page = service.search(
            GameSearchQuery(source_id=source_id, after_game_id=cursor, limit=PAGE_LIMIT)
        )
        pages += 1
        count += len(page.items)
        if not page.has_more:
            if page.next_after_game_id is not None:
                raise AssertionError("terminal Library page unexpectedly published a cursor")
            return count, pages
        if page.next_after_game_id is None:
            raise AssertionError("non-terminal Library page omitted keyset cursor")
        if cursor is not None and page.next_after_game_id <= cursor:
            raise AssertionError("Library keyset cursor did not advance")
        cursor = page.next_after_game_id


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="accessible-chess-dedupe-real-") as temporary:
        root = Path(temporary)
        compressed = root / "lichess.pgn.zst"
        subset = root / "lichess-first-5000.pgn"
        database_path = root / "library.acsdb"

        compressed_bytes = _download_verified(compressed)
        segmented = _make_subset(compressed, subset)
        if segmented != SUBSET_GAMES:
            raise AssertionError(f"expected {SUBSET_GAMES} complete games, got {segmented}")

        opened = open_pgn(subset)
        if len(opened.games) != SUBSET_GAMES:
            raise AssertionError(f"canonical Product parser returned {len(opened.games)} games")
        if opened.global_warnings:
            raise AssertionError(f"unexpected global PGN warnings: {opened.global_warnings}")

        with AcsDatabase(database_path) as database:
            service = LibraryImportService(database)
            started = time.perf_counter()
            first = service.import_games(
                opened.games,
                source_name=f"{CORPUS_NAME}-first-{SUBSET_GAMES}.pgn",
                source_format="pgn",
                source_sha256=opened.source.sha256,
            )
            first_seconds = time.perf_counter() - started
            if first.reused:
                raise AssertionError("first real source import was incorrectly classified as reused")

            started = time.perf_counter()
            second = service.import_games(
                opened.games,
                source_name=f"renamed-{CORPUS_NAME}-first-{SUBSET_GAMES}.pgn",
                source_format="PGN",
                source_sha256=opened.source.sha256.upper(),
            )
            reuse_seconds = time.perf_counter() - started
            if not second.reused:
                raise AssertionError("second identical real source import was republished")
            if second.source_id != first.source_id:
                raise AssertionError("reused real source changed source identity")

            source_count = int(database.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
            game_count = int(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
            attempt_count = int(database.conn.execute("SELECT COUNT(*) FROM import_attempts").fetchone()[0])
            if (source_count, game_count, attempt_count) != (1, SUBSET_GAMES, 2):
                raise AssertionError(
                    f"real repeated import counts mismatch: sources={source_count} games={game_count} attempts={attempt_count}"
                )
            search_count, search_pages = _enumerate_source(database, first.source_id)
            if search_count != SUBSET_GAMES:
                raise AssertionError(f"public Search enumerated {search_count} real games")
            integrity_before = database.verify_integrity()

        database_bytes = database_path.stat().st_size
        with AcsDatabase(database_path) as reopened:
            source_count_after = int(reopened.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
            game_count_after = int(reopened.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
            attempt_count_after = int(reopened.conn.execute("SELECT COUNT(*) FROM import_attempts").fetchone()[0])
            if (source_count_after, game_count_after, attempt_count_after) != (1, SUBSET_GAMES, 2):
                raise AssertionError("reopened real repeated-import counts changed")
            reopened_count, reopened_pages = _enumerate_source(reopened, first.source_id)
            if reopened_count != SUBSET_GAMES:
                raise AssertionError("reopened real Search count mismatch")
            integrity_after = reopened.verify_integrity()

        summary = {
            "status": "PASS",
            "product_candidate": "work/v2-library-dedup-provenance-20260828",
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
            "first_import_seconds": first_seconds,
            "reuse_seconds": reuse_seconds,
            "source_id": first.source_id,
            "sources": source_count_after,
            "games": game_count_after,
            "attempts": attempt_count_after,
            "second_reused": second.reused,
            "search_games": reopened_count,
            "search_pages_before_close": search_pages,
            "search_pages_after_reopen": reopened_pages,
            "integrity_before": integrity_before,
            "integrity_after": integrity_after,
            "database_bytes": database_bytes,
        }
        Path("dedup-real-evidence.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
