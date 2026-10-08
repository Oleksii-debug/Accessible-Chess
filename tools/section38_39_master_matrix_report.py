"""Canonical professional section 38/39 QA coverage registry (NOT fake PASS).

Expand 25 authentic-source-grounded expert genres × all 16 declared source
formats × Ukrainian/English into 800 executable future test requirements.
Status is READINESS_ONLY unless independent source+import+restart+UI evidence
from another executed runner is actually supplied and validated elsewhere.
This script never creates a new importer, library or chess authority.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from acs.lawful_corpus_registry import load_catalog
from acs.format_capabilities import FORMAT_CAPABILITIES
from tools.revised_sections37_38_offline_manifest import ROOT


GENRES = ROOT / "docs/corpus/SECTION38_39_MASTER_GENRES_UA_EN_SOURCE_MATRIX.json"
FORMAT_QA = ROOT / "docs/corpus/SECTION38_39_ADVANCED_BILINGUAL_QA_CATALOG.json"
OUTPUT_DIR = ROOT / "_section38_39_master_matrix_qa"
OUTPUT_FILE = "master-genre-format-800-cell-qa.json"
_ALLOWED = {"FEN", "SAN", "EPD", "PGN", "ACSDB", "EPUB", "HTML", "TXT",
            "Markdown", "DOCX", "PDF", "CBH", "CBV", "CBF", "2CBH", "CBONE"}
_FAMILY = {
    "FEN": ("fen",), "SAN": ("san",), "EPD": ("epd",),
    "PGN": ("pgn",), "ACSDB": ("acsdb",), "EPUB": ("epub",),
    "HTML": ("html",), "TXT": ("txt",), "Markdown": ("md",),
    "DOCX": ("docx",), "PDF": ("pdf",), "CBH": ("cbh",),
    "CBV": ("cbv",), "CBF": ("cbf",), "2CBH": ("2cbh",),
    "CBONE": ("cbone",),
}


def _read_json(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    if not 0 < len(raw) <= 512 * 1024:
        raise ValueError("master genre metadata source exceeds byte limits")
    data = json.loads(raw)
    if type(data) is not dict:
        raise ValueError("master genre metadata schema is invalid")
    return data, hashlib.sha256(raw).hexdigest()


def _candidate_matches_format(source_format: str, target: str) -> bool:
    """Classify source *declared type*, not a substring inside another family.

    In particular '2cbh' is not classic 'CBH', 'cbf+cbi' is not CBV,
    and FEN text embedded in another format is not an independently acquired
    FEN file. This only selects evidence candidates; it never issues PASS.
    """
    if type(source_format) is not str or type(target) is not str:
        raise TypeError("original format classifiers require exact text")
    if target not in _ALLOWED:
        raise ValueError("unsupported original format label")
    fmt = source_format.casefold().strip()
    if target == "CBH":
        return fmt in {"cbh", "cbh_family"} or fmt.startswith("cbh ")
    if target == "2CBH":
        return fmt == "2cbh"
    if target == "CBF":
        return fmt in {"cbf", "cbf+cbi"}
    if target == "CBV":
        return fmt in {"cbv", "cbv.zip"}
    if target == "CBONE":
        return fmt == "cbone"
    if target == "PGN":
        return fmt == "pgn" or fmt.startswith("pgn.") or fmt.startswith("pgn (")
    if target == "SAN":
        # SAN contained in PGN is NOT an independent original SAN file.
        return fmt == "san"
    if target == "FEN":
        return fmt == "fen"
    if target == "EPD":
        return fmt == "epd" or fmt.startswith("epd.")
    if target == "ACSDB":
        return fmt == "acsdb"
    if target == "Markdown":
        return fmt in {"markdown", "md"}
    if target == "DOCX":
        return fmt == "docx"
    if target == "PDF":
        return fmt == "pdf" or fmt.startswith("pdf (")
    if target == "EPUB":
        return fmt == "epub" or fmt.startswith("epub3/") or fmt.startswith("epub3")
    if target == "HTML":
        return fmt == "html" or "/html/" in fmt or fmt.endswith("/html")
    if target == "TXT":
        return fmt == "txt" or fmt.endswith("/txt")
    return False


def build_master_qa_matrix() -> dict:
    genres, genres_sha = _read_json(GENRES)
    formats, formats_sha = _read_json(FORMAT_QA)
    if genres.get("schema") != "accessible-chess-38-39-master-libraries-by-genre-v1":
        raise ValueError("unknown professional genres contract")
    if formats.get("schema") != "accessible-chess-section38-39-advanced-bilingual-curation-v1":
        raise ValueError("unknown format QA contract")
    genre_rows, format_rows = genres.get("genres"), formats.get("format_qa")
    if (
        type(genre_rows) is not list or len(genre_rows) != 25
        or type(genres.get("genre_count")) is not int or genres["genre_count"] != 25
        or type(format_rows) is not list or len(format_rows) != 16
        or {f.get("format") for f in format_rows} != _ALLOWED
    ):
        raise ValueError("25 × 16 canonical genre-format contracts required")
    catalog = {source["id"]: source for source in load_catalog()}
    capabilities = {cap.format_id: cap for cap in FORMAT_CAPABILITIES}
    indexed: list[dict] = []
    for genre in genre_rows:
        genre_id = genre.get("id")
        candidates = genre.get("original_or_derived_source_candidates")
        if type(genre_id) is not str or type(candidates) is not list or not candidates:
            raise ValueError("missing professional genre source candidates")
        eligible = []
        for candidate in candidates:
            ident = candidate["catalog_source_id"]
            if ident not in catalog:
                raise ValueError("advanced genre references unknown source")
            eligible.append(catalog[ident])
        for row in format_rows:
            fmt = row["format"]
            matched = tuple(
                source for source in eligible
                if _candidate_matches_format(source["format"], fmt)
            )
            for lang in ("uk", "en"):
                indexed.append({
                    "requirement_id": f"MASTER-{genre_id}-{fmt}-{lang}",
                    "genre_id": genre_id,
                    "genre_title": genre[lang],
                    "language": lang,
                    "format": fmt,
                    "required_real_file": row["required_real_object"],
                    "semantic_oracle": row["semantic_readback"],
                    "real_source_candidate_ids": [x["id"] for x in matched],
                    "real_candidate_statuses": [
                        {
                            "source_id": x["id"],
                            "acquisition": x["acquisition"],
                            "rights": x["redistribution"],
                            "sha256_expected": x.get("sha256"),
                            "source_kind": "ORIGINAL_OR_DERIVED_DECLARED_NOT_THIS_CELL_PROVEN",
                        } for x in matched
                    ],
                    "format_capability_boundaries": "See acs.format_capabilities.FORMAT_CAPABILITIES",
                    "independent_test_execution": "NOT_ATTESTED_IN_THIS_MATRIX",
                    "expected_vs_actual_readback": "NOT_EXECUTED_FOR_THIS_COMBINATION",
                    "windows_nvda_human_pass": False,
                    "evidence_status": "COVERAGE_REQUIREMENT_NOT_PASS",
                    "protected_book_bytes_present": False,
                })
    ids = [x["requirement_id"] for x in indexed]
    if len(indexed) != 800 or len(ids) != len(set(ids)):
        raise ValueError("genre × format × language coverage incomplete or duplicated")
    return {
        "schema": "acs-section38-39-advanced-cross-product-spec-v1",
        "plan_sections": [38, 39],
        "languages": ["uk", "en"],
        "genres": 25,
        "formats": 16,
        "requirement_cells": len(indexed),
        "genre_registry_sha256": genres_sha,
        "format_matrix_sha256": formats_sha,
        "canonical_capability_ids": sorted(capabilities),
        "source_registry_count": len(catalog),
        "requirements": indexed,
        "evidence_class": "SPECIFICATION_NOT_EXECUTED_REAL_CORPUS_VERDICT",
        "no_beginner_personal_course": True,
        "no_copy_of_protected_books": True,
        "section38_terminal_done": False,
        "section39_terminal_done": False,
        "needs_real_original_and_derived_per_cell_readback": True,
    }


def main() -> None:
    report = build_master_qa_matrix()
    if OUTPUT_DIR.exists() or OUTPUT_DIR.is_symlink():
        raise FileExistsError("would overwrite the owner QA coverage report")
    OUTPUT_DIR.mkdir(mode=0o700)
    destination = OUTPUT_DIR / OUTPUT_FILE
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "requirements": report["requirement_cells"],
        "format_families": report["formats"],
        "genres": report["genres"],
        "languages": report["languages"],
        "evidence_class": report["evidence_class"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
