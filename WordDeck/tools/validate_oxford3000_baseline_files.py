#!/usr/bin/env python3
"""Freeze and independently validate the embedded Oxford 3000 baseline.

The expected Git blob IDs pin the exact eight source fragments already used by
WordDeck. The validator also reconstructs/decompresses the baseline and checks the
3308 production lexical rows, exact CEFR counts, stable unique IDs and nonblank data.
"""
from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import io
from pathlib import Path

EXPECTED_BLOBS = {
    "oxford3000_uk.tsv.gz.b64part01": "bfcda7df61d81e4f2772fa60b79ddfda4fd32905",
    "oxford3000_uk.tsv.gz.b64part02": "a1644656e3108b5bde4d465ec34adc0920e96a92",
    "oxford3000_uk.tsv.gz.b64part03": "50ab07d1ff494fd645bb1387c1298a63673a8a19",
    "oxford3000_uk.tsv.gz.b64part04": "7670452ca59e1be71f3e77e9cf8dd6c28e3fb6cf",
    "oxford3000_uk.tsv.gz.b64part05": "473f03d8eb9f2c79d2f908f88635e2194b546dc6",
    "oxford3000_uk.tsv.gz.b64part06": "ed75ba029737eaf79c50cb5960122d5ba56d0166",
    "oxford3000_uk.tsv.gz.b64part07": "fa1d81074faf59b07781faf8d382da7c0af88241",
    "oxford3000_uk.tsv.gz.b64part08": "92a92b67f6dce721c7adca3054c955226274ecc7",
}
EXPECTED_ROWS = 3308
EXPECTED_LEVEL_COUNTS = {"A1": 900, "A2": 872, "B1": 809, "B2": 727}


def git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def validate(data_dir: Path) -> tuple[list[dict[str, str]], str]:
    found = sorted(path.name for path in data_dir.glob("oxford3000_uk.tsv.gz.b64part*"))
    expected = sorted(EXPECTED_BLOBS)
    if found != expected:
        missing = sorted(set(expected) - set(found))
        extra = sorted(set(found) - set(expected))
        raise ValueError(f"Oxford 3000 baseline fragment set changed; missing={missing}, extra={extra}")

    encoded_parts: list[str] = []
    for name in expected:
        path = data_dir / name
        raw = path.read_bytes()
        actual_blob = git_blob_sha1(raw)
        if actual_blob != EXPECTED_BLOBS[name]:
            raise ValueError(
                f"Oxford 3000 baseline fragment changed: {name}: {actual_blob} != {EXPECTED_BLOBS[name]}"
            )
        encoded_parts.append(raw.decode("ascii").strip())

    try:
        compressed = base64.b64decode("".join(encoded_parts), validate=True)
        tsv_bytes = gzip.decompress(compressed)
        text = tsv_bytes.decode("utf-8")
    except Exception as exc:
        raise ValueError(f"Oxford 3000 baseline fragments no longer decode/decompress cleanly: {exc}") from exc

    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    required_fields = {"entryId", "level", "source", "target"}
    if reader.fieldnames is None or not required_fields.issubset(reader.fieldnames):
        raise ValueError(f"Oxford 3000 baseline TSV schema changed: {reader.fieldnames}")
    rows = list(reader)
    if len(rows) != EXPECTED_ROWS:
        raise ValueError(f"Oxford 3000 baseline row count changed: {len(rows)} != {EXPECTED_ROWS}")

    ids: set[str] = set()
    level_counts = {key: 0 for key in EXPECTED_LEVEL_COUNTS}
    for number, row in enumerate(rows, start=1):
        entry_id = (row.get("entryId") or "").strip()
        level = (row.get("level") or "").strip().upper()
        source = (row.get("source") or "").strip()
        target = (row.get("target") or "").strip()
        if not entry_id or not source or not target:
            raise ValueError(f"Oxford 3000 baseline row {number} has a blank required field")
        if entry_id.casefold() in ids:
            raise ValueError(f"Oxford 3000 baseline duplicate entry ID: {entry_id}")
        ids.add(entry_id.casefold())
        if level not in level_counts:
            raise ValueError(f"Oxford 3000 baseline row {number} has unsupported CEFR level {level!r}")
        level_counts[level] += 1

    if level_counts != EXPECTED_LEVEL_COUNTS:
        raise ValueError(f"Oxford 3000 baseline CEFR counts changed: {level_counts} != {EXPECTED_LEVEL_COUNTS}")

    digest = hashlib.sha256(tsv_bytes).hexdigest()
    return rows, digest


def write_report(data_dir: Path, rows: list[dict[str, str]], digest: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        ("metric", "value"),
        ("baseline_rows", str(len(rows))),
        ("a1", str(EXPECTED_LEVEL_COUNTS["A1"])),
        ("a2", str(EXPECTED_LEVEL_COUNTS["A2"])),
        ("b1", str(EXPECTED_LEVEL_COUNTS["B1"])),
        ("b2", str(EXPECTED_LEVEL_COUNTS["B2"])),
        ("baseline_tsv_sha256", digest),
        ("fragment_count", str(len(EXPECTED_BLOBS))),
        ("fragment_git_blob_ids_verified", "YES"),
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerows(lines)


def self_test() -> None:
    assert git_blob_sha1(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"
    assert sum(EXPECTED_LEVEL_COUNTS.values()) == EXPECTED_ROWS
    assert len(EXPECTED_BLOBS) == 8
    print("Oxford 3000 baseline validator self-test passed: Git blob hashing and locked counts are deterministic.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "Data")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    rows, digest = validate(args.data_dir)
    if args.report is not None:
        write_report(args.data_dir, rows, digest, args.report)
    print(
        "Oxford 3000 baseline verified: "
        f"rows={len(rows)}, A1=900, A2=872, B1=809, B2=727, sha256={digest}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
