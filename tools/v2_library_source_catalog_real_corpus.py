from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen

import zstandard

from acs.acsdb import AcsDatabase
from acs.library_import_service import LibraryImportService
from acs.library_source_service import LibrarySourceCatalogService, SourceCatalogQuery
from acs.pgn_service import open_pgn


CORPUS_NAME = "lichess-standard-rated-2013-01"
CORPUS_URL = "https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst"
CORPUS_SHA256 = "aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635"
CORPUS_LICENSE = "CC0"
CORPUS_PUBLISHED_GAMES = 121_332
SUBSET_GAMES = 5_000
DOWNLOAD_LIMIT_BYTES = 32 * 1024 * 1024
DOWNLOAD_CHUNK = 1024 * 1024
GAME_PAGE_LIMIT = 200


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
    request = Request(
        CORPUS_URL,
        headers={"User-Agent": "Accessible-Chess-D07-Source-Catalog-QA/1"},
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
        with reader, io.TextIOWrapper(
            reader,
            encoding="utf-8",
            errors="strict",
            newline="",
        ) as text:
            return _write_complete_game_subset(text, subset, SUBSET_GAMES)


def _enumerate_source(catalog: LibrarySourceCatalogService, source_id: int) -> tuple[int, int]:
    count = 0
    pages = 0
    cursor: int | None = None
    while True:
        page = catalog.source_games(
            source_id,
            after_game_id=cursor,
            limit=GAME_PAGE_LIMIT,
        )
        pages += 1
        count += len(page.items)
        if not page.has_more:
            if page.next_after_game_id is not None:
                raise AssertionError("terminal source-games page unexpectedly published a cursor")
            return count, pages
        if page.next_after_game_id is None:
            raise AssertionError("non-terminal source-games page omitted keyset cursor")
        if cursor is not None and page.next_after_game_id <= cursor:
            raise AssertionError("source-games keyset cursor did not advance")
        cursor = page.next_after_game_id


def _validate_catalog_item(item, *, source_id: int, attempt_id: int) -> None:
    if item.source_id != source_id:
        raise AssertionError("source catalog changed canonical source identity")
    if item.game_count != SUBSET_GAMES:
        raise AssertionError(f"source catalog counted {item.game_count} games")
    if item.game_count != (
        item.full_game_count
        + item.warning_game_count
        + item.partial_game_count
        + item.damaged_game_count
    ):
        raise AssertionError("source status aggregate does not equal game count")
    if item.attempt_count != 2:
        raise AssertionError(f"source catalog counted {item.attempt_count} linked attempts")
    if item.latest_attempt_id != attempt_id:
        raise AssertionError("source catalog did not expose latest repeated-import attempt")
    if item.latest_attempt_status not in {"full", "warning"}:
        raise AssertionError("source catalog latest attempt status is not canonical")
    if item.first_game_id is None or item.last_game_id is None:
        raise AssertionError("non-empty source catalog item lost game bounds")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="accessible-chess-source-catalog-real-") as temporary:
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
            importer = LibraryImportService(database)
            first = importer.import_games(
                opened.games,
                source_name=f"{CORPUS_NAME}-first-{SUBSET_GAMES}.pgn",
                source_format="pgn",
                source_sha256=opened.source.sha256,
            )
            repeated = importer.import_games(
                opened.games,
                source_name=f"renamed-{CORPUS_NAME}-first-{SUBSET_GAMES}.pgn",
                source_format="PGN",
                source_sha256=opened.source.sha256.upper(),
            )
            if first.reused or not repeated.reused:
                raise AssertionError("real exact-source import/reuse classification is wrong")
            if repeated.source_id != first.source_id:
                raise AssertionError("real exact-source repeat changed source identity")

            catalog = LibrarySourceCatalogService(database)
            page = catalog.list_sources(SourceCatalogQuery(source_format="PGN", limit=10))
            if page.has_more or page.next_after_source_id is not None or len(page.items) != 1:
                raise AssertionError("real source catalog page shape is not exact")
            item = page.items[0]
            _validate_catalog_item(
                item,
                source_id=first.source_id,
                attempt_id=repeated.attempt_id,
            )
            detail = catalog.get_source(first.source_id)
            if detail != item:
                raise AssertionError("source detail and catalog aggregate diverged")
            enumerated, pages_before = _enumerate_source(catalog, first.source_id)
            if enumerated != SUBSET_GAMES:
                raise AssertionError(f"source->games enumerated {enumerated} real games")
            integrity_before = database.verify_integrity()

        database_bytes = database_path.stat().st_size
        with AcsDatabase(database_path) as reopened:
            catalog = LibrarySourceCatalogService(reopened)
            item_after = catalog.get_source(first.source_id)
            if item_after is None:
                raise AssertionError("reopened catalog lost real source")
            _validate_catalog_item(
                item_after,
                source_id=first.source_id,
                attempt_id=repeated.attempt_id,
            )
            enumerated_after, pages_after = _enumerate_source(catalog, first.source_id)
            if enumerated_after != SUBSET_GAMES:
                raise AssertionError("reopened source->games count changed")
            integrity_after = reopened.verify_integrity()

        summary = {
            "status": "PASS",
            "product_candidate": "work/v2-library-source-catalog-20260831",
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
            "source_id": first.source_id,
            "sources": 1,
            "games": item_after.game_count,
            "attempts": item_after.attempt_count,
            "latest_attempt_id": item_after.latest_attempt_id,
            "latest_attempt_status": item_after.latest_attempt_status,
            "source_status_counts": {
                "full": item_after.full_game_count,
                "warning": item_after.warning_game_count,
                "partial": item_after.partial_game_count,
                "damaged": item_after.damaged_game_count,
            },
            "source_games": enumerated_after,
            "source_game_pages_before_close": pages_before,
            "source_game_pages_after_reopen": pages_after,
            "integrity_before": integrity_before,
            "integrity_after": integrity_after,
            "database_bytes": database_bytes,
        }
        Path("source-catalog-real-evidence.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
