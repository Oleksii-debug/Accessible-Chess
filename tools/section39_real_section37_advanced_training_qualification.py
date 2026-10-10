"""Section 39 real Section37 advanced puzzle source -> canonical Books/Board qualification."""
from __future__ import annotations

import hashlib
import json
import os

from acs.bookdocument import BookDocument
from acs.chesscore import Board, parse_sq
from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog, read_verified_source_snapshot
from acs.section40_advanced_licensed_dataset import original_advanced_source_bytes
from acs.section40_extreme_licensed_dataset import original_extreme_source_bytes
from acs.section40_advanced_training_runtime import (
    build_advanced_offline_material, build_extreme_offline_material,
)
from tools.revised_sections37_38_offline_manifest import ROOT, _source_head

REPORT = ROOT / "section39-new-section37-training-position-semantic-evidence.json"
TRAINING_CASES = (
    ("lichess_cc0_advanced_16_original_derived", original_advanced_source_bytes,
     build_advanced_offline_material, 16, 2200),
    ("lichess_cc0_extreme_4_original_derived_puzzles", original_extreme_source_bytes,
     build_extreme_offline_material, 4, 3000),
)


def qualify_real_advanced_training() -> dict:
    source_catalog = {x["id"]: x for x in load_catalog()}
    rows = []
    for source_id, original_bytes, builder, expected_count, min_rating in TRAINING_CASES:
        entry = source_catalog.get(source_id)
        if (
            entry is None or entry.get("acquisition") != "VENDORED_SOURCE_VERIFIED"
            or entry.get("redistribution") != "permitted"
            or not str(entry.get("license", "")).startswith("CC0")
        ):
            raise LawfulCorpusError("Section37 genuine CC0 puzzle source not authorized")
        raw = read_verified_source_snapshot(ROOT / entry["local_source"], entry)
        digest = hashlib.sha256(raw).hexdigest()
        if (
            digest != entry["sha256"]
            or raw != original_bytes()
            or len(raw) != entry["indexed_bytes"]
        ):
            raise LawfulCorpusError("Section37 original puzzle differs from production embedded source")
        uk, tasks = builder(language="uk")
        en, tasks_en = builder(language="en")
        if len(tasks) != expected_count or len(tasks_en) != expected_count:
            raise LawfulCorpusError("real original puzzle source count changed")
        if BookDocument.from_dict(uk.as_dict()).as_dict() != uk.as_dict():
            raise LawfulCorpusError("Ukrainian genuine chess Books roundtrip changed")
        if BookDocument.from_dict(en.as_dict()).as_dict() != en.as_dict():
            raise LawfulCorpusError("English genuine chess Books roundtrip changed")
        if [(x["puzzle_id"], x["fen"], x["full_solution_uci"]) for x in tasks] != [
            (x["puzzle_id"], x["fen"], x["full_solution_uci"]) for x in tasks_en
        ]:
            raise LawfulCorpusError("bilingual chess sources changed canonical Board/Training authority")
        seen = set()
        for task in tasks:
            puzzle = task["puzzle_id"]
            position = Board(task["fen"])
            solution = task["full_solution_uci"]
            if (
                puzzle in seen
                or task["source_id"] != source_id
                or task["puzzle_rating_lichess_not_fide"] < min_rating
                or not solution
                or task["answer_uci"] != solution[0]
                or len(solution[0]) not in (4, 5)
            ):
                raise LawfulCorpusError("real puzzle rating/source/answer identity invalid")
            seen.add(puzzle)
            from_sq, to_sq = parse_sq(solution[0][:2]), parse_sq(solution[0][2:4])
            promotion = solution[0][4].upper() if len(solution[0]) == 5 else None
            if sum(
                x.frm == from_sq and x.to == to_sq and x.promotion == promotion
                for x in position.legal_moves()
            ) != 1:
                raise LawfulCorpusError("original chess puzzle first answer is not a legal Board move")
        rows.append({
            "source_id": source_id, "original_sha256": digest,
            "original_bytes": len(raw), "source_format": "JSON_FEN_UCI",
            "actual_importer": "acs.section40_advanced_training_runtime -> BookDocument/Board",
            "real_original_source_read": True, "mocked": False,
            "expected": f"{expected_count} verified Lichess rating >= {min_rating}, Board/FEN/solutions, UK+EN Books roundtrip",
            "actual": {
                "puzzle_count": len(tasks), "minimum_puzzle_rating": min(
                    task["puzzle_rating_lichess_not_fide"] for task in tasks),
                "replayed_legal_chess_positions": len(tasks),
                "uk_en_same_canonical_positions": True,
                "bookdocument_roundtrip": "PASS",
            },
            "qualification": "PASS",
            "public_release": "CC0_PUZZLE_DATA_ONLY",
        })
    return {
        "schema": "accessible-chess-section39-real-new-training-v1",
        "format_family": "derived chess FEN+UCI in JSON",
        "original_source_count": len(rows),
        "total_real_legal_puzzles": sum(r["actual"]["puzzle_count"] for r in rows),
        "sources": rows,
        "original_raw_source_full_dataset_verified": False,
        "section39_terminal_done": False,
    }


def main():
    REPORT.unlink(missing_ok=True)
    head = _source_head()
    report = qualify_real_advanced_training()
    report["source_commit_sha"] = head
    stage = REPORT.with_suffix(".tmp")
    try:
        stage.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8")
        os.replace(stage, REPORT)
    finally:
        stage.unlink(missing_ok=True)
    print(json.dumps({
        "source_commit_sha": head,
        "original_advanced_puzzles": report["total_real_legal_puzzles"],
        "section39_done": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
