"""Section 39 current-source Chess960 and EPD format qualification from Stockfish.

Both ZIPs are authentic SHA-pinned upstream Stockfish CC0 assets already
cataloged under Section 37. Test every original record using existing
PositionState/EPD parsers, record supported vs unsupported Chess960 layouts
individually, never synthesize a legal position or rewrite unknown castling.
"""
from __future__ import annotations

import hashlib
import json
import os

from acs.epd import EpdParseError, parse_epd
from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog, read_verified_zip_member
from acs.position_editor import PositionState, PositionValidationError
from tools.revised_sections37_38_offline_manifest import ROOT, _source_head

REPORT = ROOT / "section39-stockfish-chess960-epd-qualification.json"
IDS = (
    "stockfish_frc_openings_epd_zip",
    "stockfish_4mvs_90_99_epd_zip",
)


def qualify_stockfish_real_positions() -> dict:
    records = {x["id"]: x for x in load_catalog()}
    rows = []
    for source_id in IDS:
        record = records.get(source_id)
        if (
            record is None
            or record.get("acquisition") != "VENDORED_SOURCE_VERIFIED"
            or not str(record.get("license", "")).startswith("CC0")
            or not str(record.get("redistribution", "")).startswith("permitted")
        ):
            raise LawfulCorpusError("original Stockfish Chess960 EPD corpus unavailable or rights unverified")
        source = ROOT / record["local_source"]
        raw = read_verified_zip_member(
            source, record, expected_member=record["zip_member"],
            max_unpacked_bytes=record["max_unpacked_bytes"],
        )
        digest = hashlib.sha256(raw).hexdigest()
        lines = [line.strip() for line in raw.decode("utf-8-sig", errors="strict").splitlines()
                 if line.strip()]
        if not 2 <= len(lines) <= 50_000:
            raise LawfulCorpusError("original Stockfish EPD record count outside bounded scope")
        verified, unsupported = 0, 0
        first_nonpassing = []
        for index, line in enumerate(lines, 1):
            if len(line) > 4096 or any(ord(ch) < 32 for ch in line):
                raise LawfulCorpusError("original Stockfish EPD record has invalid resource bounds")
            try:
                if len(line.split()) == 6 and ";" not in line:
                    first = PositionState.from_fen(line)
                    encoded = first.to_fen()
                    second = PositionState.from_fen(encoded)
                else:
                    first = parse_epd(line)
                    encoded = first.to_epd()
                    second = parse_epd(encoded)
                if first != second:
                    raise LawfulCorpusError("original Stockfish semantic position/EPD operation altered after roundtrip")
                verified += 1
            except (PositionValidationError, EpdParseError, ValueError) as exc:
                unsupported += 1
                if len(first_nonpassing) < 12:
                    # No source chess record is copied to report.
                    first_nonpassing.append({"original_record_index": index,
                                             "reason": type(exc).__name__})
        if verified + unsupported != len(lines):
            raise LawfulCorpusError("original Chess960 semantically checked record count incomplete")
        rows.append({
            "source_id": source_id,
            "source_format": "STOCKFISH_EPD_ZIP",
            "source_zip_sha256": record["sha256"],
            "original_member_sha256": digest,
            "original_member_bytes": len(raw),
            "original_record_count": len(lines),
            "actual_canonical_position_roundtrip_count": verified,
            "unsupported_original_record_count": unsupported,
            "actual_importer": "acs.epd.parse_epd / acs.position_editor.PositionState",
            "first_unsupported": first_nonpassing,
            "expected": "real authentic original Chess960/standard EPD positions parsed and semantically reimported or honestly classified unsupported",
            "qualification": ("PASS" if unsupported == 0
                              else "PARTIAL" if verified else "UNSUPPORTED"),
            "real_source_read": True,
            "mocked": False,
        })
    return {
        "schema": "acs-section39-authentic-stockfish-chess960-epd-v1",
        "source_count": len(rows),
        "sources": rows,
        "original_total_positions": sum(r["original_record_count"] for r in rows),
        "original_semantic_supported_count": sum(r["actual_canonical_position_roundtrip_count"] for r in rows),
        "original_semantic_unsupported_count": sum(r["unsupported_original_record_count"] for r in rows),
        "section39_terminal_done": False,
    }


def main():
    REPORT.unlink(missing_ok=True)
    sha = _source_head()
    report = qualify_stockfish_real_positions()
    report["source_commit_sha"] = sha
    temp = REPORT.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8")
        os.replace(temp, REPORT)
    finally:
        temp.unlink(missing_ok=True)
    print(json.dumps({
        "source_commit_sha": sha,
        "original_real_position_count": report["original_total_positions"],
        "supported": report["original_semantic_supported_count"],
        "unsupported": report["original_semantic_unsupported_count"],
        "section39_done": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
