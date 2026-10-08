"""Section 40 licensed real advanced training -> canonical portable Books/Training.

The genuine source is checked AGAINST the exact licensed runtime-embedded bytes.
Semantic chess validation belongs to the existing production runtime adapter.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from acs.bookdocument import BookDocument
from acs.lawful_corpus_registry import (
    LawfulCorpusError, load_catalog, read_verified_source_snapshot,
)
from acs.section40_advanced_licensed_dataset import (
    original_advanced_source_bytes, SOURCE_ID,
)
from acs.section40_extreme_licensed_dataset import (
    original_extreme_source_bytes, SOURCE_ID as EXTREME_SOURCE_ID,
)
from acs.section40_advanced_training_runtime import (
    build_advanced_offline_material, build_extreme_offline_material,
)

ROOT = Path(__file__).resolve().parents[1]
_BOOK_PATH = "books/advanced-lichess-16-middlegame-endgame.json"
_TRAINING_PATH = "training/advanced-lichess-16-middlegame-endgame.json"
_LICENSE_SHA = "a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499"


def build_advanced_training(*, root: Path = ROOT) -> tuple[dict[str, bytes], list[dict]]:
    entries = load_catalog(root / "docs/corpus/revised_sections37_40_sources.json")
    matching = [entry for entry in entries if entry.get("id") == SOURCE_ID]
    if len(matching) != 1:
        raise LawfulCorpusError("genuine advanced puzzle source missing")
    record = matching[0]
    if (record.get("acquisition") != "VENDORED_SOURCE_VERIFIED"
        or not str(record.get("license", "")).startswith("CC0")
        or not str(record.get("redistribution", "")).startswith("permitted")
        or record.get("license_sha256") != _LICENSE_SHA):
        raise LawfulCorpusError("genuine advanced source provenance/rights unverified")
    read_verified_source_snapshot(
        root / record["license_source"],
        {"sha256": _LICENSE_SHA, "max_bytes": 1024 * 1024},
    )
    raw = read_verified_source_snapshot(root / record["local_source"], record)
    if raw != original_advanced_source_bytes():
        raise LawfulCorpusError("runtime offline advanced dataset differs from genuine original")
    # Exactly the production BookDocument source: no separate test-only lesson model.
    book, tasks = build_advanced_offline_material()
    if len(tasks) != 16:
        raise LawfulCorpusError("advanced runtime exercise count changed")
    doc_wire = json.dumps(
        book.as_dict(), ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    if BookDocument.from_dict(json.loads(doc_wire)).as_dict() != book.as_dict():
        raise LawfulCorpusError("advanced canonical Books readback failed")
    train_wire = json.dumps({
        "schema_version": 1, "source_id": SOURCE_ID,
        "rating_system": "LICHESS_PUZZLE_RATING_NOT_FIDE",
        "composed_studies": False,
        "tasks": tasks,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    common = {
        "author": "Lichess CC0 original contributors",
        "language": "uk", "license": "CC0-1.0",
        "redistribution": "permitted; upstream source and rating notice preserved",
        "source_url": record.get("source_page"),
        "download_url": None,
        "repeat_download": "BUNDLED_OFFLINE",
    }
    rows = [
        dict(common, id="lichess_advanced_16_book", title=book.title,
             genre="advanced tactics and positional calculation",
             format="BookDocument JSON", source_path=_BOOK_PATH,
             size_bytes=len(doc_wire), sha256=hashlib.sha256(doc_wire).hexdigest(),
             import_status="CANONICAL_BOOKDOCUMENT_ROUNDTRIP_PASS"),
        dict(common, id="lichess_advanced_16_training",
             title="16 genuine puzzle positions after opponent's move",
             genre="advanced Training puzzles", format="Training JSON",
             source_path=_TRAINING_PATH,
             size_bytes=len(train_wire), sha256=hashlib.sha256(train_wire).hexdigest(),
             import_status="CANONICAL_CHESS_POSITION_AND_COMPLETE_SOLUTION_PASS"),
    ]
    return {_BOOK_PATH: doc_wire, _TRAINING_PATH: train_wire}, rows


def build_complete_advanced_training(*, root: Path = ROOT) -> tuple[dict[str, bytes], list[dict]]:
    """Combine two legally separated real advanced Lichess CC0 source families."""
    assets, rows = build_advanced_training(root=root)
    records = load_catalog(root / "docs/corpus/revised_sections37_40_sources.json")
    candidates = [record for record in records if record.get("id") == EXTREME_SOURCE_ID]
    if len(candidates) != 1:
        raise LawfulCorpusError("original 3000+ puzzle source absent")
    record = candidates[0]
    if (record.get("acquisition") != "VENDORED_SOURCE_VERIFIED"
        or record.get("license") != "CC0-1.0"
        or record.get("redistribution") != "permitted"
        or record.get("license_sha256") != _LICENSE_SHA):
        raise LawfulCorpusError("3000+ source identity/rights not qualified")
    read_verified_source_snapshot(
        root / record["license_source"],
        {"sha256": _LICENSE_SHA, "max_bytes": 1024 * 1024},
    )
    actual = read_verified_source_snapshot(root / record["local_source"], record)
    if actual != original_extreme_source_bytes():
        raise LawfulCorpusError("3000+ runtime dataset differs from genuine original")
    book, tasks = build_extreme_offline_material()
    if len(tasks) != 4 or any(
        task["puzzle_rating_lichess_not_fide"] < 3000 for task in tasks
    ):
        raise LawfulCorpusError("3000+ advanced source cannot qualify")
    book_wire = json.dumps(book.as_dict(), ensure_ascii=False,
                           sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    if BookDocument.from_dict(json.loads(book_wire)).as_dict() != book.as_dict():
        raise LawfulCorpusError("extreme BookDocument restart/readback invalid")
    training_wire = json.dumps({
        "schema_version": 1,
        "source_id": EXTREME_SOURCE_ID,
        "rating_system": "LICHESS_PUZZLE_RATING_NOT_FIDE",
        "composed_studies": False,
        "tasks": tasks,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    book_path = "books/extreme-lichess-4-original-puzzles.json"
    train_path = "training/extreme-lichess-4-original-puzzles.json"
    if book_path in assets or train_path in assets:
        raise LawfulCorpusError("extreme source output path conflicts with advanced curriculum")
    assets[book_path] = book_wire
    assets[train_path] = training_wire
    attribution = {
        "author": "Lichess original CC0 puzzle contributors",
        "language": "uk",
        "license": "CC0-1.0",
        "redistribution": "permitted; original puzzle data only, not FeXd GPL application",
        "source_url": record["source_page"],
        "download_url": None,
        "repeat_download": "BUNDLED_OFFLINE",
    }
    rows.extend([
        dict(attribution, id="lichess_extreme_4_book", title=book.title,
             genre="expert tactical calculation", format="BookDocument JSON",
             source_path=book_path, size_bytes=len(book_wire),
             sha256=hashlib.sha256(book_wire).hexdigest(),
             import_status="CANONICAL_BOOKDOCUMENT_ROUNDTRIP_PASS"),
        dict(attribution, id="lichess_extreme_4_training",
             title="4 original 3000–3166 Lichess rated puzzles",
             genre="expert tactical chess puzzles", format="Training JSON",
             source_path=train_path, size_bytes=len(training_wire),
             sha256=hashlib.sha256(training_wire).hexdigest(),
             import_status="CANONICAL_CHESS_POSITION_AND_COMPLETE_SOLUTION_PASS"),
    ])
    return assets, rows
