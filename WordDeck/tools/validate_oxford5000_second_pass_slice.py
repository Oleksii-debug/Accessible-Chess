#!/usr/bin/env python3
"""Fail-closed validation for source-checked Oxford 5000 second-pass slices.

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


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows:
        raise RuntimeError(f"No rows found in {path}")
    return [{k: (v or "").strip() for k, v in row.items()} for row in rows]


def validate(batch_path: Path, slice_path: Path, first: int, last: int) -> None:
    batch = read_tsv(batch_path)
    verified = read_tsv(slice_path)
    batch_by_id = {row["id"]: row for row in batch}

    expected_ids = [f"ox5000-add-{number:04d}" for number in range(first, last + 1)]
    actual_ids = [row.get("id", "") for row in verified]
    if actual_ids != expected_ids:
        raise RuntimeError(f"Expected exact ordered IDs {expected_ids[0]}..{expected_ids[-1]}, got {actual_ids}")
    if len(actual_ids) != len(set(actual_ids)):
        raise RuntimeError("Second-pass slice contains duplicate IDs")

    required = {"id", "level", "source", "meta", "ukrainian", "status", "source_check"}
    for row in verified:
        if not required.issubset(row):
            raise RuntimeError(f"Second-pass row has unexpected columns: {row.keys()}")
        entry_id = row["id"]
        original = batch_by_id.get(entry_id)
        if original is None:
            raise RuntimeError(f"Second-pass ID is absent from extraction batch: {entry_id}")
        for field in ("level", "source", "meta"):
            if row[field] != original[field]:
                raise RuntimeError(f"{entry_id}: {field} drifted from source extraction batch")
        if row["status"] != "verified":
            raise RuntimeError(f"{entry_id}: only verified rows are allowed in a second-pass slice")
        if not row["ukrainian"]:
            raise RuntimeError(f"{entry_id}: Ukrainian translation is blank")
        if len(row["source_check"]) < 20 or "OALD" not in row["source_check"]:
            raise RuntimeError(f"{entry_id}: source-check evidence is missing or too vague")

    print(f"Oxford 5000 second-pass slice validated: {len(verified)} rows, {expected_ids[0]}..{expected_ids[-1]}.")


def self_test() -> None:
    validate(DEFAULT_BATCH, DEFAULT_SLICE, 101, 120)


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
    validate(args.batch, args.slice, args.first, args.last)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
