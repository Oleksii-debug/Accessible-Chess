#!/usr/bin/env python3
"""Canonicalize the already reviewed Oxford 5000 translation groups into lexical rows.

Development/build-time utility only. This is intentionally conservative: it consumes only
review material already marked verified, applies the explicit row-split ledger for known
legacy multi-POS groups, restores the audited missing `assumption` row, and fails closed on
any structure it does not understand.

The resulting IDs are lexical-row IDs, not staging/order IDs. They are derived only from
headword + part of speech + CEFR, so reordering the official page or changing an Oxford
entry URL cannot invalidate a user's stable WordDeck identity.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

POS_ABBREVIATIONS = {
    "n.": "noun",
    "v.": "verb",
    "adj.": "adjective",
    "adv.": "adverb",
    "prep.": "preposition",
    "conj.": "conjunction",
    "pron.": "pronoun",
    "det.": "determiner",
    "exclam.": "exclamation",
    "modal v.": "modal verb",
    "number": "number",
}
ALLOWED_LEVELS = {"B2", "C1"}
EXPECTED_LEGACY_GROUPS = 200
EXPECTED_CANONICAL_ROWS = 215


@dataclass(frozen=True)
class CanonicalRow:
    entry_id: str
    source: str
    part_of_speech: str
    level: str
    ukrainian: str
    status: str
    legacy_id: str
    source_check: str
    order_key: tuple[int, int]


def lexical_entry_id(source: str, part_of_speech: str, level: str) -> str:
    identity = "\x1f".join((source.strip().casefold(), part_of_speech.strip().casefold(), level.strip().casefold()))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"ox5000-{digest}"


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def legacy_number(legacy_id: str) -> int:
    match = re.fullmatch(r"ox5000-add-(\d{4})", legacy_id)
    if not match:
        raise ValueError(f"Unexpected legacy ID: {legacy_id!r}")
    return int(match.group(1))


def parse_single_meta(meta: str, declared_level: str) -> tuple[str, str]:
    raw = " ".join(meta.strip().split())
    if "," in raw or "/" in declared_level:
        raise ValueError(f"Merged POS/level metadata must be handled by split map, got meta={meta!r}, level={declared_level!r}")

    level_match = re.search(r"\b([ABC][12])\b$", raw, re.IGNORECASE)
    if not level_match:
        raise ValueError(f"Could not parse CEFR from meta {meta!r}")
    level = level_match.group(1).upper()
    if level not in ALLOWED_LEVELS:
        raise ValueError(f"Oxford 5000-exclusive row has unexpected level {level!r}")
    if declared_level.upper() != level:
        raise ValueError(f"Declared level {declared_level!r} disagrees with meta {meta!r}")

    pos_raw = raw[: level_match.start()].strip()
    part_of_speech = POS_ABBREVIATIONS.get(pos_raw)
    if part_of_speech is None:
        raise ValueError(f"Unknown POS abbreviation in meta {meta!r}")
    return part_of_speech, level


def load_verified_legacy(qa_dir: Path) -> dict[str, dict[str, str]]:
    paths = [
        qa_dir / "oxford5000_additions_translation.tsv",
        qa_dir / "oxford5000_additions_second_pass_0101_0120.tsv",
        qa_dir / "oxford5000_additions_second_pass_0121_0140.tsv",
        qa_dir / "oxford5000_additions_second_pass_0141_0200.tsv",
    ]
    rows: dict[str, dict[str, str]] = {}
    for path in paths:
        for row in read_tsv(path):
            legacy_id = row.get("id", "").strip()
            if not legacy_id:
                raise ValueError(f"Blank legacy ID in {path}")
            if legacy_id in rows:
                raise ValueError(f"Duplicate reviewed legacy ID {legacy_id}")
            if row.get("status", "").strip() != "verified":
                raise ValueError(f"Refusing non-verified legacy row {legacy_id}: {row.get('status')!r}")
            if not row.get("ukrainian", "").strip():
                raise ValueError(f"Blank Ukrainian translation for {legacy_id}")
            rows[legacy_id] = row

    expected_ids = {f"ox5000-add-{number:04d}" for number in range(1, EXPECTED_LEGACY_GROUPS + 1)}
    actual_ids = set(rows)
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        raise ValueError(f"Reviewed legacy coverage is not exactly 0001-0200; missing={missing}, extra={extra}")
    return rows


def load_split_map(qa_dir: Path) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, str]]]:
    by_legacy: dict[str, list[dict[str, str]]] = {}
    missing_rows: list[dict[str, str]] = []
    for row in read_tsv(qa_dir / "oxford5000_legacy_split_map_0001_0200.tsv"):
        if row.get("status", "").strip() != "verified":
            raise ValueError(f"Split-map row is not verified: {row}")
        for field in ("source", "part_of_speech", "level", "ukrainian"):
            if not row.get(field, "").strip():
                raise ValueError(f"Split-map row has blank {field}: {row}")
        if row["level"].strip().upper() not in ALLOWED_LEVELS:
            raise ValueError(f"Split-map row has invalid level: {row}")
        legacy_id = row["legacy_id"].strip()
        if legacy_id == "__missing__":
            missing_rows.append(row)
        else:
            legacy_number(legacy_id)
            by_legacy.setdefault(legacy_id, []).append(row)
    return by_legacy, missing_rows


def canonicalize(qa_dir: Path) -> list[CanonicalRow]:
    legacy = load_verified_legacy(qa_dir)
    split_by_legacy, missing_rows = load_split_map(qa_dir)

    output: list[CanonicalRow] = []
    for legacy_id in sorted(legacy, key=legacy_number):
        source_row = legacy[legacy_id]
        number = legacy_number(legacy_id)
        split_rows = split_by_legacy.get(legacy_id)
        if split_rows:
            for suborder, split in enumerate(split_rows):
                source = split["source"].strip()
                pos = split["part_of_speech"].strip()
                level = split["level"].strip().upper()
                output.append(CanonicalRow(
                    lexical_entry_id(source, pos, level), source, pos, level,
                    split["ukrainian"].strip(), "verified", legacy_id,
                    split.get("source_check", "").strip(), (number * 10, suborder),
                ))
            continue

        pos, level = parse_single_meta(source_row["meta"], source_row["level"])
        source = source_row["source"].strip()
        output.append(CanonicalRow(
            lexical_entry_id(source, pos, level), source, pos, level,
            source_row["ukrainian"].strip(), "verified", legacy_id,
            (source_row.get("source_check") or source_row.get("notes") or "").strip(), (number * 10, 0),
        ))

    # The structural audit places assumption noun B2 between legacy assistance 0129 and assurance 0130.
    for suborder, missing in enumerate(missing_rows, start=1):
        source = missing["source"].strip()
        pos = missing["part_of_speech"].strip()
        level = missing["level"].strip().upper()
        output.append(CanonicalRow(
            lexical_entry_id(source, pos, level), source, pos, level,
            missing["ukrainian"].strip(), "verified", "__missing__",
            missing.get("source_check", "").strip(), (129 * 10 + 5, suborder),
        ))

    output.sort(key=lambda row: row.order_key)
    identities = [(row.source.casefold(), row.part_of_speech.casefold(), row.level) for row in output]
    if len(identities) != len(set(identities)):
        raise ValueError("Canonicalization produced duplicate headword/POS/CEFR identities")
    if len({row.entry_id for row in output}) != len(output):
        raise ValueError("Canonicalization produced a stable-ID collision")
    if len(output) != EXPECTED_CANONICAL_ROWS:
        raise ValueError(f"Expected {EXPECTED_CANONICAL_ROWS} canonical rows through blow, got {len(output)}")
    if (output[0].source, output[0].part_of_speech, output[0].level) != ("abolish", "verb", "C1"):
        raise ValueError(f"Unexpected first canonical row: {output[0]}")
    if (output[-1].source, output[-1].part_of_speech, output[-1].level) != ("blow", "noun", "B2"):
        raise ValueError(f"Unexpected last canonical row: {output[-1]}")
    if not any(row.source == "assumption" and row.part_of_speech == "noun" and row.level == "B2" for row in output):
        raise ValueError("Audited missing assumption noun B2 row was not restored")
    if any(not row.ukrainian.strip() or row.status != "verified" for row in output):
        raise ValueError("Canonical output contains a blank or non-verified translation")
    return output


def write_tsv(rows: list[CanonicalRow], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["entry_id", "source", "part_of_speech", "level", "ukrainian", "status", "legacy_id", "source_check"]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: getattr(row, field) for field in fields})


def self_test() -> None:
    assert lexical_entry_id("abuse", "noun", "C1") == lexical_entry_id(" Abuse ", "NOUN", "c1")
    assert lexical_entry_id("abuse", "noun", "C1") != lexical_entry_id("abuse", "verb", "C1")
    assert parse_single_meta("v. C1", "C1") == ("verb", "C1")
    assert parse_single_meta("adj. B2", "B2") == ("adjective", "B2")
    try:
        parse_single_meta("n., v. C1", "C1")
    except ValueError:
        pass
    else:
        raise RuntimeError("Merged POS metadata was accepted without the explicit split map")
    print("Oxford reviewed-row canonicalizer self-test passed.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qa-dir", type=Path, default=Path(__file__).resolve().parents[1] / "QA")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output is None:
        parser.error("--output is required unless --self-test is used")
    rows = canonicalize(args.qa_dir)
    write_tsv(rows, args.output)
    print(f"Canonicalized {len(rows)} verified Oxford 5000 rows through noun blow to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
