#!/usr/bin/env python3
"""Fail-closed validation for source-checked legacy Oxford 5000 translation groups.

IMPORTANT: the historical ox5000-add-0001..0200 IDs are translation-working
groups, not canonical production lexical rows. This utility only protects the
reviewed Ukrainian material from drift while canonical row-preserving migration
is performed. See QA/OXFORD5000_STRUCTURE_AUDIT_0001_0200.md.

Development/CI utility only. Uses Python standard library and never ships in the
WordDeck runtime.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BATCH = ROOT / "QA" / "oxford5000_additions_batch_0101_0200.tsv"
DEFAULT_SLICE = ROOT / "QA" / "oxford5000_additions_second_pass_0101_0120.tsv"
SELF_TEST_SLICES = (
    (ROOT / "QA" / "oxford5000_additions_second_pass_0101_0120.tsv", 101, 120),
    (ROOT / "QA" / "oxford5000_additions_second_pass_0121_0140.tsv", 121, 140),
    (ROOT / "QA" / "oxford5000_additions_second_pass_0141_0200.tsv", 141, 200),
)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows:
        raise RuntimeError(f"No rows found in {path}")
    return [{k: (v or "").strip() for k, v in row.items()} for row in rows]


def has_authoritative_source_evidence(text: str) -> bool:
    """Require an explicit Oxford source marker, not a generic 'reviewed' note."""
    normalized = text.casefold()
    return "oald" in normalized or "oxford 5000 list" in normalized


def validate(batch_path: Path, slice_path: Path, first: int, last: int) -> None:
    batch = read_tsv(batch_path)
    verified = read_tsv(slice_path)
    batch_by_id = {row["id"]: row for row in batch}

    expected_ids = [f"ox5000-add-{number:04d}" for number in range(first, last + 1)]
    actual_ids = [row.get("id", "") for row in verified]
    if actual_ids != expected_ids:
        raise RuntimeError(f"Expected exact ordered legacy IDs {expected_ids[0]}..{expected_ids[-1]}, got {actual_ids}")
    if len(actual_ids) != len(set(actual_ids)):
        raise RuntimeError("Legacy second-pass slice contains duplicate IDs")

    required = {"id", "level", "source", "meta", "ukrainian", "status", "source_check"}
    allowed_levels = {"B2", "C1"}
    for row in verified:
        if not required.issubset(row):
            raise RuntimeError(f"Legacy second-pass row has unexpected columns: {row.keys()}")
        entry_id = row["id"]
        original = batch_by_id.get(entry_id)
        if original is None:
            raise RuntimeError(f"Legacy second-pass ID is absent from its translation batch: {entry_id}")
        for field in ("level", "source", "meta"):
            if row[field] != original[field]:
                raise RuntimeError(f"{entry_id}: {field} drifted from legacy extraction/translation batch")
        if row["level"] not in allowed_levels:
            raise RuntimeError(f"{entry_id}: Oxford 5000 translation group has invalid CEFR level {row['level']!r}")
        if row["status"] != "verified":
            raise RuntimeError(f"{entry_id}: only verified rows are allowed in a legacy second-pass slice")
        if not row["ukrainian"]:
            raise RuntimeError(f"{entry_id}: Ukrainian translation is blank")
        if len(row["source_check"]) < 20 or not has_authoritative_source_evidence(row["source_check"]):
            raise RuntimeError(
                f"{entry_id}: source-check evidence must explicitly name OALD or the Oxford 5000 list"
            )

    print(
        f"Legacy Oxford 5000 translation-group slice validated: {len(verified)} groups, "
        f"{expected_ids[0]}..{expected_ids[-1]}. Canonical lexical-row validation is separate."
    )


def self_test() -> None:
    total = 0
    for slice_path, first, last in SELF_TEST_SLICES:
        validate(DEFAULT_BATCH, slice_path, first, last)
        total += last - first + 1
    if total != 100:
        raise RuntimeError(f"Expected 100 legacy translation groups in CI checkpoint, got {total}")
    print(
        "Legacy Oxford 5000 translation material validated through group 0200 "
        "(100 groups in this batch); no claim of canonical lexical-row completeness."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--slice", type=Path, default=DEFAULT_SLICE)
    parser.add_argument("--first", type=int, default=101)
    parser.add_argument("--last", type=int, default=120)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.first > args.last:
        raise SystemExit("--first must not exceed --last")
    if args.self_test:
        self_test()
    else:
        validate(args.batch, args.slice, args.first, args.last)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
