#!/usr/bin/env python3
"""Fail-closed validation for the staged Oxford-5000 additions translation ledger.

Development/CI tooling only. Uses Python standard library and is not shipped as a
WordDeck runtime dependency.
"""

from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path
import sys

EXPECTED_FIRST_BATCH = 100
ALLOWED_STATUS = {"verified", "corrected", "needs_second_pass", "pending"}


def validate_tsv(text: str, require_first_batch_resolved: bool = True) -> dict[str, int]:
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    required = {"id", "level", "source", "meta", "ukrainian", "status", "notes"}
    if reader.fieldnames is None or set(reader.fieldnames) != required:
        raise ValueError(f"Unexpected header: {reader.fieldnames!r}")

    rows = list(reader)
    if len(rows) < EXPECTED_FIRST_BATCH:
        raise ValueError(f"Expected at least {EXPECTED_FIRST_BATCH} staged additions, got {len(rows)}")

    seen_ids: set[str] = set()
    unresolved = 0
    verified = 0
    corrected = 0

    for index, row in enumerate(rows, start=1):
        entry_id = row["id"].strip()
        source = row["source"].strip()
        target = row["ukrainian"].strip()
        status = row["status"].strip()

        if not entry_id or not source or not row["level"].strip() or not row["meta"].strip():
            raise ValueError(f"Row {index} has blank required source metadata")
        if entry_id in seen_ids:
            raise ValueError(f"Duplicate stable ID: {entry_id}")
        seen_ids.add(entry_id)
        if status not in ALLOWED_STATUS:
            raise ValueError(f"Row {index} has unsupported status {status!r}")
        if status in {"verified", "corrected", "needs_second_pass"} and not target:
            raise ValueError(f"Row {index} has status {status!r} but no Ukrainian translation")
        if status in {"needs_second_pass", "pending"}:
            unresolved += 1
        elif status == "verified":
            verified += 1
        elif status == "corrected":
            corrected += 1

    first_batch = rows[:EXPECTED_FIRST_BATCH]
    for ordinal, row in enumerate(first_batch, start=1):
        expected = f"ox5000-add-{ordinal:04d}"
        if row["id"].strip() != expected:
            raise ValueError(
                f"First staged batch must be contiguous: expected {expected}, got {row['id']!r}"
            )

    first_unresolved = sum(
        row["status"].strip() in {"needs_second_pass", "pending"} for row in first_batch
    )
    if require_first_batch_resolved and first_unresolved:
        raise ValueError(f"First 100 additions still contain {first_unresolved} unresolved rows")

    return {
        "rows": len(rows),
        "verified": verified,
        "corrected": corrected,
        "unresolved": unresolved,
        "first_batch_unresolved": first_unresolved,
    }


def self_test() -> None:
    header = "id\tlevel\tsource\tmeta\tukrainian\tstatus\tnotes\n"
    good_rows = []
    for ordinal in range(1, 101):
        good_rows.append(
            f"ox5000-add-{ordinal:04d}\tB2\tword{ordinal}\tn. B2\tслово{ordinal}\tverified\t"
        )
    result = validate_tsv(header + "\n".join(good_rows) + "\n")
    assert result["rows"] == 100
    assert result["first_batch_unresolved"] == 0

    bad = good_rows.copy()
    bad[9] = "ox5000-add-0010\tB2\tword10\tn. B2\tслово10\tneeds_second_pass\tambiguous"
    try:
        validate_tsv(header + "\n".join(bad) + "\n")
    except ValueError as exc:
        assert "unresolved" in str(exc)
    else:
        raise AssertionError("Validator accepted an unresolved first-batch row")

    duplicate = good_rows.copy()
    duplicate[99] = duplicate[98]
    try:
        validate_tsv(header + "\n".join(duplicate) + "\n")
    except ValueError as exc:
        assert "Duplicate" in str(exc) or "contiguous" in str(exc)
    else:
        raise AssertionError("Validator accepted a duplicate stable ID")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=str(Path(__file__).resolve().parents[1] / "QA" / "oxford5000_additions_translation.tsv"),
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        print("Oxford-5000 additions QA validator self-test passed.")
        return 0

    path = Path(args.input)
    result = validate_tsv(path.read_text(encoding="utf-8-sig"))
    print(
        "Oxford-5000 additions QA passed: "
        f"rows={result['rows']} verified={result['verified']} corrected={result['corrected']} "
        f"unresolved={result['unresolved']} first_batch_unresolved={result['first_batch_unresolved']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Oxford-5000 additions QA FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
