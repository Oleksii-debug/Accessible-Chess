#!/usr/bin/env python3
"""Summarize WordDeck SentencePack coverage-gap QA into a durable JSON checkpoint.

Development/QA utility only. It consumes the TSV emitted by
analyze_sentence_gap_occurrence.py and performs no NLP or matching of its own.
Python standard-library only; nothing is added to the shipped WordDeck runtime.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import tempfile
from collections import Counter
from pathlib import Path

EXPECTED_TOTAL = 188
EXPECTED_SINGLE = 114


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {
            "entryId",
            "level",
            "structural_class",
            "exact_sentence_match_count",
            "coverage_gap_classification",
        }
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise RuntimeError(f"Unexpected gap-QA header: {reader.fieldnames}")
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    if not rows:
        raise RuntimeError("Gap-QA input is empty")
    ids = [row["entryId"] for row in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Gap-QA input contains duplicate entry IDs")
    return rows


def summarize(rows: list[dict[str, str]], *, enforce_production_shape: bool = True) -> dict:
    if enforce_production_shape and len(rows) != EXPECTED_TOTAL:
        raise RuntimeError(f"Expected {EXPECTED_TOTAL} gap rows, got {len(rows)}")

    structural = Counter(row["structural_class"] for row in rows)
    classification = Counter(row["coverage_gap_classification"] for row in rows)
    levels = Counter(row["level"] for row in rows)

    single = [row for row in rows if row["structural_class"] == "single_surface_indexable"]
    if enforce_production_shape and len(single) != EXPECTED_SINGLE:
        raise RuntimeError(f"Expected {EXPECTED_SINGLE} single-surface rows, got {len(single)}")

    measured = [row for row in rows if row["exact_sentence_match_count"] != ""]
    unmeasured = [row for row in rows if row["exact_sentence_match_count"] == ""]
    single_unmeasured = [row for row in single if row["exact_sentence_match_count"] == ""]
    if single_unmeasured:
        raise RuntimeError(f"{len(single_unmeasured)} single-surface rows are unexpectedly unmeasured")

    def match_count(row: dict[str, str]) -> int:
        raw = row["exact_sentence_match_count"]
        if raw == "":
            return 0
        try:
            value = int(raw)
        except ValueError as exc:
            raise RuntimeError(f"Invalid exact_sentence_match_count for {row['entryId']}: {raw!r}") from exc
        if value < 0:
            raise RuntimeError(f"Negative exact_sentence_match_count for {row['entryId']}")
        return value

    for row in measured:
        match_count(row)

    single_present = [row for row in single if match_count(row) > 0]
    single_absent = [row for row in single if match_count(row) == 0]
    safe_sequence_classes = {"plain_multiword_exact_phrase_candidate", "hyphenated_exact_surface_candidate"}
    safe_sequences = [row for row in rows if row["structural_class"] in safe_sequence_classes]
    safe_present = [row for row in safe_sequences if row["exact_sentence_match_count"] != "" and match_count(row) > 0]
    safe_absent = [row for row in safe_sequences if row["exact_sentence_match_count"] != "" and match_count(row) == 0]

    return {
        "schema_version": 1,
        "input_gap_rows": len(rows),
        "measured_rows": len(measured),
        "unmeasured_semantic_or_structural_rows": len(unmeasured),
        "structural_class_counts": dict(sorted(structural.items())),
        "coverage_gap_classification_counts": dict(sorted(classification.items())),
        "cefr_gap_counts": dict(sorted(levels.items())),
        "ordinary_single_surface": {
            "total": len(single),
            "exact_present": len(single_present),
            "exact_absent": len(single_absent),
            "present_entry_ids": [row["entryId"] for row in single_present],
            "absent_entry_ids": [row["entryId"] for row in single_absent],
        },
        "safe_exact_phrase_or_hyphen": {
            "total": len(safe_sequences),
            "exact_present": len(safe_present),
            "exact_absent": len(safe_absent),
            "present_entry_ids": [row["entryId"] for row in safe_present],
            "absent_entry_ids": [row["entryId"] for row in safe_absent],
        },
        "decision_gate": {
            "morphology_evaluation_scope": "ordinary_single_surface.exact_absent only",
            "semantic_or_sense_rows_must_remain_unmodified": True,
            "note": "Exact-present gaps indicate builder/index QA; they must not trigger lemmatization. Sense/annotation rows remain protected from blanket normalization.",
        },
    }


def write_summary(summary: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def self_test() -> None:
    text = """entryId\tlevel\tsource\ttarget\tstructural_class\tnext_matching_action\texact_sentence_match_count\texample_english_sentence_ids\texact_occurrence_evidence\tcoverage_gap_classification
oxford-a1-0001\tA1\tapple\tяблуко\tsingle_surface_indexable\tmeasure\t2\t1,2\tpresent\texact_present_index_or_matching_defect_candidate
oxford-a2-0002\tA2\tpear\tгруша\tsingle_surface_indexable\tmeasure\t0\t\tabsent\texact_absent_corpus_or_inflection_candidate
oxford-b1-0003\tB1\ttake care\tдбати\tplain_multiword_exact_phrase_candidate\tevaluate\t1\t3\tpresent\tsafe_exact_form_present_extension_candidate
oxford-b2-0004\tB2\twind¹\tвітер\tsense_numbered_unsafe_to_collapse\treview\t\t\tunmeasured\tstructural_or_semantic_review_required
"""
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    summary = summarize(rows, enforce_production_shape=False)
    assert summary["input_gap_rows"] == 4
    assert summary["ordinary_single_surface"]["total"] == 2
    assert summary["ordinary_single_surface"]["exact_present"] == 1
    assert summary["ordinary_single_surface"]["exact_absent"] == 1
    assert summary["ordinary_single_surface"]["absent_entry_ids"] == ["oxford-a2-0002"]
    assert summary["safe_exact_phrase_or_hyphen"]["exact_present"] == 1
    assert summary["unmeasured_semantic_or_structural_rows"] == 1
    assert summary["decision_gate"]["semantic_or_sense_rows_must_remain_unmodified"] is True

    with tempfile.TemporaryDirectory(prefix="worddeck-gap-summary-") as directory:
        output = Path(directory) / "summary.json"
        write_summary(summary, output)
        round_trip = json.loads(output.read_text(encoding="utf-8"))
        assert round_trip["ordinary_single_surface"]["exact_present"] == 1
    print("Sentence gap QA summary self-test passed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if args.input is None or args.output is None:
        parser.error("--input and --output are required unless --self-test is used")
    rows = load_rows(args.input)
    summary = summarize(rows)
    write_summary(summary, args.output)
    single = summary["ordinary_single_surface"]
    safe = summary["safe_exact_phrase_or_hyphen"]
    print(
        f"Gap QA summary: single present={single['exact_present']} absent={single['exact_absent']}; "
        f"safe phrase/hyphen present={safe['exact_present']} absent={safe['exact_absent']}; "
        f"unmeasured={summary['unmeasured_semantic_or_structural_rows']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
