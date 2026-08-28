from __future__ import annotations

"""Real lawful corpus evidence for the Books -> Library referenced-game seam.

QA/evidence only.  This script does not implement PGN, ACSDB, Search, Book import,
or chess semantics.  It reuses the public application/domain boundaries to prove:
real CC0 PGN -> bounded canonical D06 parse -> D07 Library storage -> public Search
-> Book ``Game(game_id=...)`` -> the PR #337 ACSDB lookup adapter -> PR #303
canonical GameTree -> close/reopen -> identical referenced Book game identity.
"""

import hashlib
import io
import json
from pathlib import Path
import random
import tempfile
from urllib.request import Request, urlopen

import zstandard

from acs.acsdb import AcsDatabase
from acs.book_game_content import BookGameSource, resolve_book_game
from acs.book_library_game_lookup import AcsdbBookGameLookup
from acs.bookdocument import Game
from acs.gametree import serialize_game
from acs.library_import_service import LibraryImportService
from acs.pgn_roundtrip import parse_pgn_text
from acs.search_service import GameSearchQuery, GameSearchService


CORPUS_NAME = "lichess-standard-rated-2013-01"
CORPUS_URL = "https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst"
CORPUS_SHA256 = "aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635"
CORPUS_LICENSE = "CC0"
CORPUS_PUBLISHED_GAMES = 121_332
DOWNLOAD_LIMIT_BYTES = 32 * 1024 * 1024
DOWNLOAD_CHUNK = 1024 * 1024
SUBSET_GAMES = 512
SEARCH_LIMIT = 200
REFERENCE_SAMPLE = 64
RANDOM_SEED = 20260828
SUMMARY_PATH = Path("book-library-real-reference-summary.json")


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
    """Segment complete transport records without interpreting chess semantics."""

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
        headers={"User-Agent": "Accessible-Chess-Book-Library-Reference-QA/1"},
    )
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
        with reader, io.TextIOWrapper(
            reader,
            encoding="utf-8",
            errors="strict",
            newline="",
        ) as text:
            return _write_complete_game_subset(text, subset, SUBSET_GAMES)


def _sample(items):
    if len(items) < REFERENCE_SAMPLE:
        raise AssertionError(
            f"public Search returned too few candidates: {len(items)} < {REFERENCE_SAMPLE}"
        )
    rng = random.Random(RANDOM_SEED)
    middle = list(range(1, len(items) - 1))
    needed = REFERENCE_SAMPLE - 2
    indexes = sorted({0, len(items) - 1, *rng.sample(middle, needed)})
    if len(indexes) != REFERENCE_SAMPLE:
        raise AssertionError("deterministic Book reference sample cardinality drifted")
    return tuple(items[index] for index in indexes)


def _quick_integrity(database: AcsDatabase) -> dict[str, object]:
    quick_row = database.conn.execute("PRAGMA quick_check").fetchone()
    quick = str(quick_row[0]) if quick_row is not None else "missing"
    foreign_key_issue = database.conn.execute("PRAGMA foreign_key_check").fetchone()
    if quick.lower() != "ok":
        raise AssertionError(f"ACSDB quick_check failed: {quick}")
    if foreign_key_issue is not None:
        raise AssertionError("ACSDB foreign-key integrity failed")
    return {
        "quick_check": quick,
        "foreign_key_check": "PASS",
        "schema_version": database.schema_version,
    }


def _canonical_reference_record(database: AcsDatabase, item) -> dict[str, object]:
    changes_before = database.conn.total_changes
    resolved = resolve_book_game(
        Game(
            game_id=item.game_id,
            title=f"Real Library game {item.source_index}",
            block_id=f"real-library-{item.game_id}",
        ),
        lookup=AcsdbBookGameLookup(database),
    )
    if database.conn.total_changes != changes_before:
        raise AssertionError("Book referenced-game lookup mutated ACSDB")
    if resolved.source is not BookGameSource.REFERENCE:
        raise AssertionError("Book referenced-game lookup did not report REFERENCE source")
    if resolved.game_id != item.game_id:
        raise AssertionError("Book referenced-game lookup changed game_id")
    if resolved.game.source_index != item.source_index:
        raise AssertionError("Book referenced-game lookup changed source_index")
    canonical = serialize_game(resolved.game)
    return {
        "game_id": item.game_id,
        "source_index": item.source_index,
        "canonical_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "white": item.white,
        "black": item.black,
        "result": item.result,
    }


def _search_source(database: AcsDatabase, source_id: int):
    page = GameSearchService(database).search(
        GameSearchQuery(source_id=source_id, limit=SEARCH_LIMIT)
    )
    if len(page.items) != SEARCH_LIMIT or not page.has_more:
        raise AssertionError(
            "public Search did not expose the expected bounded first page of the real source"
        )
    if page.next_after_game_id is None:
        raise AssertionError("public Search omitted the next keyset cursor")
    source_indexes = [item.source_index for item in page.items]
    if source_indexes != list(range(SEARCH_LIMIT)):
        raise AssertionError("real source first Search page lost deterministic source order")
    return page


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="accessible-chess-book-library-real-") as temporary:
        root = Path(temporary)
        compressed = root / "lichess.pgn.zst"
        subset = root / "lichess-first-512.pgn"
        database_path = root / "library.acsdb"

        compressed_bytes = _download_verified(compressed)
        segmented = _make_subset(compressed, subset)
        if segmented != SUBSET_GAMES:
            raise AssertionError(f"expected {SUBSET_GAMES} complete games, got {segmented}")

        subset_bytes = subset.read_bytes()
        subset_sha256 = hashlib.sha256(subset_bytes).hexdigest()
        text = subset_bytes.decode("utf-8", errors="strict")
        games = tuple(parse_pgn_text(text, strict=False))
        if len(games) != SUBSET_GAMES:
            raise AssertionError(f"canonical D06 ingress returned {len(games)} games")
        if [game.source_index for game in games] != list(range(SUBSET_GAMES)):
            raise AssertionError("canonical D06 ingress source_index sequence drifted")

        database = AcsDatabase(database_path)
        try:
            result = LibraryImportService(database).import_games(
                games,
                source_name=f"{CORPUS_NAME}-first-{SUBSET_GAMES}.pgn",
                source_format="pgn",
                source_sha256=subset_sha256,
            )
            if result.game_count != SUBSET_GAMES:
                raise AssertionError(f"Library imported {result.game_count} real games")
            integrity_before = _quick_integrity(database)
            page = _search_source(database, result.source_id)
            sample = _sample(page.items)

            before_records = tuple(_canonical_reference_record(database, item) for item in sample)
            for item, record in zip(sample, before_records):
                reference = games[item.source_index]
                reference_sha = hashlib.sha256(
                    serialize_game(reference).encode("utf-8")
                ).hexdigest()
                if record["canonical_sha256"] != reference_sha:
                    raise AssertionError(
                        f"Book reference changed canonical GameTree at source index {item.source_index}"
                    )

            source_id = result.source_id
            first_page_ids = tuple(item.game_id for item in page.items)
        finally:
            database.close()

        reopened = AcsDatabase(database_path)
        try:
            integrity_after = _quick_integrity(reopened)
            reopened_page = _search_source(reopened, source_id)
            if tuple(item.game_id for item in reopened_page.items) != first_page_ids:
                raise AssertionError("reopened public Search changed stable real game IDs")
            reopened_by_id = {item.game_id: item for item in reopened_page.items}
            after_records = tuple(
                _canonical_reference_record(reopened, reopened_by_id[int(record["game_id"])])
                for record in before_records
            )
            if before_records != after_records:
                raise AssertionError("reopened Book references changed canonical identity")
        finally:
            reopened.close()

        summary = {
            "status": "PASS",
            "claim": "real lawful Books/Library referenced-game seam only",
            "product_parent": "PR337@93a256730ff920751a27c56672f74ebdca2701e4",
            "corpus": {
                "name": CORPUS_NAME,
                "url": CORPUS_URL,
                "license": CORPUS_LICENSE,
                "published_games": CORPUS_PUBLISHED_GAMES,
                "compressed_sha256": CORPUS_SHA256,
                "compressed_bytes": compressed_bytes,
                "subset_games": SUBSET_GAMES,
                "subset_sha256": subset_sha256,
                "subset_bytes": len(subset_bytes),
            },
            "journey": {
                "canonical_ingress": "acs.pgn_roundtrip.parse_pgn_text(strict=False)",
                "library_import": "acs.library_import_service.LibraryImportService",
                "search": "acs.search_service.GameSearchService",
                "book_reference": "acs.book_library_game_lookup.AcsdbBookGameLookup",
                "book_resolver": "acs.book_game_content.resolve_book_game",
                "imported_games": SUBSET_GAMES,
                "search_page_games": SEARCH_LIMIT,
                "book_references_checked": REFERENCE_SAMPLE,
                "close_reopen": "PASS",
                "canonical_digest_identity": "PASS",
                "source_index_identity": "PASS",
                "game_id_identity": "PASS",
                "read_only_lookup": "PASS",
            },
            "integrity_before_close": integrity_before,
            "integrity_after_reopen": integrity_after,
            "sample_seed": RANDOM_SEED,
            "sample": list(before_records),
            "support_boundary": {
                "new_format_support_claimed": False,
                "pgn_parser_support_claimed_here": False,
                "acsdb_search_support_claimed_here": False,
                "book_import_support_claimed_here": False,
                "export": "N/A for referenced-game lookup seam",
                "windows_nvda_acceptance": False,
            },
        }
        SUMMARY_PATH.write_text(
            json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print("BOOK_LIBRARY_REAL_REFERENCE=" + json.dumps(summary, sort_keys=True, ensure_ascii=False))
        print("BOOK LIBRARY REAL REFERENCE QA PASS")


if __name__ == "__main__":
    main()
