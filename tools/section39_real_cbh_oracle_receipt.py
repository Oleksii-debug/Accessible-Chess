"""Section 39 licensed real CBH-family semantic oracle receipt.

Reexecute, do not merely cite, the existing pinned authentic libcbh test
families. The actual product decoder/Library/PGN export/restart oracle remains
tests.test_revised_section38_real_cbh_oracles; no secondary decoder is added.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from tests.test_revised_section38_real_cbh_oracles import (
    Dev09RealCbhAnnotationsVariationsTests,
    LIBCBH_COMMIT, _environment_ready, _family_hashes,
)
from tools.revised_sections37_38_offline_manifest import ROOT, _source_head

REPORT = ROOT / "section39-genuine-cbh-annotation-variation-semantic.json"

CASES = (
    ("libcbh_gpl_original_annotation_cbh_family", "LIBCBH_ANNOTATION_DIR", "TestBase", "PASS"),
    ("libcbh_gpl_original_nested_variations_cbh_family", "LIBCBH_VARIATION_DIR", "WithVariations", "PASS"),
    ("libcbh_gpl_original_unusual_start_cbh_family", "LIBCBH_UNUSUAL_DIR", "UnusualStartBytes", "PARTIAL"),
)


def build_cbh_real_receipt() -> dict:
    if not _environment_ready():
        raise LawfulCorpusError("actual pinned CBH bridge plus three original fixture dirs required")
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(Dev09RealCbhAnnotationsVariationsTests)
    if suite.countTestCases() != 3:
        raise LawfulCorpusError("authentic CBH semantic oracle suite changed")
    output = io.StringIO()
    results = unittest.TextTestRunner(stream=output, verbosity=1).run(suite)
    if (
        results.testsRun != 3 or not results.wasSuccessful()
        or results.skipped or results.expectedFailures or results.unexpectedSuccesses
    ):
        raise LawfulCorpusError("real CBH annotation/variation/unusual source semantic tests did not all execute and pass")
    catalog = {row["id"]: row for row in load_catalog()}
    sources = []
    for source_id, variable, stem, qualification in CASES:
        directory = Path(os.environ[variable])
        if not directory.is_dir() or directory.is_symlink():
            raise LawfulCorpusError("CBH original source directory is missing/unsafe")
        hashes = _family_hashes(directory, stem)
        cbh_file = f"{stem}.cbh"
        record = catalog.get(source_id)
        if cbh_file not in hashes or record is None or (
            record.get("upstream_commit") != LIBCBH_COMMIT
            or record.get("public_release") != "EXCLUDED"
            or record.get("test_access") != "EXTERNAL_GPL_EPHEMERAL_ONLY"
            or record.get("external_fixture_stem") != stem
            or record.get("external_companion_source_checksums") is None
            or len(hashes) != 11
        ):
            raise LawfulCorpusError("real CBH family lacks complete pinned Git-source provenance")
        pinned = record["external_companion_source_checksums"]
        if set(pinned) != set(hashes) or any(
            pinned[name]["sha256"] != actual for name, actual in hashes.items()
        ):
            raise LawfulCorpusError("real CBH family bytes differ from upstream original source metadata")
        sources.append({
            "source_id": source_id,
            "actual_importer": "acs.chessbase_decoder.decode_chessbase_external -> acs.chessbase_library_import -> acs.acsdb",
            "backend_commit": LIBCBH_COMMIT,
            "original_member_sha256": hashes,
            "original_member_count": len(hashes),
            "original_source_read": True,
            "mock_used": False,
            "semantic_oracle_test": (
                "test_real_annotation_family_matches_independent_pgn_end_to_end"
                if stem == "TestBase" else
                "test_real_recursive_variations_preserve_siblings_nested_comments_and_nags"
                if stem == "WithVariations" else
                "test_real_unusual_start_boundary_is_honestly_partial_or_preserved"
            ),
            "qualification": qualification,
            "actual_loss": (
                "zero oracle-observable annotations and NAG loss" if qualification == "PASS"
                else "unusual-start actual imported game count may be zero; no whole-family PASS"
            ),
            "original_license": "GPL fixture/optional backend from exact pinned libcbh original",
            "distribution": "EXTERNAL_TEST_ONLY_NEVER_PUBLISHED",
        })
    return {
        "schema": "accessible-chess-section39-cbh-authentic-oracle-v1",
        "source_count": len(sources), "sources": sources,
        "all_three_real_semantic_tests_executed": True,
        "all_three_real_semantic_tests_success": True,
        "full_cb_family_format_supported": False,
        "original_source_bytes_packaged": False,
        "section39_terminal_done": False,
    }


def main() -> None:
    REPORT.unlink(missing_ok=True)
    sha = _source_head()
    result = build_cbh_real_receipt()
    result["source_commit_sha"] = sha
    staged = REPORT.with_suffix(".tmp")
    try:
        staged.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8")
        os.replace(staged, REPORT)
    finally:
        staged.unlink(missing_ok=True)
    print(json.dumps({
        "source_commit_sha": sha, "authentic_cbh_family_count": result["source_count"],
        "qualifications": {item["source_id"]: item["qualification"] for item in result["sources"]},
        "section39_done": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
