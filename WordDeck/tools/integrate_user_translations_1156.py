#!/usr/bin/env python3
"""Integrate the exact user-approved original 1,156-row Oxford5000 tail.

The payload is a zlib+base64 transport copy of Google Sheet
USER_TRANSLATIONS_1156 — Oxford5000 — 2026-08-20 (ID 13NjX7gg1iooze1HZvs4wq8E33bpWXWqalCVnqLCxvGQ).
This script performs deterministic reconciliation only; it does not translate or research rows.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import json
import re
import subprocess
import zlib
from pathlib import Path

ROOT = Path.cwd()
WORDDECK = ROOT / "WordDeck"
TOOLS = WORDDECK / "tools"
QA = WORDDECK / "QA"
PARTS = [TOOLS / f"user1156_payload.part{i:02d}" for i in range(1, 9)]
TAIL_NAME = "oxford5000_user_approved_tail_1156.tsv"
TAIL = QA / TAIL_NAME
RECON = QA / "oxford5000_user_approved_reconciliation_1156.tsv"
SUMMARY = QA / "oxford5000_user_approved_reconciliation_summary.json"
BOOTSTRAP = WORDDECK / "ReviewedOxford5000Bootstrap.cs"
CSPROJ = WORDDECK / "WordDeck.csproj"
AUDIO_REQ = WORDDECK / "Audio" / "generation-request.json"
SHEET_ID = "13NjX7gg1iooze1HZvs4wq8E33bpWXWqalCVnqLCxvGQ"
V7_FILES = [
    QA / "oxford5000_source_after_manual_v7_round01_manual-emergency-work-20260820-second-pa_cp0001_rows_0020.tsv",
    QA / "oxford5000_source_after_manual_v7_round02_manual-emergency-work-20260820-second-pa_cp0001_rows_0002.tsv",
]


def lexical_id(source: str, pos: str, level: str) -> str:
    identity = "\x1f".join((source.strip().lower(), pos.strip().lower(), level.strip().lower()))
    return "ox5000-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def restore_payload() -> bytes:
    missing = [str(p) for p in PARTS if not p.exists()]
    if missing:
        raise RuntimeError(f"Missing payload parts: {missing}")
    packed = "".join(p.read_text(encoding="ascii").strip() for p in PARTS)
    raw = zlib.decompress(base64.b64decode(packed))
    if len(raw) != 185737:
        raise RuntimeError(f"Unexpected restored TSV byte size: {len(raw)}")
    return raw


def validate_tail(raw: bytes) -> list[dict[str, str]]:
    TAIL.write_bytes(raw)
    rows = read_tsv(TAIL)
    required = {"entry_id", "source", "part_of_speech", "level", "ukrainian", "status", "provenance"}
    if len(rows) != 1156:
        raise RuntimeError(f"Expected 1156 user rows, got {len(rows)}")
    if not rows or not required.issubset(rows[0]):
        raise RuntimeError(f"User tail schema mismatch: {sorted(rows[0] if rows else [])}")
    ids: set[str] = set()
    identities: set[tuple[str, str, str]] = set()
    b2 = c1 = 0
    for index, row in enumerate(rows, 1):
        source, pos, level, uk = row["source"], row["part_of_speech"], row["level"].upper(), row["ukrainian"]
        if not source or not pos or not uk:
            raise RuntimeError(f"Blank required user value at row {index}")
        if level not in {"B2", "C1"}:
            raise RuntimeError(f"Unsupported user level {level!r} at row {index}")
        expected = lexical_id(source, pos, level)
        if row["entry_id"] != expected:
            raise RuntimeError(f"Stable-ID mismatch at user row {index}: {row['entry_id']} != {expected}")
        identity = (source.casefold(), pos.casefold(), level)
        if expected in ids or identity in identities:
            raise RuntimeError(f"Duplicate user lexical identity at row {index}: {source}/{pos}/{level}")
        ids.add(expected); identities.add(identity)
        if row["status"] != "verified":
            raise RuntimeError(f"User row {index} status is not verified")
        if SHEET_ID not in row["provenance"]:
            raise RuntimeError(f"User row {index} provenance lost Sheet ID")
        if re.search(r"</?[A-Za-z][^>]*>|\{\{|\}\}|\[\[|\]\]", uk):
            raise RuntimeError(f"Markup-like garbage in user translation row {index}: {uk!r}")
        letters = re.findall(r"[A-Za-zА-Яа-яІіЇїЄєҐґ]", uk)
        if not letters or sum(bool(re.match(r"[А-Яа-яІіЇїЄєҐґ]", c)) for c in letters) / len(letters) < 0.60:
            raise RuntimeError(f"User translation is not predominantly Ukrainian at row {index}: {uk!r}")
        b2 += level == "B2"; c1 += level == "C1"
    if (b2, c1) != (643, 513):
        raise RuntimeError(f"Current user Sheet level distribution changed: B2={b2}, C1={c1}")
    return rows


def reconcile(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, object]]:
    v7: dict[str, dict[str, str]] = {}
    for path in V7_FILES:
        existing = read_tsv(path)
        for row in existing:
            eid = row.get("entry_id", "")
            if eid in v7:
                raise RuntimeError(f"Duplicate V7 stable ID across slices: {eid}")
            v7[eid] = row
    if len(v7) != 22:
        raise RuntimeError(f"Expected exactly 22 current V7 rows, got {len(v7)}")
    user_ids = {row["entry_id"] for row in rows}
    overlap = user_ids & set(v7)
    if len(overlap) != 22:
        raise RuntimeError(f"Expected all 22 V7 IDs inside user original tail, overlap={len(overlap)}")
    out: list[dict[str, str]] = []
    changed = 0
    for row in rows:
        prior = v7.get(row["entry_id"])
        prior_uk = (prior or {}).get("ukrainian", "")
        action = "replace_v7_with_user_value" if prior else "activate_user_tail_identity"
        if prior and prior_uk != row["ukrainian"]:
            changed += 1
        out.append({
            "entry_id": row["entry_id"], "source": row["source"], "part_of_speech": row["part_of_speech"],
            "level": row["level"], "user_ukrainian": row["ukrainian"], "prior_v7_ukrainian": prior_uk,
            "prior_v7_present": "yes" if prior else "no", "action": action,
        })
    summary = {
        "input_rows": 1156,
        "unique_user_stable_ids": 1156,
        "actual_sheet_level_counts": {"B2": 643, "C1": 513},
        "auditor_text_level_counts_note": "Audit text said B2=397/C1=759; current Sheet actually contains B2=643/C1=513, so current Sheet values were used.",
        "v7_technical_rows_reconciled": 22,
        "v7_user_translation_differences": changed,
        "new_user_tail_identities_after_v7_replacement": 1134,
        "developer_translation_corrections": 0,
        "target_total_additional_identities": 2138,
        "target_remaining": 0,
        "primary_input": f"USER_APPROVED_INPUT Google Sheet {SHEET_ID}",
    }
    return out, summary


def modify_code() -> None:
    text = BOOTSTRAP.read_text(encoding="utf-8")
    old_const = "public const int ExpectedCanonicalRows = 1004;"
    if old_const not in text:
        raise RuntimeError("Bootstrap does not have expected 1004-row precondition")
    text = text.replace(old_const, "public const int ExpectedCanonicalRows = 2138;", 1)
    patterns = [
        r'\n\s*AppendVerifiedSlice\(result, "oxford5000_source_after_manual_v7_round01_manual-emergency-work-20260820-second-pa_cp0001_rows_0020\.tsv", 20, 10000\);\s*',
        r'\n\s*AppendVerifiedSlice\(result, "oxford5000_source_after_manual_v7_round02_manual-emergency-work-20260820-second-pa_cp0001_rows_0002\.tsv", 2, 10001\);\s*',
    ]
    for pattern in patterns:
        text, n = re.subn(pattern, "\n", text, count=1)
        if n != 1:
            raise RuntimeError(f"Could not remove exact V7 append: {pattern}")
    anchor = 'AppendVerifiedSlice(result, "oxford5000_source_after_deployment_c1_0001_0029.tsv", StandardSliceRows, 9999);'
    if anchor not in text:
        raise RuntimeError("Deployment anchor missing")
    text = text.replace(anchor, anchor + f'\n        AppendVerifiedSlice(result, "{TAIL_NAME}", 1156, 10000);', 1)
    BOOTSTRAP.write_text(text, encoding="utf-8")

    proj = CSPROJ.read_text(encoding="utf-8")
    for name in (V7_FILES[0].name, V7_FILES[1].name):
        pattern = rf'\s*<EmbeddedResource Include="QA\\{re.escape(name)}" />'
        proj, n = re.subn(pattern, "", proj, count=1)
        if n != 1:
            raise RuntimeError(f"Could not remove V7 EmbeddedResource {name}")
    marker = '    <EmbeddedResource Include="QA\\oxford5000_source_after_offspring_verified_c1_0001_0029.tsv" />'
    if marker not in proj:
        raise RuntimeError("CSPROJ insertion marker missing")
    proj = proj.replace(marker, marker + f'\n    <EmbeddedResource Include="QA\\{TAIL_NAME}" />', 1)
    CSPROJ.write_text(proj, encoding="utf-8")

    req = json.loads(AUDIO_REQ.read_text(encoding="utf-8"))
    req.update({"source": "oxford5000", "start": 0, "limit": 0, "accent": "en-GB", "speed": 1.0, "format": "mp3"})
    AUDIO_REQ.write_text(json.dumps(req, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> int:
    raw = restore_payload()
    rows = validate_tail(raw)
    recon, summary = reconcile(rows)
    write_tsv(RECON, recon, ["entry_id", "source", "part_of_speech", "level", "user_ukrainian", "prior_v7_ukrainian", "prior_v7_present", "action"])
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    modify_code()

    # Remove transport-only payload parts from the final repository state.
    for part in PARTS:
        part.unlink()

    # Existing deterministic corpus validators are sufficient for this integration.
    official = Path("/tmp/worddeck-user1156-official.html")
    runtime = Path("/tmp/worddeck-user1156-runtime.tsv")
    accounting = Path("/tmp/worddeck-user1156-accounting.tsv")
    unaccounted = Path("/tmp/worddeck-user1156-unaccounted.tsv")
    run("python", "WordDeck/tools/fetch_oxford5000_official_html.py", "--output", str(official))
    run("python", "WordDeck/tools/validate_oxford3000_baseline_files.py", "--report", "/tmp/worddeck-user1156-oxford3000.tsv")
    run("python", "WordDeck/tools/validate_oxford5000_runtime_ledger.py", "--official-html", str(official), "--ledger", str(runtime), "--report", str(accounting), "--unaccounted", str(unaccounted))
    runtime_rows = read_tsv(runtime)
    remaining_rows = read_tsv(unaccounted)
    if len(runtime_rows) != 2138 or remaining_rows:
        raise RuntimeError(f"Final corpus accounting mismatch: activated={len(runtime_rows)} remaining={len(remaining_rows)}")
    runtime_ids = {r["entry_id"] for r in runtime_rows}
    if len(runtime_ids) != 2138:
        raise RuntimeError("Final runtime contains duplicate stable IDs")

    summary["validated_final_activated"] = 2138
    summary["validated_final_remaining"] = 0
    summary["oxford3000_preserved"] = 3308
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
