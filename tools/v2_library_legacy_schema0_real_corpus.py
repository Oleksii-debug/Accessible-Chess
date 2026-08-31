from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.gametree import serialize_game
from acs.legacy_library_migration import migrate_legacy_library
from acs.pgn_service import open_pgn
from acs.search_service import GameSearchQuery, GameSearchService
from tools.v2_library_dedup_real_corpus import (
    CORPUS_LICENSE,
    CORPUS_NAME,
    CORPUS_PUBLISHED_GAMES,
    CORPUS_SHA256,
    CORPUS_URL,
    SUBSET_GAMES,
    _download_verified,
    _make_subset,
)


PAGE_LIMIT = 200


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def _create_legacy_from_real_games(path: Path, games) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS games(id INTEGER PRIMARY KEY, title TEXT, pgn TEXT, created_at TEXT)"
        )
        connection.executemany(
            "INSERT INTO games(id,title,pgn,created_at) VALUES(?,?,?,?)",
            (
                (
                    index,
                    game.tags.get("Event") or f"Legacy real game {index}",
                    serialize_game(game),
                    f"2013-01-01T00:{(index // 60) % 60:02d}:{index % 60:02d}",
                )
                for index, game in enumerate(games, start=1)
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _enumerate_all(database: AcsDatabase) -> tuple[int, int]:
    service = GameSearchService(database)
    total = 0
    pages = 0
    cursor: int | None = None
    while True:
        page = service.search(GameSearchQuery(after_game_id=cursor, limit=PAGE_LIMIT))
        pages += 1
        total += len(page.items)
        if not page.has_more:
            if page.next_after_game_id is not None:
                raise AssertionError("terminal migrated Library page unexpectedly has a cursor")
            return total, pages
        if page.next_after_game_id is None:
            raise AssertionError("non-terminal migrated Library page omitted keyset cursor")
        if cursor is not None and page.next_after_game_id <= cursor:
            raise AssertionError("migrated Library keyset cursor did not advance")
        cursor = page.next_after_game_id


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="accessible-chess-legacy-real-") as temporary:
        root = Path(temporary)
        compressed = root / "lichess.pgn.zst"
        subset = root / "lichess-first-5000.pgn"
        legacy = root / "legacy-library.db"
        current = root / "library.acsdb"

        compressed_bytes = _download_verified(compressed)
        segmented = _make_subset(compressed, subset)
        if segmented != SUBSET_GAMES:
            raise AssertionError(f"expected {SUBSET_GAMES} complete games, got {segmented}")

        opened = open_pgn(subset)
        if len(opened.games) != SUBSET_GAMES:
            raise AssertionError(f"canonical Product parser returned {len(opened.games)} games")
        if opened.global_warnings:
            raise AssertionError(f"unexpected global PGN warnings: {opened.global_warnings}")

        _create_legacy_from_real_games(legacy, opened.games)
        legacy_sha_before = _sha256(legacy)
        legacy_bytes = legacy.stat().st_size

        started = time.perf_counter()
        result = migrate_legacy_library(legacy, current)
        migration_seconds = time.perf_counter() - started
        legacy_sha_after = _sha256(legacy)
        if legacy_sha_after != legacy_sha_before:
            raise AssertionError("legacy source bytes changed during migration")
        if result.legacy_rows != SUBSET_GAMES or result.games != SUBSET_GAMES:
            raise AssertionError(f"legacy migration count mismatch: {result}")
        if result.schema_version != ACSDB_SCHEMA_VERSION:
            raise AssertionError("legacy migration did not reach current ACSDB schema")

        with AcsDatabase(current) as database:
            integrity_before = database.verify_integrity()
            source_count = int(database.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
            game_count = int(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
            attempt_count = int(database.conn.execute("SELECT COUNT(*) FROM import_attempts").fetchone()[0])
            if (source_count, game_count, attempt_count) != (SUBSET_GAMES, SUBSET_GAMES, SUBSET_GAMES):
                raise AssertionError(
                    f"migrated real counts mismatch: sources={source_count} games={game_count} attempts={attempt_count}"
                )
            search_count, search_pages = _enumerate_all(database)
            if search_count != SUBSET_GAMES:
                raise AssertionError(f"public Search enumerated {search_count} migrated games")
            first = database.get_game(1)
            last = database.get_game(SUBSET_GAMES)
            if first is None or last is None:
                raise AssertionError("migrated real endpoint game ids are missing")
            if first["pgn_text"] != serialize_game(opened.games[0]):
                raise AssertionError("first migrated real game changed canonical PGN")
            if last["pgn_text"] != serialize_game(opened.games[-1]):
                raise AssertionError("last migrated real game changed canonical PGN")

        database_bytes = current.stat().st_size
        with AcsDatabase(current) as reopened:
            integrity_after = reopened.verify_integrity()
            reopened_count, reopened_pages = _enumerate_all(reopened)
            if reopened_count != SUBSET_GAMES:
                raise AssertionError("reopened migrated real Library count changed")

        summary = {
            "status": "PASS",
            "product_candidate": "work/v2-library-legacy-schema0-migration-20260831",
            "migration_contract": "exact shipped schema0 shape -> new current ACSDB; source read-only; no in-place swap",
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
            "legacy_shape_generated_from_real_games": True,
            "legacy_rows": result.legacy_rows,
            "legacy_database_bytes": legacy_bytes,
            "legacy_sha256_before": legacy_sha_before,
            "legacy_sha256_after": legacy_sha_after,
            "migration_seconds": migration_seconds,
            "sources": source_count,
            "games": game_count,
            "attempts": attempt_count,
            "warning_games": result.warning_games,
            "search_games": reopened_count,
            "search_pages_before_close": search_pages,
            "search_pages_after_reopen": reopened_pages,
            "integrity_before": integrity_before,
            "integrity_after": integrity_after,
            "schema_version": result.schema_version,
            "database_bytes": database_bytes,
        }
        Path("legacy-schema0-real-evidence.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
