#!/usr/bin/env python3
"""Measure builder-aligned exact corpus occurrence for unresolved Oxford SentencePack gaps.

Development/QA utility only. This deliberately does NOT lemmatize, stem, or guess
inflections. It answers the narrower evidence question first: does the exact
Oxford surface (or a structurally safe exact token sequence) occur in a Tatoeba
English sentence that the production SentencePack builder could actually accept?

The production C# builder currently accepts English sentences with 2..24 normalized
tokens, normalizes straight/curly/backtick apostrophes, indexes ordinary one-token
dictionary surfaces, and indexes structurally safe multi-token dictionary sources
by contiguous normalized token sequence. This QA tool mirrors those bounded rules
so it does not classify evidence from sentences the builder would reject.

Sense-annotated or otherwise structurally unsafe records stay explicitly unresolved;
this tool never strips sense markers or collapses semantically distinct dictionary
records. Matching is indexed with Python's standard dict/set primitives only. No
NLP/morphology dependency is introduced for an exact-string evidence task.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
from collections import defaultdict
from pathlib import Path

MIN_TOKENS = 2
MAX_TOKENS = 24
WORD_TOKEN_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
ANALYZABLE_CLASSES = {
    "single_surface_indexable",
    "plain_multiword_exact_phrase_candidate",
    "hyphenated_exact_surface_candidate",
}


def normalize_apostrophes(value: str) -> str:
    return value.replace("’", "'").replace("‘", "'").replace("`", "'")


def normalize_token(value: str) -> str:
    return normalize_apostrophes(value).strip().casefold()


def word_tokens(text: str) -> list[str]:
    normalized = normalize_apostrophes(text)
    return [normalize_token(match.group(0)) for match in WORD_TOKEN_RE.finditer(normalized)]


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
            english_id = (row.get("english_id") or "").strip()
            ukrainian_id = (row.get("ukrainian_id") or "").strip()
            if not english_id or not ukrainian_id:
                raise RuntimeError(f"Missing Tatoeba sentence id at line {line_no}")
            yield {
                "english_id": english_id,
                "english": english,
                "ukrainian_id": ukrainian_id,
                "ukrainian": (row.get("ukrainian") or "").strip(),
            }


def builder_eligible_tokens(sentence: str) -> list[str] | None:
    """Mirror TatoebaSentencePackBuilder's 2..24-token sentence eligibility."""
    tokens = word_tokens(sentence)
    if len(tokens) < MIN_TOKENS or len(tokens) > MAX_TOKENS:
        return None
    return tokens


def contiguous_contains(haystack: list[str], needle: list[str]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    width = len(needle)
    return any(haystack[index:index + width] == needle for index in range(len(haystack) - width + 1))


def matches_sentence(row: dict[str, str], sentence_tokens: list[str]) -> bool:
    structural = row["structural_class"]
    source_tokens = word_tokens(row["source"])
    if structural == "single_surface_indexable":
        # Production BuildSurfaceIndex accepts only sources whose tokenizer result
        # is exactly one token equal to the normalized source.
        if len(source_tokens) != 1 or source_tokens[0] != normalize_token(row["source"]):
            return False
        return source_tokens[0] in sentence_tokens
    if structural in {"plain_multiword_exact_phrase_candidate", "hyphenated_exact_surface_candidate"}:
        # Production BuildExactSequenceIndex tokenizes safe source text, so both
        # "part-time" and "part time" resolve to the same contiguous token sequence.
        return contiguous_contains(sentence_tokens, source_tokens)
    return False


def classify_gap(structural: str, match_count: int | None) -> str:
    """Convert bounded exact evidence into an actionable QA class without guessing senses."""
    if match_count is None:
        return "structural_or_semantic_review_required"
    if structural == "single_surface_indexable":
        return (
            "exact_present_index_or_matching_defect_candidate"
            if match_count > 0
            else "exact_absent_corpus_or_inflection_candidate"
        )
    if structural in {"plain_multiword_exact_phrase_candidate", "hyphenated_exact_surface_candidate"}:
        return (
            "safe_exact_form_present_extension_candidate"
            if match_count > 0
            else "safe_exact_form_absent_corpus_or_inflection_candidate"
        )
    return "structural_or_semantic_review_required"


def build_candidate_indexes(resolved_rows: list[dict[str, str]]):
    """Build builder-aligned exact-match lookup buckets; no morphology or sense collapse."""
    single_by_token: dict[str, list[dict[str, str]]] = defaultdict(list)
    sequence_by_first_token: dict[str, list[dict[str, str]]] = defaultdict(list)

    for row in resolved_rows:
        structural = row["structural_class"]
        source_tokens = word_tokens(row["source"])
        if structural == "single_surface_indexable":
            normalized_source = normalize_token(row["source"])
            if len(source_tokens) == 1 and source_tokens[0] == normalized_source:
                single_by_token[normalized_source].append(row)
            continue
        if structural not in {
            "plain_multiword_exact_phrase_candidate",
            "hyphenated_exact_surface_candidate",
        }:
            continue
        if len(source_tokens) >= 2:
            sequence_by_first_token[source_tokens[0]].append(row)

    return dict(single_by_token), dict(sequence_by_first_token)


def analyze(resolved_rows: list[dict[str, str]], pairs_path: Path) -> list[dict[str, str]]:
    analyzable = [row for row in resolved_rows if row["structural_class"] in ANALYZABLE_CLASSES]
    counts = {row["entryId"]: 0 for row in analyzable}
    examples: dict[str, list[str]] = {row["entryId"]: [] for row in analyzable}
    single_by_token, sequence_by_first_token = build_candidate_indexes(resolved_rows)
    seen_stable_pairs: set[tuple[str, str]] = set()

    for pair in iter_pairs(pairs_path):
        stable_pair = (pair["english_id"], pair["ukrainian_id"])
        if stable_pair in seen_stable_pairs:
            # Production builder rejects duplicate stable sentence IDs. Presence
            # evidence should therefore count an accepted pair at most once.
            continue
        seen_stable_pairs.add(stable_pair)

        tokens = builder_eligible_tokens(pair["english"])
        if tokens is None:
            continue

        matched_ids: set[str] = set()

        # Sentence counts, not token counts: visit each normalized token once.
        for token in set(tokens):
            for row in single_by_token.get(token, ()):
                matched_ids.add(row["entryId"])

        # Safe phrase/hyphen candidates are sparse. Bucket by first token and
        # mirror the builder's contiguous token-sequence comparison.
        for token in set(tokens):
            for row in sequence_by_first_token.get(token, ()):
                entry_id = row["entryId"]
                if entry_id in matched_ids:
                    continue
                if matches_sentence(row, tokens):
                    matched_ids.add(entry_id)

        for entry_id in matched_ids:
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
            evidence = "builder_eligible_exact_surface_present"
        else:
            evidence = "builder_eligible_exact_surface_absent"
        result.append({
            **row,
            "exact_sentence_match_count": "" if match_count is None else str(match_count),
            "example_english_sentence_ids": "" if match_count is None else ",".join(examples[row["entryId"]]),
            "exact_occurrence_evidence": evidence,
            "coverage_gap_classification": classify_gap(structural, match_count),
        })
    return result


def write_tsv(records: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "entryId", "level", "source", "target", "structural_class", "next_matching_action",
        "exact_sentence_match_count", "example_english_sentence_ids", "exact_occurrence_evidence",
        "coverage_gap_classification",
    ]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(records)


def self_test() -> None:
    resolved_text = """entryId\tlevel\tsource\ttarget\tstructural_class\tnext_matching_action
oxford-a1-0001\tA1\tapple\tяблуко\tsingle_surface_indexable\tmeasure
oxford-a1-0002\tA1\tpear\tгруша\tsingle_surface_indexable\tmeasure
oxford-a1-0003\tA1\ttake care\tдбати\tplain_multiword_exact_phrase_candidate\tevaluate
oxford-a1-0004\tA1\tpart-time\tнеповний день\thyphenated_exact_surface_candidate\tevaluate
oxford-a1-0005\tA1\twind¹\tвітер\tsense_numbered_unsafe_to_collapse\treview
oxford-a1-0006\tA1\tdon't\tне робити\tsingle_surface_indexable\tmeasure
"""
    # Pair 1 repeats apple twice but must count one sentence.
    # Pair 4 is one token and is rejected by the production builder.
    # Pair 5 exceeds 24 tokens and is rejected by the production builder.
    # Pair 6 duplicates pair 1's stable EN/UA IDs and must not double count.
    # Pair 7 proves builder-style token-sequence equivalence for part-time/part time.
    long_sentence = " ".join(["pear"] + [f"word{i}" for i in range(1, 25)])
    pairs_text = f"""english_id\tenglish_lang\tenglish\tenglish_author\tukrainian_id\tukrainian_lang\tukrainian\tukrainian_author
1\teng\tI ate an apple, apple.\ta\t11\tukr\tЯ з'їв яблуко.\tu
2\teng\tPlease take care of this.\ta\t12\tukr\tПодбай про це.\tu
3\teng\tIt is a part-time job.\ta\t13\tukr\tЦе робота на неповний день.\tu
4\teng\tpear\ta\t14\tukr\tгруша\tu
5\teng\t{long_sentence}\ta\t15\tukr\tдовге речення\tu
1\teng\tI ate an apple.\ta\t11\tukr\tЯ з'їв яблуко.\tu
7\teng\tThis is a part time role.\ta\t17\tukr\tЦе робота на неповний день.\tu
8\teng\tI don‘t know.\ta\t18\tukr\tЯ не знаю.\tu
"""
    reader = csv.DictReader(io.StringIO(resolved_text), delimiter="\t")
    resolved = [{key: (value or "").strip() for key, value in row.items()} for row in reader]

    single_index, sequence_index = build_candidate_indexes(resolved)
    if [row["entryId"] for row in single_index.get("apple", [])] != ["oxford-a1-0001"]:
        raise RuntimeError("Single-token candidate index self-test failed")
    if {row["entryId"] for row in sequence_index.get("take", [])} != {"oxford-a1-0003"}:
        raise RuntimeError("Phrase first-token candidate index self-test failed")
    if {row["entryId"] for row in sequence_index.get("part", [])} != {"oxford-a1-0004"}:
        raise RuntimeError("Hyphen first-token candidate index self-test failed")
    if any(row["entryId"] == "oxford-a1-0005" for rows in sequence_index.values() for row in rows):
        raise RuntimeError("Sense-annotated record leaked into exact candidate indexes")

    if builder_eligible_tokens("pear") is not None:
        raise RuntimeError("One-token builder eligibility self-test failed")
    if builder_eligible_tokens(long_sentence) is not None:
        raise RuntimeError("Overlong builder eligibility self-test failed")

    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        pairs = Path(directory) / "pairs.tsv"
        pairs.write_text(pairs_text, encoding="utf-8")
        result = analyze(resolved, pairs)
    by_id = {row["entryId"]: row for row in result}

    if by_id["oxford-a1-0001"]["exact_sentence_match_count"] != "1":
        raise RuntimeError("Single-token sentence-count/dedup matching self-test failed")
    if by_id["oxford-a1-0001"]["coverage_gap_classification"] != "exact_present_index_or_matching_defect_candidate":
        raise RuntimeError("Exact-present single-surface classification self-test failed")
    if by_id["oxford-a1-0002"]["exact_sentence_match_count"] != "0":
        raise RuntimeError("Builder-ineligible exact occurrences must not count")
    if by_id["oxford-a1-0002"]["coverage_gap_classification"] != "exact_absent_corpus_or_inflection_candidate":
        raise RuntimeError("Exact-absent single-surface classification self-test failed")
    if by_id["oxford-a1-0003"]["exact_sentence_match_count"] != "1":
        raise RuntimeError("Exact multiword matching self-test failed")
    if by_id["oxford-a1-0003"]["coverage_gap_classification"] != "safe_exact_form_present_extension_candidate":
        raise RuntimeError("Exact-present multiword classification self-test failed")
    if by_id["oxford-a1-0004"]["exact_sentence_match_count"] != "2":
        raise RuntimeError("Builder-style hyphen/space token-sequence matching self-test failed")
    if by_id["oxford-a1-0005"]["exact_sentence_match_count"] != "":
        raise RuntimeError("Sense-annotated record must not be automatically matched")
    if by_id["oxford-a1-0005"]["coverage_gap_classification"] != "structural_or_semantic_review_required":
        raise RuntimeError("Sense-annotated classification self-test failed")
    if by_id["oxford-a1-0006"]["exact_sentence_match_count"] != "1":
        raise RuntimeError("Apostrophe normalization self-test failed")
    if by_id["oxford-a1-0001"]["exact_occurrence_evidence"] != "builder_eligible_exact_surface_present":
        raise RuntimeError("Builder-aligned evidence label self-test failed")

    print("Sentence gap builder-aligned exact-occurrence analyzer self-test passed.")


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
    single_present = [
        row for row in records
        if row["coverage_gap_classification"] == "exact_present_index_or_matching_defect_candidate"
    ]
    single_absent = [
        row for row in records
        if row["coverage_gap_classification"] == "exact_absent_corpus_or_inflection_candidate"
    ]
    print(f"Analyzed {len(records)} gaps; builder-aligned exact matching measured for {len(measured)} safe candidates.")
    print(f"Builder-eligible exact surface present: {len(present)}; absent: {len(absent)}.")
    print(
        "Ordinary single-surface classification: "
        f"index/matching-defect candidates={len(single_present)}; "
        f"corpus-absence/inflection candidates={len(single_absent)}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
