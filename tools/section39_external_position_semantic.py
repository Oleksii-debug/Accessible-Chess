"""Section 39 original-source EPD/FEN semantic qualification; GPL bytes never shipped.

The upstream checkout is temporary CI input. Source identity and its license
must pass Section 37's single canonical verification before this module is
allowed to exercise the existing canonical position/EPD parser and serializer.
No invented format support, and no silent corrupt-record acceptance.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from acs.epd import EpdParseError, parse_epd
from acs.position_editor import PositionState
from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from tools.revised_section37_external_book_acquisition import _direct_path, _bounded_direct_snapshot, ROOT
from tools.revised_section37_external_position_acquisition import (
    EXPECTED, verify_real_position_sources,
)
from tools.revised_sections37_38_offline_manifest import _source_head

REPORT = ROOT / "section39-original-epd-fen-semantic-evidence.json"
MAX_FAILURE_NOTES = 12


def qualify_original_record(text: str, family: str) -> tuple[str, str]:
    """One original position -> canonical read/write/reimport verdict.

    Four-field FEN cannot acquire fictitious halfmove/fullmove counters: it is
    checked through the existing EPD-compatible position representation.
    """
    if family == "epd":
        first = parse_epd(text)
        serialized = first.to_epd()
        second = parse_epd(serialized)
        if second != first or second.to_epd() != serialized:
            raise LawfulCorpusError("EPD operation/position semantic comparison changed")
        return "PASS", "canonical EPD semantic position + ordered opaque operations"
    if family == "fen":
        parts = text.strip().split()
        if len(parts) == 6:
            original = PositionState.from_fen(text.strip())
            canonical = original.to_fen()
            if PositionState.from_fen(canonical) != original:
                raise LawfulCorpusError("six-field FEN semantic reimport changed")
            return "PASS", "six-field FEN semantic read-write-reimport"
        if len(parts) == 4:
            original = parse_epd(text.strip())
            canonical = original.to_epd()
            if parse_epd(canonical) != original:
                raise LawfulCorpusError("four-field position reimport changed")
            return "PARTIAL", "four-field FEN-like position; no source counters existed"
        raise LawfulCorpusError("unexpected FEN field count")
    raise LawfulCorpusError("unsupported original position family")


def _qualify_pinned_source(record: dict, root: Path, verified: dict) -> dict:
    family, expected_count = EXPECTED[record["id"]]
    raw = _bounded_direct_snapshot(
        _direct_path(root, record["external_checkout_path"]), record["max_bytes"],
    )
    digest = hashlib.sha256(raw).hexdigest()
    if (
        digest != verified["original_sha256"]
        or digest != record["sha256"]
        or len(raw) != verified["original_bytes"]
        or len(raw) != record["indexed_bytes"]
    ):
        raise LawfulCorpusError("original upstream source changed between acquisition and semantic read")
    lines = [line.strip() for line in raw.decode("utf-8", errors="strict").splitlines() if line.strip()]
    if len(lines) != expected_count:
        raise LawfulCorpusError("original position record count drift")
    counts = {"PASS": 0, "PARTIAL": 0, "FAIL": 0}
    errors = []
    notes = {}
    for index, line in enumerate(lines, 1):
        try:
            verdict, note = qualify_original_record(line, family)
            counts[verdict] += 1
            notes[note] = notes.get(note, 0) + 1
        except (EpdParseError, LawfulCorpusError, ValueError, TypeError, OverflowError) as exc:
            counts["FAIL"] += 1
            if len(errors) < MAX_FAILURE_NOTES:
                # Never leak source bytes into a public artifact.
                errors.append({"line": index, "category": type(exc).__name__})
    if sum(counts.values()) != expected_count:
        raise LawfulCorpusError("semantic accounting incomplete")
    status = (
        "PASS" if counts["PASS"] == expected_count
        else "FAIL" if counts["FAIL"] == expected_count
        else "PARTIAL"
    )
    return {
        "source_id": record["id"],
        "format": family.upper(),
        "original_sha256": digest,
        "original_git_blob": verified["original_git_blob"],
        "license_sha256": verified["original_license_sha256"],
        "original_record_count": expected_count,
        "actual_importer": "acs.epd.parse_epd" if family == "epd" else "acs.position_editor.PositionState / acs.epd.parse_epd",
        "expected": "exact original-byte semantic parse, serialize and reimport, no field/operation loss",
        "actual": {"counts": counts, "semantic_scope": notes, "failure_categories": errors},
        "qualification": status,
        "real_source_read": True,
        "mocked": False,
        "redistribution": "EXCLUDED",
    }


def qualify_external_position_sources(records: tuple[dict, ...], root: Path) -> dict:
    """Genuine-only entry point. Never accept invented verification receipts."""
    selection = tuple(x for x in records if x.get("id") in EXPECTED)
    originals = verify_real_position_sources(selection, root)
    verified = {v["source_id"]: v for v in originals}
    rows = [
        _qualify_pinned_source(record, root, verified[record["id"]])
        for record in sorted(selection, key=lambda x: x["id"])
    ]
    return {
        "schema": "accessible-chess-section39-external-original-position-semantics-v1",
        "sources": rows,
        "source_count": len(rows),
        "total_original_records": sum(r["original_record_count"] for r in rows),
        "all_real_source_semantics_pass": all(r["qualification"] == "PASS" for r in rows),
        "mock_qualification_permitted": False,
        "section39_terminal_done": False,
    }


def main() -> None:
    REPORT.unlink(missing_ok=True)
    head = _source_head()
    checkout = os.environ.get("ACS_37_EPD2DOC_ROOT")
    if not checkout:
        raise LawfulCorpusError("temporary licensed upstream checkout absent")
    report = qualify_external_position_sources(load_catalog(), Path(checkout))
    report["source_commit_sha"] = head
    staged = REPORT.with_suffix(".tmp")
    try:
        staged.write_text(json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(staged, REPORT)
    finally:
        staged.unlink(missing_ok=True)
    if any(r["actual"]["counts"]["FAIL"] for r in report["sources"]):
        raise LawfulCorpusError("genuine upstream position semantic failure; see retained receipt")
    print(json.dumps({
        "source_commit_sha": head,
        "original_position_count": report["total_original_records"],
        "per_source_status": {r["source_id"]: r["qualification"] for r in report["sources"]},
        "section39_done": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
