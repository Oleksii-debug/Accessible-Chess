#!/usr/bin/env python3
"""Build a conservative EN-UA Tatoeba pair TSV where BOTH sentence texts are in official CC0 exports."""

from __future__ import annotations

import argparse
import bz2
import hashlib
import json
from pathlib import Path
import urllib.request

SOURCES = {
    "english_cc0": "https://downloads.tatoeba.org/exports/per_language/eng/eng_sentences_CC0.tsv.bz2",
    "ukrainian_cc0": "https://downloads.tatoeba.org/exports/per_language/ukr/ukr_sentences_CC0.tsv.bz2",
    "english_ukrainian_links": "https://downloads.tatoeba.org/exports/per_language/eng/eng-ukr_links.tsv.bz2",
}
MAX_BYTES = {
    "english_cc0": 32 * 1024 * 1024,
    "ukrainian_cc0": 16 * 1024 * 1024,
    "english_ukrainian_links": 32 * 1024 * 1024,
}
LICENSE_FILTER = "CC0 1.0 on BOTH sentence sides"


def download_bounded(url: str, destination: Path, maximum: int) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": "WordDeck-SentencePack-Builder/1.0"})
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(request, timeout=90) as response, destination.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise RuntimeError(f"Upstream export exceeded bounded download limit: {url}")
            digest.update(chunk)
            output.write(chunk)
    if total == 0:
        raise RuntimeError(f"Upstream export was empty: {url}")
    return {"url": url, "sha256": digest.hexdigest(), "bytes": total}


def load_cc0_sentences(path: Path, expected_lang: str) -> dict[int, str]:
    result: dict[int, str] = {}
    with bz2.open(path, "rt", encoding="utf-8", errors="strict", newline="") as source:
        for line_number, raw in enumerate(source, 1):
            columns = raw.rstrip("\r\n").split("\t")
            if len(columns) < 3:
                raise RuntimeError(f"Malformed CC0 sentence row {line_number} in {path.name}")
            try:
                sentence_id = int(columns[0])
            except ValueError as exc:
                raise RuntimeError(f"Invalid sentence id at row {line_number} in {path.name}") from exc
            language = columns[1].strip().lower()
            text = columns[2].strip()
            if language != expected_lang:
                raise RuntimeError(f"Unexpected language {language!r} at row {line_number} in {path.name}")
            if sentence_id <= 0 or not text or "\t" in text or "\r" in text or "\n" in text:
                raise RuntimeError(f"Unsafe sentence row {line_number} in {path.name}")
            if sentence_id in result and result[sentence_id] != text:
                raise RuntimeError(f"Duplicate CC0 sentence id with conflicting text: {sentence_id}")
            result[sentence_id] = text
    if not result:
        raise RuntimeError(f"No sentences parsed from {path.name}")
    return result


def parse_link_ids(columns: list[str], line_number: int) -> tuple[int, int]:
    candidates = ((0, 1), (0, 2), (1, 3))
    for left_index, right_index in candidates:
        if max(left_index, right_index) >= len(columns):
            continue
        try:
            left = int(columns[left_index].strip())
            right = int(columns[right_index].strip())
        except ValueError:
            continue
        if left > 0 and right > 0:
            return left, right
    raise RuntimeError(
        f"Unsupported EN-UA link row {line_number}: expected two sentence ids; got {len(columns)} columns"
    )


def build_pairs(links_path: Path, english: dict[int, str], ukrainian: dict[int, str]) -> list[tuple[int, str, int, str]]:
    pairs: set[tuple[int, int]] = set()
    inspected = 0
    with bz2.open(links_path, "rt", encoding="utf-8", errors="strict", newline="") as source:
        for line_number, raw in enumerate(source, 1):
            if not raw.strip():
                continue
            inspected += 1
            columns = raw.rstrip("\r\n").split("\t")
            left, right = parse_link_ids(columns, line_number)
            if left in english and right in ukrainian:
                pairs.add((left, right))
            elif right in english and left in ukrainian:
                pairs.add((right, left))

    ordered = [(en_id, english[en_id], uk_id, ukrainian[uk_id]) for en_id, uk_id in sorted(pairs)]
    if not ordered:
        raise RuntimeError(
            f"No links survived BOTH-sides-CC0 filtering (links inspected={inspected}, eng_cc0={len(english)}, ukr_cc0={len(ukrainian)})."
        )
    return ordered


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    source_dir = output_dir / "upstream"
    source_dir.mkdir(parents=True, exist_ok=True)

    evidence: dict[str, dict[str, object]] = {}
    local_paths: dict[str, Path] = {}
    for key, url in SOURCES.items():
        local_path = source_dir / Path(url).name
        local_paths[key] = local_path
        evidence[key] = download_bounded(url, local_path, MAX_BYTES[key])

    english = load_cc0_sentences(local_paths["english_cc0"], "eng")
    ukrainian = load_cc0_sentences(local_paths["ukrainian_cc0"], "ukr")
    pairs = build_pairs(local_paths["english_ukrainian_links"], english, ukrainian)

    pair_path = output_dir / "tatoeba-en-uk-both-cc0.tsv"
    with pair_path.open("w", encoding="utf-8", newline="\n") as output:
        output.write("english_id\tenglish\tukrainian_id\tukrainian\n")
        for en_id, en_text, uk_id, uk_text in pairs:
            output.write(f"{en_id}\t{en_text}\t{uk_id}\t{uk_text}\n")

    output_sha = sha256_file(pair_path)
    manifest = {
        "schema_version": 1,
        "license_filter": LICENSE_FILTER,
        "license": "CC0 1.0",
        "output_sha256": output_sha,
        "pair_count": len(pairs),
        "english_cc0_sentence_count": len(english),
        "ukrainian_cc0_sentence_count": len(ukrainian),
        "sources": evidence,
        "selection_rule": "Include an EN-UA linked pair only when the English sentence id is present in the official English CC0 export AND the Ukrainian sentence id is present in the official Ukrainian CC0 export.",
    }
    manifest_path = Path(str(pair_path) + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"English CC0 sentences: {len(english)}")
    print(f"Ukrainian CC0 sentences: {len(ukrainian)}")
    print(f"Both-sides-CC0 EN-UA linked pairs: {len(pairs)}")
    print(f"Pair TSV: {pair_path}")
    print(f"Pair SHA256: {output_sha}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
