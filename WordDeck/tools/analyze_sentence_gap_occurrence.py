#!/usr/bin/env python3
"""Measure exact corpus occurrence for unresolved Oxford SentencePack gaps.

Development/QA utility only. This deliberately does NOT lemmatize, stem, or guess
inflections. It answers the narrower evidence question first: does the exact
Oxford surface (or a structurally safe exact phrase/hyphen form) occur in the
attributed Tatoeba English side at all? Runtime WordDeck remains offline .NET.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
from pathlib import Path

WORD_TOKEN_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
ANALYZABLE_CLASSES = {
    "single_surface_indexable",
    "plain_multiword_exact_phrase_candidate",
    "hyphenated_exact_surface_candidate",
}


def normalize_token(value: str) -> str:
    return value.replace("’", "'").casefold()


def word_tokens(text: str) -> list[str]:
    return [normalize_token(match.group(0)) for match in WORD_TOKEN_RE.finditer(text)]


def load_resolved(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"entryId", "level", "source", "target", "structural_class", "next_matching_action"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise RuntimeError(f"Unexpected resolved-gap header: {reader.fieldnames}")
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    if not rows:
        raise RuntimeError("Resolved-gap input is empty")
    ids = [row["entryId"] for row in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Resolved-gap input contains duplicate entry IDs")
    return rows


def iter_pairs(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"english_id", "english", "ukrainian_id", "ukrainian"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise RuntimeError(f"Unexpected Tatoeba pair header: {reader.fieldnames}")
        for line_no, row in enumerate(reader, 2):
            english = (row.get("english") or "").strip()
            if not english:
                raise RuntimeError(f"Blank English sentence at line {line_no}")
            yield {
                "english_id": (row.get("english_id") or "").strip(),
                "english": english,
                "ukrainian_id": (row.get("ukrainian_id") or "").strip(),
                "ukrainian": (row.get("ukrainian") or "").strip(),
            }


def contiguous_contains(haystack: list[str], needle: list[str]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    width = len(needle)
    return any(haystack[index:index + width] == needle for index in range(len(haystack) - width + 1))


def exact_hyphen_surface_occurs(sentence: str, source: str) -> bool:
    """Case-insensitive exact hyphenated surface with conservative word boundaries."""
    sentence_norm = sentence.replace("’", "'").casefold()
    source_norm = source.replace("’", "'").casefold()
    start = 0
    while True:
        index = sentence_norm.find(source_norm, start)
        if index < 0:
            return False
        end = index + len(source_norm)
        left_ok = index == 0 or not sentence_norm[index - 1].isalnum()
        right_ok = end == len(sentence_norm) or not sentence_norm[end].isalnum()
        if left_ok and right_ok:
            return True
        start = index + 1


def matches_sentence(row: dict[str, str], sentence: str, sentence_tokens: list[str]) -> bool:
    structural = row["structural_class"]
    source = row["source"]
    if structural == "single_surface_indexable":
        needle = normalize_token(source)
        return needle in sentence_tokens
    if structural == "plain_multiword_exact_phrase_candidate":
        return contiguous_contains(sentence_tokens, word_tokens(source))
    if structural == "hyphenated_exact_surface_candidate":
        return exact_hyphen_surface_occurs(sentence, source)
    return False


def analyze(resolved_rows: list[dict[str, str]], pairs_path: Path) -> list[dict[str, str]]:
    analyzable = [row for row in resolved_rows if row["structural_class"] in ANALYZABLE_CLASSES]
    counts = {row["entryId"]: 0 for row in analyzable}
    examples: dict[str, list[str]] = {row["entryId"]: [] for row in analyzable}

    for pair in iter_pairs(pairs_path):
        sentence = pair["english"]
        tokens = word_tokens(sentence)
        for row in analyzable:
            entry_id = row["entryId"]
            if matches_sentence(row, sentence, tokens):
                counts[entry_id] += 1
                if len(examples[entry_id]) < 3:
                    examples[entry_id].append(pair["english_id"])

    result: list[dict[str, str]] = []
    for row in resolved_rows:
        structural = row["structural_class"]
        match_count = counts.get(row["entryId"])
        if structural not in ANALYZABLE_CLASSES:
            evidence = "not_measured_semantic_or_tokenizer_review_required"
        elif match_count and match_count > 0:
            evidence = "exact_surface_present_in_corpus"
        else:
            evidence = "exact_surface_absent_from_corpus"
        result.append({
            **row,
            "exact_sentence_match_count": "" if match_count is None else str(match_count),
            "example_english_sentence_ids": "" if match_count is None else ",".join(examples[row["entryId"]]),
            "exact_occurrence_evidence": evidence,
        })
    return result


def write_tsv(records: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "entryId", "level", "source", "target", "structural_class", "next_matching_action",
        "exact_sentence_match_count", "example_english_sentence_ids", "exact_occurrence_evidence",
    ]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(records)


def self_test() -> None:
    resolved_text = """entryId\tlevel\tsource\ttarget\tstructural_class\tnext_matching_action\noxford-a1-0001\tA1\tapple\tяблуко\tsingle_surface_indexable\tmeasure\noxford-a1-0002\tA1\ttake care\tдбати\tplain_multiword_exact_phrase_candidate\tevaluate\noxford-a1-0003\tA1\tpart-time\tнеповний день\thyphenated_exact_surface_candidate\tevaluate\noxford-a1-0004\tA1\twind¹\tвітер\tsense_numbered_unsafe_to_collapse\treview\n"""
    pairs_text = """english_id\tenglish_lang\tenglish\tenglish_author\tukrainian_id\tukrainian_lang\tukrainian\tukrainian_author\n1\teng\tI ate an apple.\ta\t11\tukr\tЯ з'їв яблуко.\tu\n2\teng\tPlease take care of this.\ta\t12\tukr\tПодбай про це.\tu\n3\teng\tIt is a part-time job.\ta\t13\tukr\tЦе робота на неповний день.\tu\n4\teng\tPineapple is different.\ta\t14\tukr\tАнанас інший.\tu\n"""
    reader = csv.DictReader(io.StringIO(resolved_text), delimiter="\t")
    resolved = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        pairs = Path(directory) / "pairs.tsv"
        pairs.write_text(pairs_text, encoding="utf-8")
        result = analyze(resolved, pairs)
    by_id = {row["entryId"]: row for row in result}
    if by_id["oxford-a1-0001"]["exact_sentence_match_count"] != "1":
        raise RuntimeError("Single-token boundary matching self-test failed")
    if by_id["oxford-a1-0002"]["exact_sentence_match_count"] != "1":
        raise RuntimeError("Exact multiword matching self-test failed")
    if by_id["oxford-a1-0003"]["exact_sentence_match_count"] != "1":
        raise RuntimeError("Exact hyphenated matching self-test failed")
    if by_id["oxford-a1-0004"]["exact_sentence_match_count"] != "":
        raise RuntimeError("Sense-annotated record must not be automatically matched")
    print("Sentence gap exact-occurrence analyzer self-test passed.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolved", type=Path)
    parser.add_argument("--pairs", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.resolved or not args.pairs or not args.output:
        parser.error("--resolved, --pairs and --output are required unless --self-test is used")
    records = analyze(load_resolved(args.resolved), args.pairs)
    write_tsv(records, args.output)
    measured = [row for row in records if row["exact_sentence_match_count"] != ""]
    present = [row for row in measured if int(row["exact_sentence_match_count"]) > 0]
    absent = [row for row in measured if int(row["exact_sentence_match_count"]) == 0]
    print(f"Analyzed {len(records)} gaps; exact matching measured for {len(measured)} safe candidates.")
    print(f"Exact surface present: {len(present)}; exact surface absent: {len(absent)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
