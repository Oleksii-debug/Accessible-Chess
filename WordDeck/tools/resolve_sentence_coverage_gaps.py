#!/usr/bin/env python3
"""Resolve SentencePack gap IDs against the embedded Oxford dictionary.

Development/QA utility only. Uses Python standard library and mirrors the embedded
base64+gzip packaging format; it is not part of the shipped WordDeck runtime.
"""
from __future__ import annotations

import argparse
import base64
import csv
import gzip
import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "Data"
DEFAULT_GAPS = ROOT / "QA" / "sentence_coverage_gaps_20260817.txt"

ID_RE = re.compile(r"^oxford-(?:a1|a2|b1|b2)-\d{4}$", re.I)
WORD_RE = re.compile(r"^[A-Za-z]+(?:['’][A-Za-z]+)?$")
SUPERSCRIPT_OR_DIGIT_RE = re.compile(r"[0-9¹²³⁴⁵⁶⁷⁸⁹⁰]")
HYPHEN_RE = re.compile(r"[-‐‑‒–—]")


def load_embedded_rows() -> dict[str, dict[str, str]]:
    parts = sorted(DATA_DIR.glob("oxford3000_uk.tsv.gz.b64part*"))
    if not parts:
        raise RuntimeError("Embedded Oxford base64 parts were not found")
    encoded = "".join(p.read_text(encoding="utf-8").strip() for p in parts)
    raw = gzip.decompress(base64.b64decode(encoded))
    lines = raw.decode("utf-8-sig").splitlines()
    data_lines = [line for line in lines if line.strip() and not line.startswith("#")]
    if not data_lines:
        raise RuntimeError("Embedded dictionary contained no TSV data")
    reader = csv.DictReader(io.StringIO("\n".join(data_lines)), delimiter="\t")
    required = {"entryId", "level", "source", "target"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise RuntimeError(f"Unexpected embedded dictionary header: {reader.fieldnames}")
    rows: dict[str, dict[str, str]] = {}
    for row in reader:
        entry_id = row["entryId"].strip()
        if not entry_id or entry_id in rows:
            raise RuntimeError(f"Blank or duplicate embedded entry id: {entry_id!r}")
        rows[entry_id] = {k: (v or "").strip() for k, v in row.items()}
    return rows


def load_gap_ids(path: Path) -> list[str]:
    ids = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if ID_RE.match(value):
            ids.append(value.lower())
    if len(ids) != len(set(ids)):
        raise RuntimeError("Gap list contains duplicate Oxford IDs")
    return ids


def structural_class(source: str) -> str:
    """Classify only what can be proved from the dictionary source form itself.

    Ordering is deliberate: sense markers/annotations are unsafe to collapse even
    when the source also contains spaces or punctuation. Plain multiword phrases
    and ordinary hyphenated forms are kept separate because they can later be
    evaluated for deterministic exact phrase/token matching without conflating
    Oxford senses.
    """
    s = source.strip()
    if WORD_RE.fullmatch(s):
        return "single_surface_indexable"
    if SUPERSCRIPT_OR_DIGIT_RE.search(s):
        return "sense_numbered_unsafe_to_collapse"
    if "(" in s or ")" in s or "[" in s or "]" in s:
        return "sense_or_usage_annotated_unsafe_to_collapse"
    if "," in s or "/" in s or ";" in s:
        return "variant_or_compound_needs_semantic_review"
    if any(ch.isspace() for ch in s):
        return "plain_multiword_exact_phrase_candidate"
    if HYPHEN_RE.search(s) and any(ch.isalpha() for ch in s):
        return "hyphenated_exact_surface_candidate"
    return "other_noncanonical_needs_tokenizer_review"


def matching_action(structural: str) -> str:
    if structural == "single_surface_indexable":
        return "measure_corpus_or_inflection_evidence"
    if structural == "plain_multiword_exact_phrase_candidate":
        return "evaluate_exact_phrase_matching"
    if structural == "hyphenated_exact_surface_candidate":
        return "evaluate_exact_hyphen_surface_matching"
    if structural in {
        "sense_numbered_unsafe_to_collapse",
        "sense_or_usage_annotated_unsafe_to_collapse",
        "variant_or_compound_needs_semantic_review",
    }:
        return "preserve_distinction_manual_semantic_review"
    return "tokenizer_review_before_matching_change"


def resolve(gaps_path: Path) -> list[dict[str, str]]:
    rows = load_embedded_rows()
    gap_ids = load_gap_ids(gaps_path)
    missing = [entry_id for entry_id in gap_ids if entry_id not in rows]
    if missing:
        raise RuntimeError(f"Gap IDs not present in embedded dictionary: {missing[:5]}")
    result = []
    for entry_id in gap_ids:
        row = rows[entry_id]
        structural = structural_class(row["source"])
        result.append({
            "entryId": entry_id,
            "level": row["level"],
            "source": row["source"],
            "target": row["target"],
            "structural_class": structural,
            "next_matching_action": matching_action(structural),
        })
    return result


def write_tsv(records: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["entryId", "level", "source", "target", "structural_class", "next_matching_action"],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(records)


def self_test() -> None:
    rows = load_embedded_rows()
    if len(rows) != 3308:
        raise RuntimeError(f"Expected 3308 embedded Oxford entries, found {len(rows)}")
    records = resolve(DEFAULT_GAPS)
    if len(records) != 188:
        raise RuntimeError(f"Expected 188 coverage gaps, resolved {len(records)}")
    if records[0]["entryId"] != "oxford-a1-0001":
        raise RuntimeError("Unexpected first resolved gap")

    counts: dict[str, int] = {}
    for record in records:
        counts[record["structural_class"]] = counts.get(record["structural_class"], 0) + 1
    if counts.get("single_surface_indexable") != 114:
        raise RuntimeError(f"Expected 114 ordinary single surfaces, got {counts.get('single_surface_indexable', 0)}")
    if counts.get("sense_numbered_unsafe_to_collapse") != 36:
        raise RuntimeError(f"Expected 36 numbered/sense-marker records, got {counts.get('sense_numbered_unsafe_to_collapse', 0)}")
    if counts.get("hyphenated_exact_surface_candidate") != 3:
        raise RuntimeError(f"Expected 3 hyphenated candidates, got {counts.get('hyphenated_exact_surface_candidate', 0)}")
    structurally_non_single = len(records) - counts["single_surface_indexable"]
    if structurally_non_single != 74:
        raise RuntimeError(f"Expected 74 structurally non-single gaps, got {structurally_non_single}")
    if any(not r["next_matching_action"] for r in records):
        raise RuntimeError("Every gap must have an explicit next matching action")

    print(f"Sentence coverage gap resolver self-test passed: {len(rows)} dictionary entries, {len(records)} gaps resolved.")
    for key in sorted(counts):
        print(f"{key}: {counts[key]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gaps", type=Path, default=DEFAULT_GAPS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    records = resolve(args.gaps)
    if args.output:
        write_tsv(records, args.output)
    counts: dict[str, int] = {}
    for record in records:
        counts[record["structural_class"]] = counts.get(record["structural_class"], 0) + 1
    print(f"Resolved {len(records)} coverage gaps.")
    for key in sorted(counts):
        print(f"{key}: {counts[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
