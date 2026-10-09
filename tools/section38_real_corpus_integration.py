from __future__ import annotations

"""Section 38 real-corpus integration/readback gate.

Inputs are downloaded into a test-only workspace.  The command binds every
published result to a SHA-256, routes chess data through the canonical PGN and
Library owners, and records unsupported formats explicitly instead of calling
fixtures or filename probes a successful import.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from acs.acsdb import AcsDatabase  # noqa: E402
from acs.book_library_import import open_book_library_source  # noqa: E402
from acs.library_import_service import (  # noqa: E402
    LibraryImportCancelledError,
    LibraryImportService,
)
from acs.pgn_roundtrip import parse_pgn_text  # noqa: E402


PGN_SOURCES = {
    "cotswold_pgn": {
        "relative": "chessit/cotswold_2023.pgn",
        "url": "https://www.chessit.co.uk/Congresses/Cotswold/2023/Cotswold_Open_2023.pgn",
        "rights": "test_only_redistribution_uncleared",
    },
    "alekhine_pgn": {
        "relative": "extracted/alekhine/Alekhine.pgn",
        "url": "https://www.pgnmentor.com/players/Alekhine.zip",
        "rights": "free_download_redistribution_unclear",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _games(path: Path):
    return parse_pgn_text(path.read_bytes().decode("utf-8-sig"), strict=False)


def _pgn_readback(path: Path) -> dict[str, object]:
    games = _games(path)
    results: dict[str, int] = {}
    for game in games:
        results[game.result] = results.get(game.result, 0) + 1
    return {
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "games": len(games),
        "warnings": sum(bool(game.warnings) for game in games),
        "results": dict(sorted(results.items())),
    }


def _book_readback(path: Path) -> dict[str, object]:
    opened = open_book_library_source(path)
    # BookLibrarySource intentionally exposes games/prose only; the semantic
    # document itself is owned by the existing Book Open path.  The exact
    # source and Library game projection are the integration contract here.
    return {
        "bytes": path.stat().st_size,
        "sha256": opened.source.sha256,
        "games": len(opened.games),
        "retained_book_blocks": opened.retained_book_blocks,
        "warnings": list(opened.warnings),
        "status": "PASS",
    }


def _library_gate(path: Path) -> dict[str, object]:
    games = _games(path)
    source_sha = _sha256(path)
    with tempfile.TemporaryDirectory(prefix="accessible-chess-section38-") as directory:
        database_path = Path(directory) / "library.acsdb"
        with AcsDatabase(database_path) as database:
            service = LibraryImportService(database)
            first = service.import_games(
                games,
                source_name=path.name,
                source_format="pgn",
                source_sha256=source_sha,
            )
            second = service.import_games(
                games,
                source_name=path.name,
                source_format="pgn",
                source_sha256=source_sha,
            )
            if not second.reused or second.source_id != first.source_id:
                raise RuntimeError("repeated real PGN import was not idempotently reused")
            backup = Path(directory) / "library-backup.acsdb"
            database.backup_to(backup)
            database.verify_integrity()
            count_before_restart = len(database.search_games(limit=max(1000, len(games) + 1)))
        with AcsDatabase(backup) as reopened:
            reopened.verify_integrity()
            count_after_restart = len(reopened.search_games(limit=max(1000, len(games) + 1)))
        if count_before_restart != len(games) or count_after_restart != len(games):
            raise RuntimeError("real PGN Library count changed across import/restart")

        cancelled = threading.Event()
        with AcsDatabase() as cancelled_db:
            def observe(progress):
                if progress.processed_games == 1:
                    cancelled.set()
            try:
                LibraryImportService(cancelled_db).import_games(
                    games,
                    source_name="cancelled-" + path.name,
                    source_format="pgn",
                    source_sha256=hashlib.sha256(("cancelled\0" + source_sha).encode()).hexdigest(),
                    cancel_check=cancelled.is_set,
                    progress_callback=observe,
                )
            except LibraryImportCancelledError:
                pass
            else:
                raise RuntimeError("cancellable real PGN import did not cancel")
            if cancelled_db.search_games(limit=1000):
                raise RuntimeError("cancelled real PGN import published rows")
    return {
        "status": "PASS",
        "games": len(games),
        "first_import_reused": first.reused,
        "second_import_reused": second.reused,
        "restart_count": count_after_restart,
        "cancellation_atomic": True,
    }


def collect(root: Path) -> dict[str, object]:
    evidence: dict[str, object] = {
        "schema_version": 1,
        "section": 38,
        "status": "INTERNAL_COMPLETE_EXTERNAL_BLOCKED",
        "source_policy": "read/test/redistribute are separate permissions",
        "pgn_sources": {},
        "book_sources": {},
        "integration": {},
        "unsupported_external_fixtures": {
            "PDF": "BLOCKED_NO_LAWFUL_REAL_FIXTURE_AND_OWNER",
            "DOCX": "BLOCKED_NO_LAWFUL_REAL_FIXTURE_AND_OWNER",
            "CBF+CBI": "BLOCKED_NO_LAWFUL_FIXTURE_AND_INDEPENDENT_ORACLE",
            "2CBH": "BLOCKED_NO_LAWFUL_FIXTURE_AND_INDEPENDENT_ORACLE",
            "CBONE": "BLOCKED_NO_LAWFUL_FIXTURE_AND_INDEPENDENT_ORACLE",
        },
    }
    for key, metadata in PGN_SOURCES.items():
        path = root / metadata["relative"]
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"missing real Section 38 source: {path}")
        readback = _pgn_readback(path)
        evidence["pgn_sources"][key] = {**metadata, "readback": readback}
    cotswold = root / PGN_SOURCES["cotswold_pgn"]["relative"]
    evidence["integration"] = _library_gate(cotswold)

    book_candidates = {
        "gutenberg_txt": root / "gutenberg-33870" / "pg33870.txt",
        "gutenberg_html": root / "gutenberg-33870" / "html" / "pg33870-images.html",
        "gutenberg_epub3": root / "gutenberg-33870" / "pg33870.epub3",
    }
    book_urls = {
        "gutenberg_txt": "https://www.gutenberg.org/cache/epub/33870/pg33870.txt",
        "gutenberg_html": "https://www.gutenberg.org/cache/epub/33870/pg33870-h.zip",
        "gutenberg_epub3": "https://www.gutenberg.org/ebooks/33870.epub3.images",
    }
    for key, path in book_candidates.items():
        if not path.is_file():
            evidence["book_sources"][key] = {"url": book_urls[key], "status": "NOT_CONFIGURED"}
            continue
        evidence["book_sources"][key] = {"url": book_urls[key], "readback": _book_readback(path)}
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = collect(args.corpus_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
