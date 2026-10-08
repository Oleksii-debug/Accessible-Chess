"""Exact-SHA Section 39 CI provenance aggregator.

Merge *executed real upstream source* reports from independent Linux jobs.
Never infer CI success from a generated JSON file or promote a mock to PASS.
The product's canonical capability registry remains the source of capability
declarations; this is per-format QA evidence, not a second product authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from tools.revised_sections37_38_offline_manifest import ROOT, _source_head

REPORT = ROOT / "section39-ci-joined-real-format-evidence.json"
EXPECTED_SCHEMAS = (
    "accessible-chess-section39-real-format-qualification-v1",
    "accessible-chess-section39-external-original-position-semantics-v1",
    "accessible-chess-section39-original-chess-books-semantic-v1",
)
HEX40 = frozenset("0123456789abcdef")
HEX64 = HEX40


def _valid_digest(value: object, length: int) -> bool:
    return type(value) is str and len(value) == length and set(value) <= HEX40


def merge_real_receipts(base: dict, original_positions: dict, original_books: dict,
                        catalog: tuple[dict, ...], expected_sha: str,
                        cbh: dict | None = None) -> dict:
    if not _valid_digest(expected_sha, 40):
        raise LawfulCorpusError("Section 39 merge lacks exact source SHA")
    reports = (base, original_positions, original_books)
    for report, schema in zip(reports, EXPECTED_SCHEMAS):
        if report.get("schema") != schema or report.get("source_commit_sha") != expected_sha:
            raise LawfulCorpusError("Section 39 evidence missing exact candidate revision or schema")
        if report.get("section39_terminal_done") is True or report.get("terminal_done") is True:
            raise LawfulCorpusError("incoming report falsely declares terminal DONE")
    sources = {item["id"]: item for item in catalog}
    base_receipts = {item["source_id"]: dict(item) for item in base.get("source_receipts", [])}
    original_rows = base.get("format_rows", [])
    if len(original_rows) != 16 or len(base_receipts) != len(sources):
        raise LawfulCorpusError("original sixteen-format or source matrix changed")
    if set(base_receipts) != set(sources) or len({r["format"] for r in original_rows}) != 16:
        raise LawfulCorpusError("original format/source identities are incomplete")
    rows = {row["format"]: dict(row) for row in original_rows}
    position_evidence = original_positions.get("sources", [])
    book_evidence = original_books.get("sources", [])
    if (
        len(position_evidence) != 2
        or {p["source_id"] for p in position_evidence} !=
            {"original_epd2doc_7men_human_epd", "original_epd2doc_opening_fen"}
        or len(book_evidence) != 5
        or {p["source_id"] for p in book_evidence} != {
            "gutenberg_blue_book_chess_staunton",
            "gutenberg_chess_history_bird_original_txt",
            "gutenberg_checkmates_three_fishburne_original_txt",
            "original_gpl_chastity_chess_chapters_markdown",
            "cc0_capablanca_open_pdf_original_source",
        }
    ):
        raise LawfulCorpusError("original licensed external-file matrices incomplete")

    imported_external = []
    # The CBH authority is the already-existing original libcbh test adapter.
    # Retain the full 11-file companion identity for each of three real families.
    if cbh is not None:
        if (
            cbh.get("schema") != "accessible-chess-section39-cbh-authentic-oracle-v1"
            or cbh.get("source_commit_sha") != expected_sha
            or cbh.get("all_three_real_semantic_tests_executed") is not True
            or cbh.get("all_three_real_semantic_tests_success") is not True
            or cbh.get("full_cb_family_format_supported") is not False
            or cbh.get("original_source_bytes_packaged") is not False
        ):
            raise LawfulCorpusError("CBH real source oracle is stale, skipped or falsely supported")
        original_cbh = cbh.get("sources", [])
        if (
            len(original_cbh) != 3 or
            {e.get("source_id") for e in original_cbh} != {
                "libcbh_gpl_original_annotation_cbh_family",
                "libcbh_gpl_original_nested_variations_cbh_family",
                "libcbh_gpl_original_unusual_start_cbh_family",
            }
        ):
            raise LawfulCorpusError("all three pinned original CBH families are required")
        authentic_cbh = []
        for entry in original_cbh:
            registered = sources[entry["source_id"]]
            members = entry.get("original_member_sha256", {})
            qualified = entry.get("qualification")
            if (
                entry.get("original_source_read") is not True
                or entry.get("mock_used") is not False
                or entry.get("backend_commit") != registered.get("upstream_commit")
                or entry.get("original_member_count") != 11
                or not isinstance(members, dict)
                or len(members) != 11
                or {k: v["sha256"] for k, v in registered["external_companion_source_checksums"].items()} != members
                or qualified not in {"PASS", "PARTIAL"}
                or (entry["source_id"] == "libcbh_gpl_original_unusual_start_cbh_family" and qualified != "PARTIAL")
                or registered.get("public_release") != "EXCLUDED"
            ):
                raise LawfulCorpusError("original CBH companion SHA256s or true semantics mismatch")
            receipt = base_receipts[entry["source_id"]]
            receipt["actual_component_sha256"] = members
            receipt["status"] = "PARTIAL"
            receipt["note"] = "real GPL original 11-component CBH family; source-only test; whole format remains partial"
            authentic_cbh.append({
                "source_id": entry["source_id"], "qualification": qualified,
                "actual_importer": entry["actual_importer"],
                "original_member_sha256": members,
                "semantic_oracle_test": entry["semantic_oracle_test"],
            })
        cbh_row = rows["CBH"]
        cbh_row.update({
            "qualification": "PARTIAL", "read": "PARTIAL",
            "write": "UNSUPPORTED", "roundtrip": "UNSUPPORTED",
            "actual_importer": "acs.chessbase_decoder + acs.chessbase_library_import",
            "source_kind": "PINNED_GENUINE_UPSTREAM_BYTES",
            "coverage": "EXECUTED_BOUNDED_SLICE",
            "genuine_external_sources": authentic_cbh,
            "actual": "two authentic annotated/recursive-RAV families passed independent PGN export/ACSDB/restart oracle; unusual-start remains partial",
            "source_ids": sorted(set(cbh_row["source_ids"]) | {e["source_id"] for e in authentic_cbh}),
        })

    for entry in (*position_evidence, *book_evidence):
        source_id = entry["source_id"]
        if source_id not in sources or entry.get("real_source_read") is not True:
            raise LawfulCorpusError("external source evidence is synthetic or unknown")
        registered = sources[source_id]
        digest = entry.get("original_sha256", entry.get("source_sha256"))
        blob = entry.get("original_git_blob")
        if (
            not _valid_digest(digest, 64)
            or not _valid_digest(blob, 40)
            or blob != registered["upstream_git_blob"]
            or (registered.get("sha256") is not None and digest != registered["sha256"])
        ):
            raise LawfulCorpusError("external original source checksum/Git blob differs from catalog")
        license_digest = entry.get("license_sha256", entry.get("external_license_sha256"))
        if not _valid_digest(license_digest, 64):
            raise LawfulCorpusError("external original license evidence unavailable")
        pinned_license = registered.get("external_license_sha256")
        if pinned_license is not None and license_digest != pinned_license:
            raise LawfulCorpusError("external license digest does not match original catalog")
        if source_id.startswith("original_epd2doc_"):
            observed = entry.get("actual", {})
            counts = observed.get("counts", {})
            expected_count = registered.get("expected_line_count")
            if (
                expected_count != entry.get("original_record_count")
                or not isinstance(counts, dict)
                or sum(counts.get(k, 0) for k in ("PASS", "PARTIAL", "FAIL")) != expected_count
                or entry.get("format") not in ("EPD", "FEN")
                or (
                    entry.get("qualification") == "PASS"
                    and counts != {"PASS": expected_count, "PARTIAL": 0, "FAIL": 0}
                )
            ):
                raise LawfulCorpusError("genuine EPD/FEN semantic coverage cannot be invented")
        elif source_id == "cc0_capablanca_open_pdf_original_source":
            if entry.get("qualification") != "UNSUPPORTED" or entry.get("actual_importer") is not None:
                raise LawfulCorpusError("authentic PDF bytes cannot be promoted to semantic import")
        elif (
            entry.get("qualification") == "PARTIAL"
            and (
                entry.get("read") != "PASS"
                or entry.get("actual", {}).get("semantic_blocks_identical_after_reimport") is not True
                or entry.get("actual", {}).get("book_progress_restart") != "PASS"
            )
        ):
            raise LawfulCorpusError("genuine book must prove both reimport and durable resume")
        source_receipt = base_receipts[source_id]
        if source_receipt.get("actual_sha256") is not None:
            raise LawfulCorpusError("one external original was already claimed by base source matrix")
        source_receipt["actual_sha256"] = digest
        source_receipt["actual_bytes"] = entry.get("original_bytes")
        # For position rows original bytes live in the Section 37 proof.
        # Position readback does not carry byte count: use indexed bytes after
        # SHA and independent upstream Git object checks above.
        if source_receipt["actual_bytes"] is None:
            source_receipt["actual_bytes"] = registered.get("indexed_bytes")
        source_receipt["semantic_qualification"] = entry["qualification"]
        source_receipt["status"] = (
            "PASS" if entry["qualification"] == "PASS"
            else "PARTIAL" if entry["qualification"] in {"PARTIAL", "UNSUPPORTED"}
            else "FAIL"
        )
        source_receipt["note"] = "original external Git object+license verified, executed separate real-format adapter"
        if entry.get("distribution") not in (None, "TEST_ONLY_SOURCE_BYTES_NOT_PACKAGED"):
            raise LawfulCorpusError("original book declared unexpected distribution")
        fmt = (
            entry["format"] if entry.get("format") in ("EPD", "FEN")
            else {"txt": "TXT", "md": "Markdown", "pdf": "PDF"}.get(entry.get("source_format"))
        )
        if fmt not in rows:
            raise LawfulCorpusError("external source format not in canonical sixteen")
        summary = {
            "source_id": source_id, "actual_sha256": digest,
            "original_git_blob": blob, "qualification": entry["qualification"],
            "actual_importer": entry.get("actual_importer"),
        }
        if "actual" in entry:
            summary["actual"] = entry["actual"]
        imported_external.append(summary)
        row = rows[fmt]
        extra = list(row.get("genuine_external_sources", []))
        extra.append(summary)
        row["genuine_external_sources"] = extra
        row["source_ids"] = sorted(set(row["source_ids"]) | {source_id})

    epd = rows["EPD"]
    epd_source = epd["genuine_external_sources"][0]
    epd_quality = epd_source["qualification"]
    epd.update({
        "qualification": epd_quality,
        "read": "PASS" if epd_quality == "PASS" else epd_quality,
        "write": "PASS" if epd_quality == "PASS" else epd_quality,
        "roundtrip": "PASS" if epd_quality == "PASS" else epd_quality,
        "actual_importer": epd_source["actual_importer"],
        "qualified_source_id": epd_source["source_id"],
        "source_kind": "PINNED_GENUINE_UPSTREAM_BYTES",
        "coverage": "EXECUTED_BOUNDED_SLICE",
        "actual": epd_source["actual"],
    })
    fen_extra = rows["FEN"]["genuine_external_sources"][0]
    if fen_extra["qualification"] != "PASS":
        rows["FEN"]["qualification"] = "PARTIAL"
        rows["FEN"]["roundtrip"] = "PARTIAL"
    for fmt in ("TXT", "Markdown"):
        target = rows[fmt]
        extras = target.get("genuine_external_sources", [])
        if not extras:
            raise LawfulCorpusError("original chess text/Markdown book evidence missing")
        if any(x["qualification"] == "FAIL" for x in extras):
            target["qualification"] = "FAIL"
            target["read"] = "FAIL"
        else:
            target["qualification"] = "PARTIAL"
            target["read"] = "PASS" if all(x["qualification"] == "PARTIAL" for x in extras) else "PARTIAL"
        target["write"] = "UNSUPPORTED"
        target["roundtrip"] = "UNSUPPORTED"
        target["coverage"] = "EXECUTED_BOUNDED_SLICE"
        target["source_kind"] = "PINNED_GENUINE_UPSTREAM_BYTES"
        target["actual_importer"] = "acs.book_text_import.import_text_book"
    pdf = rows["PDF"]
    pdf.update({
        "qualification": "UNSUPPORTED", "read": "UNSUPPORTED",
        "write": "UNSUPPORTED", "roundtrip": "UNSUPPORTED",
        "actual_importer": None, "coverage": "VERIFIED_ORIGINAL_BUT_UNSUPPORTED",
        "source_kind": "PINNED_GENUINE_UPSTREAM_BYTES",
        "actual": "genuine original PDF bytes authenticated; no PDF semantic importer",
    })
    return {
        "schema": "accessible-chess-section39-combined-external-genuine-evidence-v1",
        "section": 39, "source_commit_sha": expected_sha,
        "original_source_count": len(imported_external) + (3 if cbh is not None else 0),
        "format_count": 16, "format_rows": [rows[r["format"]] for r in original_rows],
        "source_receipts": [base_receipts[r["source_id"]] for r in base["source_receipts"]],
        "full_matrix_completed": False,
        "windows_packaged_verified": False,
        "manual_nvda_verified": False,
        "terminal_done": False,
        "ci_completion": "NOT_ATTESTED_BY_THIS_REPORT",
        "outstanding": [
            "independent true sample coverage of every supported and optional format",
            "CBH-family complete proprietary original roundtrip and companion negative matrix",
            "Chess960 Unicode NAG RAV mixed-size original end-to-end loss metrics",
            "Windows packaged keyboard NVDA and recovery qualification",
            "upstream sections 37 and 38 terminal integration evidence",
        ],
    }


def _read(path: Path) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 6 * 1024 * 1024:
        raise LawfulCorpusError("missing/unsafe or overlarge Section 39 CI artifact")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    REPORT.unlink(missing_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--positions", type=Path, required=True)
    parser.add_argument("--books", type=Path, required=True)
    parser.add_argument("--cbh", type=Path, required=True)
    args = parser.parse_args()
    head = _source_head()
    result = merge_real_receipts(
        _read(args.base), _read(args.positions), _read(args.books),
        load_catalog(), head, _read(args.cbh),
    )
    staged = REPORT.with_suffix(".tmp")
    try:
        staged.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(staged, REPORT)
    finally:
        staged.unlink(missing_ok=True)
    if any(r["qualification"] == "FAIL" for r in result["format_rows"]):
        raise LawfulCorpusError("combined original-format evidence has a semantic failure")
    print(json.dumps({
        "source_commit_sha": head, "genuine_external_originals": result["original_source_count"],
        "format_count": result["format_count"], "section39_done": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
