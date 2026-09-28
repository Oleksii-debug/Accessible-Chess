from __future__ import annotations

"""Real lawful acceptance oracle for TXT chess-book ingestion.

The corpus is supplied by CI and is never vendored or uploaded. This oracle proves
only the TXT adapter claim. It deliberately requires that legacy ASCII diagrams
and descriptive chess notation remain readable prose instead of being guessed
into canonical positions or games.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import tempfile

from acs.book_progress_store import BookProgressStore
from acs.book_text_import import BookTextFormat, import_text_book
from acs.bookdocument import Game, Paragraph, Position
from acs.bookreader import BookReader


SUMMARY_PATH = Path("book-real-text-summary.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()

    source_path = Path(args.source)
    raw = source_path.read_bytes()
    actual_sha = sha256(raw).hexdigest()
    if actual_sha != args.expected_sha256:
        raise SystemExit(f"real TXT corpus digest mismatch: {actual_sha}")

    result = import_text_book(
        raw,
        source_name="Project Gutenberg 5614 plain text",
        source_format=BookTextFormat.TXT,
        title="Chess Strategy",
        author="Edward Lasker",
        language="en",
    )
    paragraphs = [block for block in result.document.blocks if isinstance(block, Paragraph)]
    games = [block for block in result.document.blocks if isinstance(block, Game)]
    positions = [block for block in result.document.blocks if isinstance(block, Position)]

    if result.source_sha256 != actual_sha:
        raise AssertionError("TXT adapter source digest differs from downloaded lawful corpus")
    if not result.book_key == f"txt-sha256:{actual_sha}":
        raise AssertionError("TXT stable book key does not bind exact source bytes")
    if result.document.title != "Chess Strategy" or result.document.author != "Edward Lasker":
        raise AssertionError("real TXT semantic metadata changed")
    if result.source_format is not BookTextFormat.TXT:
        raise AssertionError("real TXT source was classified as another format")
    if len(paragraphs) < 100:
        raise AssertionError(f"real TXT source produced too few readable paragraphs: {len(paragraphs)}")
    combined = "\n".join(block.text for block in paragraphs)
    for needle in ("TRANSLATOR’S PREFACE", "AUTHOR’S PREFACE", "GENERAL PRINCIPLES OF CHESS STRATEGY"):
        if needle not in combined:
            raise AssertionError(f"real TXT reading text lost required section marker: {needle}")
    if "ASCII" not in combined or "#Kt" not in combined:
        raise AssertionError("real TXT source lost its legacy diagram-reading explanation")
    if games or positions or result.pgn_games or result.positions:
        raise AssertionError("plain TXT importer fabricated chess semantics from legacy text")

    reader = BookReader(result.document)
    target_index = min(max(1, len(paragraphs) // 3), len(result.document.blocks) - 1)
    origin = reader.go_to(target_index)
    reader.save_return_point("real-txt-origin")
    reader.next_block()
    if reader.restore_return_point("real-txt-origin") != origin:
        raise AssertionError("real TXT BookReader exact return point changed")

    with tempfile.TemporaryDirectory(prefix="acs-real-txt-book-") as directory:
        store = BookProgressStore(Path(directory) / "book-progress.json")
        store.save(result.book_key, reader)
        fresh = import_text_book(
            raw,
            source_name="Project Gutenberg 5614 plain text",
            source_format=BookTextFormat.TXT,
            title="Chess Strategy",
            author="Edward Lasker",
            language="en",
        )
        reopened = store.restore(result.book_key, fresh.document)
        if reopened.location() != origin:
            raise AssertionError("real TXT close/reopen did not restore exact reading location")
        if reopened.restore_return_point("real-txt-origin") != origin:
            raise AssertionError("real TXT named return point did not survive reopen")

    summary = {
        "status": "PASS",
        "claim": "lawful real TXT chess-book semantic reading only",
        "source": {
            "name": "Project Gutenberg eBook #5614 — Chess Strategy",
            "author": "Edward Lasker",
            "license_status": "Public domain in the USA; check local jurisdiction",
            "sha256": actual_sha,
            "bytes": len(raw),
        },
        "txt": {
            "paragraphs": len(paragraphs),
            "fabricated_games": len(games),
            "fabricated_positions": len(positions),
            "ascii_diagram_text_preserved": True,
            "exact_return": "PASS",
            "close_reopen_progress": "PASS",
        },
        "support_boundary": {
            "TXT": "SUPPORTED_BY_THIS_REAL_GATE",
            "Markdown": "PARTIAL_FIXTURE_ONLY_PENDING_REAL_MARKDOWN_BOOK_CORPUS",
            "HTML_XHTML": "OWNED_BY_PR391_NOT_CLAIMED_HERE",
            "DOCX_EPUB_PDF_OCR": "UNSUPPORTED_HERE",
        },
    }
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print("REAL_TEXT_BOOK=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    print("REAL TXT BOOK QA PASS")


if __name__ == "__main__":
    main()
