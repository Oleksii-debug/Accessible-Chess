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
                        cbh: dict | None = None,
                        advanced: dict | None = None,
                        training: dict | None = None,
                        gutenberg: dict | None = None,
                        chess960: dict | None = None,
                        reti: dict | None = None,
                        docx: dict | None = None) -> dict:
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
    # Actual upstream Capablanca text converted into an OPC DOCX for user
    # interoperability is not an independent original DOCX. Record that real
    # Books open/recovery test without granting source-format write/roundtrip.
    if docx is not None:
        original_id = "gitenberg_capablanca_33870_original_txt"
        original = sources.get(original_id)
        raw_receipt = base_receipts.get(original_id)
        if (
            original is None
            or raw_receipt is None
            or docx.get("schema") != "accessible-chess-section39-original-prose-derived-docx-v1"
            or docx.get("source_commit_sha") != expected_sha
            or docx.get("source_id") != original_id
            or docx.get("original_txt_sha256") != original.get("sha256")
            or docx.get("original_txt_bytes") != original.get("indexed_bytes")
            or raw_receipt.get("actual_sha256") != original.get("sha256")
            or raw_receipt.get("actual_bytes") != original.get("indexed_bytes")
            or docx.get("read") != "PASS"
            or docx.get("write") != "UNSUPPORTED"
            or docx.get("roundtrip") != "UNSUPPORTED"
            or docx.get("qualification") != "PARTIAL_DERIVED_REAL_PROSE_NOT_INDEPENDENT_UPSTREAM_DOCX"
            or docx.get("original_format") != "TXT"
            or docx.get("derived_format") != "DOCX"
            or docx.get("genuine_original_text") is not True
            or docx.get("independent_upstream_docx") is not False
            or docx.get("mocked") is not False
            or docx.get("redistribution") != "ORIGINAL_NONCLEARED_BYTES_NOT_PACKAGED"
            or docx.get("actual_original_chess_paragraphs") != 32
            or docx.get("actual_semantic_blocks") != 33
            or not _valid_digest(docx.get("actual_docx_sha256"), 64)
        ):
            raise LawfulCorpusError("original Capablanca source-derived DOCX readback was fabricated or overclaimed")
        docx_row = rows["DOCX"]
        docx_row.update({
            "qualification": "PARTIAL",
            "read": "PASS", "write": "UNSUPPORTED", "roundtrip": "UNSUPPORTED",
            "coverage": "GENUINE_CHESS_TEXT_IN_DERIVED_DOCX_ONLY",
            "source_kind": "DERIVED_DOCX_FROM_AUTHENTIC_PINNED_BOOK_TXT",
            "qualified_source_id": original_id,
            "actual_importer": docx["actual_importer"],
            "actual": {
                "original_upstream_txt_sha256": docx["original_txt_sha256"],
                "real_generated_docx_sha256": docx["actual_docx_sha256"],
                "original_chess_paragraphs": 32,
                "actual_semantic_blocks": 33,
                "independent_original_docx_unavailable": True,
                "source_writeback": "UNSUPPORTED",
            },
            "source_ids": sorted(set(docx_row["source_ids"]) | {original_id}),
        })

    # A true historic chess composition is distinct from source-rated Lichess
    # training games. It must execute the original position, UK+EN commentary
    # and search/durable reimport before being credited to PGN/GameTree.
    if reti is not None:
        identity = "historical_reti_1921_original_bilingual_study_pgn"
        source = sources.get(identity)
        actual = reti.get("actual", {})
        if (
            source is None or
            reti.get("schema") != "acs-section39-historical-reti-original-study-v1"
            or reti.get("source_commit_sha") != expected_sha
            or reti.get("source_id") != identity
            or reti.get("source_sha256") != source.get("sha256")
            or reti.get("source_bytes") != source.get("indexed_bytes")
            or reti.get("original_fen") != "7K/8/k1P5/7p/8/8/8/8 w - - 0 1"
            or reti.get("canonical_replayed_san_plies") != 11
            or reti.get("historical_composition_year") != 1921
            or reti.get("bilingual_english_ukrainian") is not True
            or reti.get("real_source_read") is not True
            or reti.get("mocked") is not False
            or reti.get("qualification") != "PASS"
            or actual.get("full_game_tree_pgn_reimport_equal") is not True
            or actual.get("full_game_tree_acsdb_restart_equal") is not True
            or actual.get("source_search_count") != 1
            or actual.get("original_annotation_languages") != ["uk", "en"]
            or source.get("public_release") != "INCLUDED_OWN_TEXT_HISTORICAL_COMPOSITION"
            or base_receipts[identity].get("actual_sha256") != reti.get("source_sha256")
        ):
            raise LawfulCorpusError("historic original Réti composed-study chess receipt is missing/stale/fabricated")
        receipt = base_receipts[identity]
        receipt["semantic_qualification"] = "PASS"
        receipt["actual_importer"] = reti["actual_importer"]
        receipt["note"] = "genuine original historical composed study, 1921, bilingual annotations, legal SAN, ACSDB/PGN export and restart"
        original_row = rows["PGN"]
        original_row["genuine_historical_compositions"] = [{
            "source_id": identity, "source_sha256": source["sha256"],
            "bilingual_original_composition": True, "canonical_san_ply_count": 11,
            "full_semantic_pgn_acsdb_roundtrip": True,
        }]
        original_row["source_ids"] = sorted(set(original_row["source_ids"]) | {identity})

    if chess960 is not None:
        original_ids = {
            "stockfish_frc_openings_epd_zip",
            "stockfish_4mvs_90_99_epd_zip",
        }
        witnesses = chess960.get("sources", [])
        if (
            chess960.get("schema") != "acs-section39-authentic-stockfish-chess960-epd-v1"
            or chess960.get("source_commit_sha") != expected_sha
            or chess960.get("source_count") != 2
            or len(witnesses) != 2
            or {record.get("source_id") for record in witnesses} != original_ids
        ):
            raise LawfulCorpusError("genuine original Stockfish Chess960 evidence absent/stale")
        chess960_evidence = []
        for original in witnesses:
            origin = sources[original["source_id"]]
            supported = original.get("actual_canonical_position_roundtrip_count")
            unsupported = original.get("unsupported_original_record_count")
            total = original.get("original_record_count")
            quality = original.get("qualification")
            valid_quality = (
                "PASS" if unsupported == 0 else
                "PARTIAL" if supported else "UNSUPPORTED"
            ) if (type(supported) is int and type(unsupported) is int
                  and supported >= 0 and unsupported >= 0) else "INVALID"
            if (
                original.get("source_zip_sha256") != origin.get("sha256")
                or not _valid_digest(original.get("original_member_sha256"), 64)
                or type(total) is not int or total < 2
                or supported + unsupported != total
                or original.get("real_source_read") is not True
                or original.get("mocked") is not False
                or quality != valid_quality
                or origin.get("acquisition") != "VENDORED_SOURCE_VERIFIED"
                or not str(origin.get("license", "")).startswith("CC0")
            ):
                raise LawfulCorpusError("authentic Chess960 source identity or per-record coverage falsified")
            receipt = base_receipts[original["source_id"]]
            if receipt.get("actual_sha256") != origin["sha256"]:
                raise LawfulCorpusError("real original Chess960 ZIP was not byte-verified")
            receipt["semantic_qualification"] = quality
            receipt["actual_importer"] = original["actual_importer"]
            receipt["note"] = "actual original FRC and EPD ZIP; canonical per-position supported and unsupported outcomes counted separately"
            if quality == "PASS":
                receipt["status"] = "PASS"
            chess960_evidence.append({
                "source_id": original["source_id"],
                "original_zip_sha256": origin["sha256"],
                "original_member_sha256": original["original_member_sha256"],
                "supported": supported, "unsupported": unsupported,
                "qualification": quality,
            })
        rows["EPD"]["genuine_chess960_and_epd_source_evidence"] = chess960_evidence
        if any(row["unsupported"] for row in chess960_evidence):
            rows["EPD"]["qualification"] = "PARTIAL"
            rows["EPD"]["roundtrip"] = "PARTIAL"
        rows["EPD"]["source_ids"] = sorted(set(rows["EPD"]["source_ids"]) | original_ids)

    if gutenberg is not None:
        originals = gutenberg.get("sources", [])
        authoritative = {
            "capablanca_chess_fundamentals_epub3": ("EPUB", "https://www.gutenberg.org/ebooks/33870.epub3.images"),
            "gutenberg_chess_strategy_lasker": ("HTML", "https://www.gutenberg.org/cache/epub/5614/pg5614-h.zip"),
        }
        if (
            gutenberg.get("schema") != "accessible-chess-section39-real-external-gutenberg-ebooks-v1"
            or gutenberg.get("source_commit_sha") != expected_sha
            or gutenberg.get("source_count") != 2
            or gutenberg.get("downloaded_original_ebook_bytes_packaged") is not False
            or gutenberg.get("full_original_independent_sha_prequalified") is not False
            or len(originals) != 2
            or {x.get("source_id") for x in originals} != set(authoritative)
        ):
            raise LawfulCorpusError("actual Gutenberg EPUB3/HTML original-source proof unavailable or stale")
        for proof in originals:
            identity = proof["source_id"]
            fmt, url = authoritative[identity]
            received = proof.get("original_download_sha256")
            semantic = proof.get("qualified_semantic_source_sha256")
            registered = sources[identity]
            if (
                proof.get("source_format") != fmt
                or proof.get("original_source_url") != url
                or not str(proof.get("actual_final_url", "")).startswith("https://www.gutenberg.org/")
                or not _valid_digest(received, 64)
                or not _valid_digest(semantic, 64)
                or type(proof.get("original_download_bytes")) is not int
                or proof["original_download_bytes"] < 512
                or proof.get("original_sha256_prepinned_in_catalog") is not False
                or proof.get("qualification") != "PARTIAL_SOURCE_NOT_PREPINNED"
                or proof.get("real_original_source_read") is not True
                or proof.get("mocked") is not False
                or proof.get("semantic_bookdocument_equal_reimport") is not True
                or proof.get("reader_resume_reimport") != "PASS"
                or proof.get("source_rights") != "US_PD_DECLARATION_ONLY; NOT_CLEARED_FOR_PUBLIC_RELEASE"
                or proof.get("public_release") != "EXCLUDED"
                or registered.get("sha256") is not None
                or registered.get("redistribution") != "NOT_CLEARED"
            ):
                raise LawfulCorpusError("actual original EPUB3/HTML source receipt is fake or rights unverified")
            receipt = base_receipts[identity]
            if receipt.get("actual_sha256") is not None:
                raise LawfulCorpusError("Gutenberg original source was counted twice")
            receipt.update({
                "actual_sha256": received,
                "actual_bytes": proof["original_download_bytes"],
                "actual_importer": proof["actual_importer"],
                "status": "PARTIAL",
                "note": "real verified first-party HTTPS original and semantic read/reimport; original hash was observed, not pre-pinned",
            })
            format_row = rows[fmt]
            format_row.update({
                "qualification": "PARTIAL", "read": "PASS",
                "write": "UNSUPPORTED", "roundtrip": "UNSUPPORTED",
                "source_kind": "GENUINE_OFFICIAL_UPSTREAM_UNPINNED_ORIGINAL",
                "coverage": "EXECUTED_EXTERNAL_UNPINNED_SOURCE",
                "qualified_source_id": identity,
                "actual_importer": proof["actual_importer"],
                "actual": {
                    "source_id": identity,
                    "observed_original_sha256": received,
                    "semantic_original_sha256": semantic,
                    "semantic_block_count": proof["semantic_block_count"],
                    "reader_resume_reimport": "PASS",
                    "source_hash_prepinned": False,
                },
                "source_ids": sorted(set(format_row["source_ids"]) | {identity}),
            })

    # Real Section 37 CC0 source changes feed the deployed Books/Training
    # player, not just a test directory. Only executed original-byte readback
    # qualifies the embedded 16+4 puzzles; never call derived JSON full FEN.
    if training is not None:
        selected = training.get("sources", [])
        required = {
            "lichess_cc0_advanced_16_original_derived": 16,
            "lichess_cc0_extreme_4_original_derived_puzzles": 4,
        }
        if (
            training.get("schema") != "accessible-chess-section39-real-new-training-v1"
            or training.get("source_commit_sha") != expected_sha
            or training.get("original_source_count") != 2
            or training.get("total_real_legal_puzzles") != 20
            or training.get("original_raw_source_full_dataset_verified") is not False
            or len(selected) != 2
            or {entry.get("source_id") for entry in selected} != set(required)
        ):
            raise LawfulCorpusError("latest Section37 advanced corpus is stale, synthetic or incomplete")
        real_puzzle_evidence = []
        for source in selected:
            identity = source["source_id"]
            catalog_entry = sources[identity]
            actual = source.get("actual", {})
            receipt = base_receipts[identity]
            if (
                source.get("real_original_source_read") is not True
                or source.get("mocked") is not False
                or source.get("source_format") != "JSON_FEN_UCI"
                or source.get("original_sha256") != catalog_entry.get("sha256")
                or source.get("original_bytes") != catalog_entry.get("indexed_bytes")
                or source.get("qualification") != "PASS"
                or source.get("public_release") != "CC0_PUZZLE_DATA_ONLY"
                or actual.get("puzzle_count") != required[identity]
                or actual.get("replayed_legal_chess_positions") != required[identity]
                or actual.get("uk_en_same_canonical_positions") is not True
                or actual.get("bookdocument_roundtrip") != "PASS"
                or receipt.get("actual_sha256") != source["original_sha256"]
            ):
                raise LawfulCorpusError("original Section37 chess training source provenance/semantics invalid")
            receipt["semantic_qualification"] = "PASS_FOR_BOUNDED_QUALIFIED_JSON_POSITIONS"
            receipt["actual_importer"] = source["actual_importer"]
            receipt["note"] = "original CC0 source verified and real 2200+/3000+ BookDocument/Board readback; JSON is not FEN source format"
            real_puzzle_evidence.append({
                "source_id": identity, "original_sha256": source["original_sha256"],
                "verified_puzzle_count": required[identity], "source_kind": "SOURCE_BOUND_JSON_POSITION",
            })
        rows["FEN"]["genuine_embedded_chess_positions"] = real_puzzle_evidence

    # Section 37 keeps adding real original chess files on this workline.
    # Reuse those exact bytes and their observed end-to-end semantic verdicts.
    if advanced is not None:
        adv_id = "lichess_cc0_high_level_4_original_annotated_games"
        entry = sources.get(adv_id)
        actual = advanced.get("actual", {})
        if (
            entry is None
            or advanced.get("schema") != "accessible-chess-section39-new-section37-annotated-source-v1"
            or advanced.get("source_commit_sha") != expected_sha
            or advanced.get("source_id") != adv_id
            or advanced.get("real_source_read") is not True
            or advanced.get("mocked") is not False
            or advanced.get("original_sha256") != entry.get("sha256")
            or advanced.get("original_bytes") != entry.get("indexed_bytes")
            or advanced.get("original_game_count") != 4
            or entry.get("acquisition") != "VENDORED_SOURCE_VERIFIED"
            or entry.get("redistribution") != "permitted"
            or advanced.get("qualification") != "PASS"
            or actual.get("full_game_tree_equal_after_pgn_export") is not True
            or actual.get("full_game_tree_equal_after_acsdb_restart") is not True
            or actual.get("search_result_games") != 4
            or actual.get("source_indexes") != [0, 1, 2, 3]
        ):
            raise LawfulCorpusError("new original Section37 annotated source not fully qualified")
        receipt = base_receipts[adv_id]
        if receipt.get("actual_sha256") is not None:
            raise LawfulCorpusError("original annotated source already attributed to another candidate")
        receipt.update({
            "actual_sha256": advanced["original_sha256"],
            "actual_bytes": advanced["original_bytes"],
            "status": "PASS",
            "actual_importer": advanced["actual_importer"],
            "note": "genuine original Section37 annotated PGN, full GameTree export/reimport/search/SQLite restart",
        })
        pgn_row = rows["PGN"]
        pgn_row["genuine_external_sources"] = list(pgn_row.get("genuine_external_sources", [])) + [{
            "source_id": adv_id, "actual_sha256": advanced["original_sha256"],
            "qualification": advanced["qualification"],
            "actual_importer": advanced["actual_importer"],
            "full_game_tree_equal": True,
            "annotated_game_count": 4,
        }]
        pgn_row["source_ids"] = sorted(set(pgn_row["source_ids"]) | {adv_id})

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
    # EPD's original non-Chess960 puzzle PASS does not prove all genuine
    # Chess960 castling position records are supported. Keep the weakest
    # observed real-original verdict after the generic EPD result is merged.
    if chess960 is not None and any(x["unsupported"] for x in chess960_evidence):
        epd["qualification"] = "PARTIAL"
        epd["roundtrip"] = "PARTIAL"
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
        "original_source_count": len(imported_external) + (3 if cbh is not None else 0) + (1 if advanced is not None else 0) + (2 if gutenberg is not None else 0) + (2 if chess960 is not None else 0) + (1 if reti is not None else 0),
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
    parser.add_argument("--advanced", type=Path, required=True)
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--gutenberg", type=Path, required=True)
    parser.add_argument("--chess960", type=Path, required=True)
    parser.add_argument("--reti", type=Path, required=True)
    parser.add_argument("--docx", type=Path, required=True)
    args = parser.parse_args()
    head = _source_head()
    result = merge_real_receipts(
        _read(args.base), _read(args.positions), _read(args.books),
        load_catalog(), head, _read(args.cbh), _read(args.advanced), _read(args.training),
        _read(args.gutenberg), _read(args.chess960), _read(args.reti), _read(args.docx),
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
