"""Honest per-source real-byte/readback manifest for revised Sections 37–38.

This does not claim completion of every declared format or distribution rights.
It runs the existing chess/book adapters against original, hash-pinned assets.
No source file is copied, published, or extracted to an untrusted filesystem path.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from acs.book_text_import import import_text_book
from acs.lawful_corpus_registry import (
    LawfulCorpusError, _vendored_asset_path, inventory_vendored_corpus,
    load_catalog, read_verified_source_snapshot, read_verified_zip_member,
)
from acs.pgn_roundtrip import parse_pgn_text
from acs.position_editor import PositionState


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "revised-sections37-38-offline-manifest.json"
PGN_ID = "stockfish_2moves_v2_pgn_zip"
FEN_ID = "stockfish_startpos_epd_zip"
BOOK_ID = "gitenberg_capablanca_33870_original_txt"


def _source_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=ROOT, check=True, capture_output=True, text=True, timeout=10,
    )
    sha = result.stdout.strip()
    expected = os.environ.get("ACCESSIBLE_CHESS_EXPECTED_HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or (expected is not None and expected != sha):
        raise LawfulCorpusError("manifest source checkout is not the expected exact SHA")
    return sha


def build_manifest(root: Path = ROOT) -> dict:
    catalog = load_catalog(root / "docs/corpus/revised_sections37_40_sources.json")
    verified = {
        item["source_id"]: item
        for item in inventory_vendored_corpus(catalog, root, distribution="TEST_BUILD")
    }
    outputs: list[dict] = []
    for item in catalog:
        acquisition = item["acquisition"]
        source_id = item["id"]
        row = {
            "source_id": source_id,
            "title": item.get("title"),
            "author": item.get("author"),
            "format": item.get("format"),
            "source_page": item.get("source_page"),
            "download_url": item.get("download_url"),
            "license": item.get("license"),
            "redistribution": item.get("redistribution"),
            "acquisition": acquisition,
            "expected_sha256": item.get("sha256"),
            "expected_bytes": item.get("indexed_bytes"),
            "actual_sha256": None,
            "actual_bytes": None,
            "semantic_state": "NOT_QUALIFIED",
            "semantic_count": 0,
            "public_release_published": False,
        }
        if acquisition == "VENDORED_SOURCE_VERIFIED":
            source = _vendored_asset_path(root, item["local_source"])
            # For a non-CC0 book, a pinned TEST_ONLY read is permitted by this
            # local QA ledger; it never authorizes public redistribution.
            # Read from one bounded, inode-checked source handle and bind the
            # exact bytes handed to Book/PGN/FEN adapters to the pinned digest.
            # A separate verify(path) followed by Path.read_bytes() could open
            # a swapped/unbounded file between the two operations.
            raw = read_verified_source_snapshot(source, item)
            row["actual_sha256"] = hashlib.sha256(raw).hexdigest()
            row["actual_bytes"] = len(raw)
            row["semantic_state"] = "VERIFIED_BYTES_ONLY"
            if source_id in verified:
                if verified[source_id]["sha256"] != row["actual_sha256"]:
                    raise LawfulCorpusError("source registry and manifest disagree")
            elif source_id != BOOK_ID:
                raise LawfulCorpusError("unqualified source entered test-only manifest")
            if source_id == BOOK_ID:
                book = import_text_book(
                    raw, source_name=source.name,
                    source_format="txt", title="Chess Fundamentals",
                    author="José Raúl Capablanca", language="en",
                )
                if book.source_sha256 != row["actual_sha256"] or not book.document.blocks:
                    raise LawfulCorpusError("real text book semantic readback failed")
                row["semantic_state"] = "SEMANTIC_TEXT_READ_TEST_ONLY"
                row["semantic_count"] = len(book.document.blocks)
            elif source_id == PGN_ID or source_id == FEN_ID:
                member = read_verified_zip_member(
                    source, item, expected_member=item["zip_member"],
                    max_unpacked_bytes=item["max_unpacked_bytes"],
                )
                row["verified_zip_member_sha256"] = hashlib.sha256(member).hexdigest()
                row["verified_zip_member_bytes"] = len(member)
                if source_id == PGN_ID:
                    if len(member) != item["original_member_bytes"]:
                        raise LawfulCorpusError("original PGN member byte count differs from qualified upstream source")
                    games = parse_pgn_text(member.decode("utf-8-sig", errors="strict"), strict=False)
                    if len(games) != item["original_pgn_opening_records"] or not all(game.line.moves for game in games):
                        raise LawfulCorpusError("original PGN games changed or lost canonical moves")
                    row["semantic_state"] = "SEMANTIC_PGN_PARSED"
                    row["semantic_count"] = len(games)
                    # Library persistence/roundtrip are separate mandatory gates.
                else:
                    lines = member.decode("utf-8-sig", errors="strict").splitlines()
                    first = lines[0].strip()
                    if len(first.split()) != 6:
                        raise LawfulCorpusError("original startpos source is not full FEN")
                    position = PositionState.from_fen(first)
                    if position.to_fen() != first or position.validate_playable():
                        raise LawfulCorpusError("canonical start-position readback failed")
                    row["semantic_state"] = "SEMANTIC_FEN_READ"
                    row["semantic_count"] = 1
        outputs.append(row)
    if len(outputs) != len(catalog) or len({r["source_id"] for r in outputs}) != len(catalog):
        raise LawfulCorpusError("source registry count or identity changed")
    return {
        "schema": "accessible-chess-revised-37-38-provenance-v1",
        "sources": outputs,
        "source_count": len(outputs),
        "vendored_cc0_byte_verified_count": len(verified),
        "genuine_test_book_read_count": sum(
            r["semantic_state"] == "SEMANTIC_TEXT_READ_TEST_ONLY" for r in outputs
        ),
        "revised_section_37_terminal_done": False,
        "revised_section_38_terminal_done": False,
        "note": "Verified bytes and named real-source semantic slices; other formats remain unqualified.",
    }


def main() -> None:
    REPORT.unlink(missing_ok=True)
    temporary = REPORT.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    head = _source_head()
    report = build_manifest()
    report["source_commit_sha"] = head
    try:
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, REPORT)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({
        "source_commit_sha": head,
        "source_count": report["source_count"],
        "vendored_cc0_byte_verified_count": report["vendored_cc0_byte_verified_count"],
        "genuine_test_book_read_count": report["genuine_test_book_read_count"],
        "section_37_done": False,
        "section_38_done": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
