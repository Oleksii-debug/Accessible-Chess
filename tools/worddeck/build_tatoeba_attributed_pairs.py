#!/usr/bin/env python3
"""Build an EN-UA Tatoeba pair TSV from official detailed exports with per-side owner attribution retained."""

from __future__ import annotations

import argparse
import bz2
import hashlib
import json
from pathlib import Path
import urllib.request

SOURCES = {
    "english_detailed": "https://downloads.tatoeba.org/exports/per_language/eng/eng_sentences_detailed.tsv.bz2",
    "ukrainian_detailed": "https://downloads.tatoeba.org/exports/per_language/ukr/ukr_sentences_detailed.tsv.bz2",
    "english_ukrainian_links": "https://downloads.tatoeba.org/exports/per_language/eng/eng-ukr_links.tsv.bz2",
}
MAX_BYTES = {
    "english_detailed": 96 * 1024 * 1024,
    "ukrainian_detailed": 48 * 1024 * 1024,
    "english_ukrainian_links": 32 * 1024 * 1024,
}
LICENSE_FILTER = "CC BY 2.0 FR with BOTH sentence-owner usernames retained"
LICENSE = "CC BY 2.0 FR"


def download_bounded(url: str, destination: Path, maximum: int) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": "WordDeck-SentencePack-Builder/1.0"})
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
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


def load_link_pairs(path: Path) -> list[tuple[int, int]]:
    pairs: set[tuple[int, int]] = set()
    with bz2.open(path, "rt", encoding="utf-8", errors="strict", newline="") as source:
        for line_number, raw in enumerate(source, 1):
            if not raw.strip():
                continue
            columns = raw.rstrip("\r\n").split("\t")
            left, right = parse_link_ids(columns, line_number)
            pairs.add((left, right))
    if not pairs:
        raise RuntimeError("Official EN-UA links export produced no pairs.")
    return sorted(pairs)


def normalize_author(raw: str) -> str | None:
    value = raw.strip()
    if not value or value in {"\\N", "-", "?"}:
        return None
    if "\t" in value or "\r" in value or "\n" in value:
        return None
    return value


def load_detailed(path: Path, expected_lang: str, needed_ids: set[int]) -> dict[int, tuple[str, str]]:
    result: dict[int, tuple[str, str]] = {}
    with bz2.open(path, "rt", encoding="utf-8", errors="strict", newline="") as source:
        for line_number, raw in enumerate(source, 1):
            columns = raw.rstrip("\r\n").split("\t")
            if len(columns) < 4:
                raise RuntimeError(f"Malformed detailed sentence row {line_number} in {path.name}")
            try:
                sentence_id = int(columns[0])
            except ValueError as exc:
                raise RuntimeError(f"Invalid sentence id at row {line_number} in {path.name}") from exc
            if sentence_id not in needed_ids:
                continue
            language = columns[1].strip().lower()
            text = columns[2].strip()
            author = normalize_author(columns[3])
            if language != expected_lang:
                raise RuntimeError(f"Unexpected language {language!r} at row {line_number} in {path.name}")
            if sentence_id <= 0 or not text or "\t" in text or "\r" in text or "\n" in text or author is None:
                continue
            previous = result.get(sentence_id)
            value = (text, author)
            if previous is not None and previous != value:
                raise RuntimeError(f"Duplicate detailed sentence id with conflicting content: {sentence_id}")
            result[sentence_id] = value
    return result


def orient_pairs(raw_pairs: list[tuple[int, int]], english: dict[int, tuple[str, str]], ukrainian: dict[int, tuple[str, str]]) -> list[tuple[int, str, str, int, str, str]]:
    pairs: set[tuple[int, int]] = set()
    for left, right in raw_pairs:
        if left in english and right in ukrainian:
            pairs.add((left, right))
        elif right in english and left in ukrainian:
            pairs.add((right, left))

    ordered: list[tuple[int, str, str, int, str, str]] = []
    for en_id, uk_id in sorted(pairs):
        en_text, en_author = english[en_id]
        uk_text, uk_author = ukrainian[uk_id]
        ordered.append((en_id, en_text, en_author, uk_id, uk_text, uk_author))
    if not ordered:
        raise RuntimeError("No EN-UA links survived nonblank per-side author filtering.")
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

    raw_pairs = load_link_pairs(local_paths["english_ukrainian_links"])
    left_ids = {left for left, _ in raw_pairs}
    right_ids = {right for _, right in raw_pairs}
    all_ids = left_ids | right_ids

    english = load_detailed(local_paths["english_detailed"], "eng", all_ids)
    ukrainian = load_detailed(local_paths["ukrainian_detailed"], "ukr", all_ids)
    pairs = orient_pairs(raw_pairs, english, ukrainian)

    pair_path = output_dir / "tatoeba-en-uk-attributed.tsv"
    with pair_path.open("w", encoding="utf-8", newline="\n") as output:
        output.write("english_id\tenglish_lang\tenglish\tenglish_author\tukrainian_id\tukrainian_lang\tukrainian\tukrainian_author\n")
        for en_id, en_text, en_author, uk_id, uk_text, uk_author in pairs:
            output.write(f"{en_id}\teng\t{en_text}\t{en_author}\t{uk_id}\tukr\t{uk_text}\t{uk_author}\n")

    output_sha = sha256_file(pair_path)
    manifest = {
        "schema_version": 1,
        "license_filter": LICENSE_FILTER,
        "license": LICENSE,
        "output_sha256": output_sha,
        "pair_count": len(pairs),
        "raw_link_pair_count": len(raw_pairs),
        "english_linked_sentences_with_owner": len(english),
        "ukrainian_linked_sentences_with_owner": len(ukrainian),
        "sources": evidence,
        "selection_rule": "Use an official EN-UA link only when both referenced detailed sentence rows are present, language-correct, and retain a nonblank Tatoeba owner username. Emit each owner beside the corresponding sentence so WordDeck can preserve record-level attribution.",
    }
    manifest_path = Path(str(pair_path) + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Official EN-UA links: {len(raw_pairs)}")
    print(f"Linked English detailed sentences with owner: {len(english)}")
    print(f"Linked Ukrainian detailed sentences with owner: {len(ukrainian)}")
    print(f"Attributed EN-UA linked pairs: {len(pairs)}")
    print(f"Pair TSV: {pair_path}")
    print(f"Pair SHA256: {output_sha}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
