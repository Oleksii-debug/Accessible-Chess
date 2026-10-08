"""Section 39 qualification of all actual Section37 bilingual 12-lesson books.

Single canonical Section37 workbook generator, existing Section40 Lichess CC0
originals and product Version2Application Books importer. Ten original
project-authored, bilingual derived files in 5 formats are *not* ten unrelated
publisher originals. No duplicate chess parser, no user download prerequisite.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from acs.book_progress_store import BookProgressStore
from acs.bookreader import BookReader
from acs.bookdocument import BookDocument
from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog, read_verified_source_snapshot
from acs.version2_application import Version2Application
from tools.revised_section37_bilingual_workbook_pack import load_advanced_workbook, make_pack
from tools.revised_sections37_38_offline_manifest import ROOT, _source_head

REPORT = ROOT / "section39-section37-bilingual-ten-native-books-qualification.json"
WORKBOOK = "tests/real_corpus/advanced_training/section37_master_workbook_bilingual.json"
SOURCES = (
    ("lichess_cc0_advanced_16_original_derived", "uci_moves_with_opponent_first", "rating"),
    ("lichess_cc0_extreme_4_original_derived_puzzles", "uci_moves_opponent_first", "puzzle_rating"),
)
EXTENSIONS = ("txt", "md", "html", "epub", "docx")
LANGUAGES = ("uk", "en")


def qualify_bilingual_books(*, root: Path = ROOT) -> tuple[dict, dict[str, bytes]]:
    """Return evidence and exact qualified genuine-source-derived book bytes."""
    catalog = {entry["id"]: entry for entry in load_catalog(root / "docs/corpus/revised_sections37_40_sources.json")}
    source = root / WORKBOOK
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 512 * 1024:
        raise LawfulCorpusError("genuine Section37 bilingual workbook unavailable or unsafe")
    original = source.read_bytes()
    source_hash = hashlib.sha256(original).hexdigest()
    work = load_advanced_workbook(source)
    if len(work["lessons"]) != 12 or work["language_codes"] != ["uk", "en"]:
        raise LawfulCorpusError("original Section37 advanced workbook size/language drift")
    qualified = {}
    for source_id, field, rating_field in SOURCES:
        entry = catalog.get(source_id)
        if (
            entry is None or entry.get("acquisition") != "VENDORED_SOURCE_VERIFIED"
            or entry.get("redistribution") != "permitted"
            or not str(entry.get("license", "")).startswith("CC0")
        ):
            raise LawfulCorpusError("original source puzzle rights/identity cannot be verified")
        raw = read_verified_source_snapshot(root / entry["local_source"], entry)
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise LawfulCorpusError("original source sample SHA changed")
        entries = json.loads(raw)["puzzles"]
        for item in entries:
            key = item["puzzle_id"]
            if key in qualified:
                raise LawfulCorpusError("genuine CC0 advanced source has duplicate puzzle ID")
            qualified[key] = (
                item["fen_before_opponent_move"], item[field].split(),
                item[rating_field], source_id,
            )
    for lesson in work["lessons"]:
        key = lesson["original_puzzle_id"]
        original_data = qualified.get(key)
        if original_data is None or (
            lesson["fen_before_opponent_move"] != original_data[0]
            or lesson["opponent_previous_move_uci"] != original_data[1][0]
            or lesson["solution_after_opponent_uci"] != original_data[1][1:]
            or lesson["rating_lichess_puzzle"] != original_data[2]
            or lesson["composer_study"] is not False
        ):
            raise LawfulCorpusError("workbook puzzle substituted for original Section37 CC0 chess position")
    files = make_pack(work)
    if len(files) != 10 or set(files) != {
        f"section37-advanced-workbook-{lang}.{ext}"
        for lang in LANGUAGES for ext in EXTENSIONS
    }:
        raise LawfulCorpusError("bilingual five-format original derived source inventory changed")
    expected_fens = tuple(lesson["fen_before_opponent_move"]
                          for lesson in work["lessons"])
    outputs = []
    locations = {}
    with tempfile.TemporaryDirectory(prefix="acs39-37-real-workbook-") as scratch:
        root_tmp = Path(scratch)
        for lang in LANGUAGES:
            for ext in EXTENSIONS:
                filename = f"section37-advanced-workbook-{lang}.{ext}"
                body = files[filename]
                path = root_tmp / filename
                path.write_bytes(body)
                prepared = Version2Application.prepare_book_open(path)
                again = Version2Application.prepare_book_open(path)
                restored_document = BookDocument.from_dict(prepared.document.as_dict())
                if (
                    prepared.document.as_dict() != again.document.as_dict()
                    or restored_document.as_dict() != prepared.document.as_dict()
                    or len(prepared.document.blocks) < 20
                ):
                    raise LawfulCorpusError("genuine bilingual chess book semantic reimport failed")
                chess_positions = [
                    block.fen for block in prepared.document.blocks
                    if block.kind == "Position"
                ]
                if ext in {"md", "html", "epub"}:
                    if tuple(chess_positions) != expected_fens:
                        raise LawfulCorpusError("bilingual chess book changed original FEN position identity/order")
                elif chess_positions:
                    raise LawfulCorpusError("TXT/DOCX invented an unmarked chess position")
                visible_text = "\n".join(
                    getattr(block, "text", "") for block in prepared.document.blocks
                    if isinstance(getattr(block, "text", ""), str)
                )
                # Complete genuine advanced instruction must survive five
                # native book transformations; just keeping its page title
                # and twelve FEN entries is not semantic source fidelity.
                if any(
                    lesson["lesson_id"] not in visible_text
                    or lesson[lang]["prompt"] not in visible_text
                    for lesson in work["lessons"]
                ):
                    raise LawfulCorpusError("Section37 bilingual full teaching lesson text was lost on original format import")
                reader = BookReader(prepared.document)
                before = reader.location()
                after = reader.next_block()
                if after.index != before.index + 1:
                    raise LawfulCorpusError("genuine chess text reader cannot move forward")
                reader.save_return_point("section39-source37-bilingual")
                progress = root_tmp / ("progress-" + lang + "." + ext + ".json")
                BookProgressStore(progress).save(prepared.book_key, reader)
                resumed = BookProgressStore(progress).restore(
                    again.book_key, again.document,
                )
                if (
                    resumed.location() != after
                    or resumed.restore_return_point("section39-source37-bilingual") != after
                ):
                    raise LawfulCorpusError("bilingual chess book loses reading position after restart")
                outputs.append({
                    "format": ext.upper(), "language": lang, "filename": filename,
                    "derived_sha256": hashlib.sha256(body).hexdigest(),
                    "derived_bytes": len(body),
                    "semantic_blocks": len(prepared.document.blocks),
                    "explicit_fen_positions": len(chess_positions),
                    "source_fen_sequence_identical": (
                        tuple(chess_positions) == expected_fens if ext in {"md", "html", "epub"}
                        else "NO_EXPLICIT_FEN_METADATA_IN_TEXT_DOCX"
                    ),
                    "all_twelve_original_prompts_present": True,
                    "importer": "acs.version2_application.Version2Application.prepare_book_open",
                    "bookdocument_semantic_reimport": "PASS",
                    "book_progress_disk_restart": "PASS",
                    "source_kind": "AUTHORED_DERIVED_FROM_PINNED_ORIGINAL_CC0_POSITIONS",
                    "independent_publisher_original_file": False,
                })
                if chess_positions:
                    locations[(lang, ext)] = tuple(chess_positions)
        for extension in ("md", "html", "epub"):
            if locations[("uk", extension)] != locations[("en", extension)]:
                raise LawfulCorpusError("UK/EN authentic source changes canonical FEN position data")
    result = {
        "schema": "acs-section39-original-section37-bilingual-ten-book-import-v1",
        "workbook_source_path": WORKBOOK,
        "workbook_source_sha256": source_hash,
        "origin_sample_source_ids": [x[0] for x in SOURCES],
        "original_lesson_count": 12,
        "language_count": 2,
        "source_native_derived_format_count": 5,
        "observed_derivative_count": len(outputs),
        "sources": outputs,
        "real_original_cc0_position_provenance": True,
        "original_third_party_publisher_file_claim": False,
        "qualified_native_product_import_and_disk_restart": True,
        "source_book_binary_distribution_rights": "NEW_PROJECT_AUTHORED_CC0_POSITION_DERIVATIVES",
        "section39_terminal_done": False,
        "section40_terminal_done": False,
    }
    return result, files


def main():
    REPORT.unlink(missing_ok=True)
    sha = _source_head()
    evidence, _ = qualify_bilingual_books()
    evidence["source_commit_sha"] = sha
    temp = REPORT.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8")
        os.replace(temp, REPORT)
    finally:
        temp.unlink(missing_ok=True)
    print(json.dumps({
        "source_commit_sha": sha, "real_advanced_lessons": 12,
        "uk_en_derived_book_formats_executed": 10,
        "section39_done": False, "section40_done": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
