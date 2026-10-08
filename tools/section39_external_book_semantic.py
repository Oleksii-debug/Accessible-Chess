"""Section 39 genuine third-party TXT/Markdown book semantics and PDF gap.

Work only on separately licensed and SHA/Git-blob verified temporary originals.
Use canonical BookTextImport + BookReader + durable progress; never duplicate a
parser, publish original test-only bytes, or manufacture PDF/OCR support.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from acs.book_text_import import BookTextImportError, import_text_book
from acs.bookreader import BookReader
from acs.book_progress_store import BookProgressStore
from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from tools.revised_section37_external_book_acquisition import (
    ROOT, _direct_path, _bounded_direct_snapshot, _exact_head, verify_external_books,
)

REPORT = ROOT / "section39-original-books-semantic-evidence.json"
IDS = frozenset({
    "gutenberg_blue_book_chess_staunton",
    "gutenberg_chess_history_bird_original_txt",
    "gutenberg_checkmates_three_fishburne_original_txt",
    "original_gpl_chastity_chess_chapters_markdown",
    "cc0_capablanca_open_pdf_original_source",
})


def _semantic_original_book(record: dict, provenance: dict, root: Path) -> dict:
    raw = _bounded_direct_snapshot(
        _direct_path(root, record["external_checkout_path"]), record["max_bytes"],
    )
    digest = hashlib.sha256(raw).hexdigest()
    if digest != provenance["sha256"] or len(raw) != provenance["original_bytes"]:
        raise LawfulCorpusError("original chess book changed between verified source and semantic import")
    identity = {
        "source_id": record["id"], "source_format": record["format"],
        "source_sha256": digest,
        "original_git_blob": provenance["git_blob"],
        "external_license_sha256": provenance["license_sha256"],
        "original_bytes": len(raw), "real_source_read": True,
        "source_rights": provenance.get("book_rights_notice"),
        "distribution": "TEST_ONLY_SOURCE_BYTES_NOT_PACKAGED",
    }
    if record["format"] == "pdf":
        # There is no actual canonical PDF adapter. A real PDF header and
        # original Git blob are source verification, NOT semantic read.
        return {
            **identity, "actual_importer": None, "qualification": "UNSUPPORTED",
            "read": "UNSUPPORTED", "write": "UNSUPPORTED", "roundtrip": "UNSUPPORTED",
            "expected": "real PDF semantic import/navigation/export",
            "actual": "original PDF bytes authenticated; no registered PDF semantic adapter",
        }

    fmt = "markdown" if record["format"] == "md" else "txt"
    try:
        first = import_text_book(
            raw, source_name=Path(record["external_checkout_path"]).name,
            source_format=fmt, title=record["title"],
            author=record.get("author"), language="en",
        )
        second = import_text_book(
            raw, source_name=Path(record["external_checkout_path"]).name,
            source_format=fmt, title=record["title"],
            author=record.get("author"), language="en",
        )
        if (
            first.source_sha256 != digest
            or second.source_sha256 != digest
            or first.book_key != second.book_key
            or len(first.document.blocks) != len(second.document.blocks)
            or len(first.document.blocks) < 2
        ):
            raise LawfulCorpusError("genuine book reimport changed source or semantic block index")
        one = [block.as_dict() for block in first.document.blocks]
        two = [block.as_dict() for block in second.document.blocks]
        if one != two:
            raise LawfulCorpusError("genuine original book blocks changed across semantic reimport")
        reader = BookReader(first.document)
        first_place = reader.location()
        moved = reader.next_block()
        if moved.index != first_place.index + 1:
            raise LawfulCorpusError("genuine book keyboard-like next-block navigation lost place")
        reader.save_return_point("section39-real-source")
        snapshot = reader.snapshot()
        resumed = BookReader.restore_snapshot(second.document, snapshot)
        if (
            resumed.location() != moved
            or resumed.restore_return_point("section39-real-source") != moved
        ):
            raise LawfulCorpusError("genuine book snapshot restart did not restore navigation")
        with tempfile.TemporaryDirectory(prefix="acs-39-original-book-") as temporary:
            state = Path(temporary) / "book-progress.json"
            BookProgressStore(state).save(first.book_key, reader)
            fresh = BookProgressStore(state).restore(second.book_key, second.document)
            if fresh.location() != moved or fresh.restore_return_point("section39-real-source") != moved:
                raise LawfulCorpusError("genuine book disk-restart lost return point")
        return {
            **identity, "actual_importer": "acs.book_text_import.import_text_book -> acs.bookreader.BookReader",
            "qualification": "PARTIAL", "read": "PASS",
            "write": "UNSUPPORTED", "roundtrip": "UNSUPPORTED",
            "expected": "original bytes -> BookDocument -> navigate -> reimport -> durable resume",
            "actual": {
                "block_count": len(one), "semantic_blocks_identical_after_reimport": True,
                "book_progress_restart": "PASS", "source_writeback": "UNSUPPORTED",
                "game_count": first.pgn_games, "position_count": first.positions,
                "warning_count": len(first.warnings),
            },
        }
    except (BookTextImportError, LawfulCorpusError, UnicodeError, ValueError) as exc:
        return {
            **identity, "actual_importer": "acs.book_text_import.import_text_book",
            "qualification": "FAIL", "read": "FAIL", "write": "UNSUPPORTED",
            "roundtrip": "UNSUPPORTED",
            "expected": "original bytes -> stable semantic BookDocument/reader restart",
            "actual": {"failure_category": type(exc).__name__},
        }


def qualify_external_books(catalog: tuple[dict, ...], root: Path) -> dict:
    relevant = tuple(record for record in catalog if record.get("id") in IDS)
    if len(relevant) != len(IDS):
        raise LawfulCorpusError("five actual external chess-book sources must be cataloged")
    verified = verify_external_books(relevant, root)
    receipts = {item["source_id"]: item for item in verified}
    rows = [
        _semantic_original_book(record, receipts[record["id"]], root)
        for record in sorted(relevant, key=lambda item: item["id"])
    ]
    if len(rows) != 5:
        raise LawfulCorpusError("actual third-party book matrix incomplete")
    return {
        "schema": "accessible-chess-section39-original-chess-books-semantic-v1",
        "source_count": len(rows), "sources": rows,
        "actual_original_semantic_read_count": sum(row["read"] == "PASS" for row in rows),
        "full_source_format_roundtrip_count": 0,
        "derived_or_synthetic_pass_count": 0,
        "section39_terminal_done": False,
    }


def main() -> None:
    REPORT.unlink(missing_ok=True)
    head = _exact_head()
    source_root = os.environ.get("ACS_37_GITENBERG_ROOT")
    if not source_root:
        raise LawfulCorpusError("authorized temporary original book root absent")
    report = qualify_external_books(load_catalog(), Path(source_root))
    report["source_commit_sha"] = head
    staged = REPORT.with_suffix(".tmp")
    try:
        staged.write_text(json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(staged, REPORT)
    finally:
        staged.unlink(missing_ok=True)
    print(json.dumps({
        "source_commit_sha": head,
        "actual_external_chess_book_formats": [x["source_format"] for x in report["sources"]],
        "semantic_reads": report["actual_original_semantic_read_count"],
        "section39_done": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
