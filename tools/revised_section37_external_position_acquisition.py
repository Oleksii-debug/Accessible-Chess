"""Lawful exact-byte acquisition of authentic chess EPD/FEN test sources.

Strict transport/provenance gate only.  No PGN, EPD, FEN or chess-rules
parsers are reimplemented; syntactic line counting is NOT semantic validation.
Do not distribute the external GPL puzzle materials in public builds.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog, verified_local_source
from tools.revised_section37_external_book_acquisition import (
    _direct_path,
    _bounded_direct_snapshot,
    _git_blob,
    _exact_head,
    ROOT,
)

REPORT = ROOT / "revised-section37-original-epd-fen-source-evidence.json"
EXPECTED = {
    "original_epd2doc_7men_human_epd": ("epd", 1110),
    "original_epd2doc_opening_fen": ("fen", 4),
}


def verify_record_line_structure(text: str, fmt: str, line_count: int) -> int:
    """Only identify original source record family; never decide chess legality."""
    if type(text) is not str or type(line_count) is not int or not 0 < line_count <= 2_000_000:
        raise LawfulCorpusError("original source line qualification arguments invalid")
    if fmt not in ("epd", "fen") or "\x00" in text:
        raise LawfulCorpusError("original source format or content invalid")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) != line_count or any(len(line) > 2048 for line in lines):
        raise LawfulCorpusError("original EPD/FEN line count or bound changed")
    if fmt == "epd":
        if not all(" bm " in line and "; id " in line for line in lines):
            raise LawfulCorpusError("original EPD puzzle record family changed")
    elif not all(len(line.split()) in (4, 6) for line in lines):
        raise LawfulCorpusError("original FEN field structure changed")
    return len(lines)


def verify_original_positions(record: dict, external_root: Path) -> dict:
    expected = EXPECTED.get(record.get("id"))
    if expected is None:
        raise LawfulCorpusError("original chess-position corpus source id unknown")
    fmt, line_count = expected
    if (
        record.get("format") != fmt
        or record.get("expected_line_count") != line_count
        or record.get("acquisition") != "PINNED_NOT_DOWNLOADED_IN_THIS_PASS"
        or record.get("test_access") != "EXTERNAL_GPL_CHESS_POSITIONS_ONLY"
        or record.get("public_release") != "EXCLUDED"
        or record.get("redistribution") != "NOT_CLEARED"
    ):
        raise LawfulCorpusError("original chess-position source authority or rights altered")
    if (
        record.get("external_license_git_blob") !=
        "f288702d2fa16d3cdf0035b15a9fcbc552cd88e7"
        or record.get("external_license_sha256") !=
        "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"
        or record.get("external_license_indexed_bytes") != 35149
    ):
        raise LawfulCorpusError("original EPD/FEN GPL license metadata modified")
    original = _direct_path(external_root, record.get("external_checkout_path"))
    licence = _direct_path(external_root, record.get("external_license_checkout_path"))
    verified_local_source(original, record)
    source_bytes = _bounded_direct_snapshot(original, record["max_bytes"])
    licence_bytes = _bounded_direct_snapshot(licence, 35149)
    if (
        len(source_bytes) != record["indexed_bytes"]
        or hashlib.sha256(source_bytes).hexdigest() != record.get("sha256")
        or _git_blob(source_bytes) != record.get("upstream_git_blob")
        or len(licence_bytes) != 35149
        or _git_blob(licence_bytes) != record["external_license_git_blob"]
        or hashlib.sha256(licence_bytes).hexdigest() != record["external_license_sha256"]
        or not licence_bytes.lstrip().startswith(b"GNU GENERAL PUBLIC LICENSE")
    ):
        raise LawfulCorpusError("original EPD/FEN source or license byte identity mismatch")
    try:
        text = source_bytes.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise LawfulCorpusError("original EPD/FEN source encoding corrupt") from exc
    actual_count = verify_record_line_structure(text, fmt, line_count)
    return {
        "source_id": record["id"],
        "source_page": record["source_page"],
        "format": fmt,
        "original_bytes": len(source_bytes),
        "original_sha256": record["sha256"],
        "original_git_blob": record["upstream_git_blob"],
        "original_nonblank_lines": actual_count,
        "original_license_sha256": record["external_license_sha256"],
        "original_license_git_blob": record["external_license_git_blob"],
        "original_source_qualified": True,
        "semantic_fen_or_epd_import": "NOT_TESTED_BY_SOURCE_ACQUISITION",
        "public_release": "EXCLUDED",
        "external_source_packaged": False,
    }


def verify_real_position_sources(records: tuple[dict, ...], root: Path) -> tuple[dict, ...]:
    selection = [source for source in records if source.get("id") in EXPECTED]
    if len(selection) != len(EXPECTED) or {x["id"] for x in selection} != set(EXPECTED):
        raise LawfulCorpusError("original real FEN/EPD corpus catalog incomplete")
    return tuple(verify_original_positions(source, root) for source in sorted(selection, key=lambda x: x["id"]))


def main() -> None:
    REPORT.unlink(missing_ok=True)
    staged = REPORT.with_suffix(".tmp")
    staged.unlink(missing_ok=True)
    head = _exact_head()
    checkout = os.environ.get("ACS_37_EPD2DOC_ROOT")
    if not checkout:
        raise LawfulCorpusError("original EPD/FEN checkout root absent")
    originals = verify_real_position_sources(load_catalog(), Path(checkout))
    output = {
        "schema": "accessible-chess-section37-original-epd-fen-sources-v1",
        "source_commit_sha": head,
        "status": "SOURCE_ONLY_PASS",
        "sources": originals,
        "section37_terminal_done": False,
        "release_authorized": False,
    }
    try:
        staged.write_text(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8")
        os.replace(staged, REPORT)
    finally:
        staged.unlink(missing_ok=True)
    print(json.dumps({
        "real_source_count": len(originals),
        "original_record_count": sum(x["original_nonblank_lines"] for x in originals),
        "source_commit_sha": head,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
