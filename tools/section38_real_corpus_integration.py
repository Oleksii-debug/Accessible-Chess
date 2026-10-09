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
import subprocess
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
from acs.version2_application import Version2Application  # noqa: E402


PGN_SOURCES = {
    "cotswold_pgn": {
        "relative": "chessit/cotswold_2023.pgn",
        "url": "https://www.chessit.co.uk/Congresses/Cotswold/2023/Cotswold_Open_2023.pgn",
        "rights": "test_only_redistribution_uncleared",
        "expected_sha256": "3053909b99d30e4d430995553b0b9db4f131c5518fa50d62167c1f0fae5bfe34",
        "expected_games": 113,
    },
    "alekhine_pgn": {
        "relative": "extracted/alekhine/Alekhine.pgn",
        "url": "https://www.pgnmentor.com/players/Alekhine.zip",
        "rights": "free_download_redistribution_unclear",
        "expected_sha256": "d3fd8dcd9fb308d7636856c6538b386191f87738d8908ebe85fa064f48b5a8a0",
        "expected_games": 1661,
    },
}


# Observed original publisher bytes in the existing Section-38 test-only receipt.
# These are receipt pins, not a claim about future Gutenberg URL immutability.
BOOK_RECEIPT_SHA256 = {
    "gutenberg_txt": "86f8bbe769853ddac506c65f6b4fb2e78cb5f00761e6bee06c4d7a415b042639",
    "gutenberg_html": "491d869b06d2e330554f0dd401d697c2bd0af5e4ccdd7abdb3fd0765a1116043",
    "gutenberg_epub3": "d0d23372a6bbe47a2cdda030d9e13a8ff80f54a1a0cc7d38ac052a867825ab74",
}

MAX_REAL_PGN_BYTES = 128 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_pgn_games(path: Path, metadata: dict[str, object]):
    """Bind exact original bytes to the canonical parser; reject stale downloads."""
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("missing or indirect real Section 38 PGN source")
    size = path.stat().st_size
    if not 0 < size <= MAX_REAL_PGN_BYTES:
        raise RuntimeError("real Section 38 PGN size is outside bounded limits")
    original_sha = _sha256(path)
    if original_sha != metadata["expected_sha256"]:
        raise RuntimeError("real Section 38 PGN original SHA-256 does not match receipt")
    games = parse_pgn_text(path.read_bytes().decode("utf-8-sig"), strict=False)
    if len(games) != metadata["expected_games"]:
        raise RuntimeError("real Section 38 PGN game count differs from pinned oracle")
    if any(game.warnings for game in games):
        raise RuntimeError("real Section 38 PGN contains unqualified parse warnings")
    if _sha256(path) != original_sha:
        raise RuntimeError("real Section 38 PGN changed during semantic parsing")
    return games


def _pgn_readback(path: Path, metadata: dict[str, object]) -> tuple[dict[str, object], object]:
    games = _verified_pgn_games(path, metadata)
    results: dict[str, int] = {}
    for game in games:
        results[game.result] = results.get(game.result, 0) + 1
    return {
        "bytes": path.stat().st_size,
        "sha256": metadata["expected_sha256"],
        "status": "PASS_SOURCE_PINNED",
        "games": len(games),
        "warnings": sum(bool(game.warnings) for game in games),
        "results": dict(sorted(results.items())),
    }, games


def _book_readback(path: Path, expected_sha256: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("indirect or missing original book source")
    actual_sha = _sha256(path)
    if actual_sha != expected_sha256:
        raise RuntimeError("original book source SHA-256 differs from pinned receipt")
    opened = open_book_library_source(path)
    # Unlike a games-only Library projection, this also executes the real
    # native user's Book Open preparation, including EPUB3, through its
    # canonical semantic owner; no parallel book parser is introduced.
    prepared = Version2Application.prepare_book_open(path)
    semantic_blocks = len(prepared.document.blocks)
    if not semantic_blocks or not (opened.retained_book_blocks or opened.games):
        raise RuntimeError("original book lost semantic content on canonical open")
    if opened.source.sha256 != actual_sha or _sha256(path) != actual_sha:
        raise RuntimeError("original book source identity changed during import")
    warnings = list(opened.warnings)
    loss_signals = ("table structure", "unavailable", "no readable semantic content",
                    "unsupported", "not preserved", "omitted", "missing")
    semantic_loss = any(
        any(signal in warning.casefold() for signal in loss_signals)
        for warning in (*warnings, *prepared.warnings)
    )
    # The Book is genuinely readable, but its missing images/flattened tables
    # may not be advertised as complete-fidelity PASS.
    return {
        "bytes": path.stat().st_size,
        "sha256": actual_sha,
        "games": len(opened.games),
        "retained_book_blocks": opened.retained_book_blocks,
        "native_book_open_blocks": semantic_blocks,
        "native_book_open_warnings": len(prepared.warnings),
        "semantic_loss_detected": semantic_loss,
        "warnings": warnings,
        "status": "PARTIAL_SEMANTIC_LOSS" if semantic_loss else "PASS",
    }


def _library_gate(path: Path, games, source_sha: str) -> dict[str, object]:
    if _sha256(path) != source_sha:
        raise RuntimeError("real PGN mutated before Library ingress")
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
        if _sha256(path) != source_sha:
            raise RuntimeError("real PGN mutated during Library ingress")

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
        "status": "PARTIAL_NOT_TERMINAL",
        "source_policy": "read/test/redistribute are separate permissions",
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
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
    verified_games = {}
    for key, metadata in PGN_SOURCES.items():
        path = root / metadata["relative"]
        readback, games = _pgn_readback(path, metadata)
        verified_games[key] = games
        evidence["pgn_sources"][key] = {**metadata, "readback": readback}
    cotswold = root / PGN_SOURCES["cotswold_pgn"]["relative"]
    evidence["integration"] = _library_gate(
        cotswold, verified_games["cotswold_pgn"],
        PGN_SOURCES["cotswold_pgn"]["expected_sha256"],
    )

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
        evidence["book_sources"][key] = {
            "url": book_urls[key],
            "expected_sha256": BOOK_RECEIPT_SHA256[key],
            "readback": _book_readback(path, BOOK_RECEIPT_SHA256[key]),
        }
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
