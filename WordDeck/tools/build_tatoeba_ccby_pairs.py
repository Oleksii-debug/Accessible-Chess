#!/usr/bin/env python3
"""Build attributed English/Ukrainian Tatoeba pairs under CC BY 2.0 FR.

Development-time only. Uses official per-language detailed sentence exports so
both text sides retain the Tatoeba owner username required for practical
attribution. Pairs without a usable username on either side are skipped rather
than silently weakening attribution. Runtime WordDeck remains offline .NET.
"""
from __future__ import annotations

import argparse
import bz2
import hashlib
import json
import tempfile
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, Iterator, Tuple

OFFICIAL_URLS = {
    "english_detailed": "https://downloads.tatoeba.org/exports/per_language/eng/eng_sentences_detailed.tsv.bz2",
    "ukrainian_detailed": "https://downloads.tatoeba.org/exports/per_language/ukr/ukr_sentences_detailed.tsv.bz2",
    "links": "https://downloads.tatoeba.org/exports/per_language/eng/eng-ukr_links.tsv.bz2",
}
LICENSE = "CC BY 2.0 FR"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _open_text(path: Path):
    if path.suffix.lower() == ".bz2":
        return bz2.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def _usable_author(value: str) -> bool:
    value = value.strip()
    return bool(value) and value not in {"\\N", "-", "?"}


def load_detailed_sentences(path: Path, expected_lang: str) -> Tuple[Dict[int, Tuple[str, str]], int]:
    result: Dict[int, Tuple[str, str]] = {}
    skipped_no_author = 0
    with _open_text(path) as fh:
        for line_no, raw in enumerate(fh, 1):
            raw = raw.rstrip("\r\n")
            if not raw:
                continue
            columns = raw.split("\t")
            if len(columns) < 4:
                raise ValueError(f"{path}: line {line_no} has fewer than 4 detailed-sentence columns")
            try:
                sentence_id = int(columns[0])
            except ValueError as exc:
                raise ValueError(f"{path}: line {line_no} has invalid sentence id") from exc
            lang = columns[1].strip().lower()
            if lang != expected_lang:
                raise ValueError(f"{path}: line {line_no} language is {lang!r}, expected {expected_lang!r}")
            text = columns[2].strip()
            author = columns[3].strip()
            if sentence_id <= 0 or not text:
                raise ValueError(f"{path}: line {line_no} has blank/invalid sentence data")
            if "\t" in text or "\n" in text:
                raise ValueError(f"{path}: line {line_no} contains unsafe text")
            if not _usable_author(author):
                skipped_no_author += 1
                continue
            previous = result.get(sentence_id)
            value = (text, author)
            if previous is not None and previous != value:
                raise ValueError(f"{path}: sentence id {sentence_id} has conflicting detailed data")
            result[sentence_id] = value
    return result, skipped_no_author


def iter_link_ids(path: Path) -> Iterator[Tuple[int, int]]:
    with _open_text(path) as fh:
        for line_no, raw in enumerate(fh, 1):
            raw = raw.rstrip("\r\n")
            if not raw:
                continue
            columns = raw.split("\t")
            if len(columns) != 2:
                raise ValueError(f"{path}: line {line_no} has {len(columns)} columns; expected 2")
            try:
                en_id = int(columns[0])
                uk_id = int(columns[1])
            except ValueError as exc:
                raise ValueError(f"{path}: line {line_no} has invalid linked sentence id") from exc
            if en_id <= 0 or uk_id <= 0:
                raise ValueError(f"{path}: line {line_no} has non-positive linked sentence id")
            yield en_id, uk_id


def build_pairs(
    english: Dict[int, Tuple[str, str]],
    ukrainian: Dict[int, Tuple[str, str]],
    links: Iterable[Tuple[int, int]],
    output: Path,
    english_skipped_no_author: int,
    ukrainian_skipped_no_author: int,
) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    emitted = 0
    skipped_missing_or_unattributed = 0
    with output.open("w", encoding="utf-8", newline="\n") as out:
        out.write("english_id\tenglish_lang\tenglish\tenglish_author\tukrainian_id\tukrainian_lang\tukrainian\tukrainian_author\n")
        for en_id, uk_id in links:
            key = (en_id, uk_id)
            if key in seen:
                continue
            seen.add(key)
            en = english.get(en_id)
            uk = ukrainian.get(uk_id)
            if en is None or uk is None:
                skipped_missing_or_unattributed += 1
                continue
            en_text, en_author = en
            uk_text, uk_author = uk
            values = (en_text, en_author, uk_text, uk_author)
            if any("\t" in value or "\n" in value or "\r" in value for value in values):
                raise ValueError(f"sentence pair {en_id}/{uk_id} contains an unsafe TSV character")
            out.write(f"{en_id}\teng\t{en_text}\t{en_author}\t{uk_id}\tukr\t{uk_text}\t{uk_author}\n")
            emitted += 1
    return {
        "english_attributed_sentences": len(english),
        "ukrainian_attributed_sentences": len(ukrainian),
        "english_sentences_skipped_no_author": english_skipped_no_author,
        "ukrainian_sentences_skipped_no_author": ukrainian_skipped_no_author,
        "unique_links_seen": len(seen),
        "pairs_emitted": emitted,
        "links_skipped_missing_or_unattributed_side": skipped_missing_or_unattributed,
    }


def download_exports(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    result = {}
    for key, url in OFFICIAL_URLS.items():
        destination = directory / url.rsplit("/", 1)[-1]
        request = urllib.request.Request(url, headers={"User-Agent": "WordDeck-development/1.0"})
        with urllib.request.urlopen(request, timeout=180) as response, destination.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        result[key] = destination
    return result


def write_manifest(path: Path, inputs: dict[str, Path], output: Path, stats: dict) -> None:
    manifest = {
        "schema_version": 1,
        "source": "Tatoeba official weekly detailed sentence exports plus EN-UA links",
        "license_filter": "CC BY 2.0 FR with BOTH sentence-owner usernames retained",
        "license": LICENSE,
        "attribution_policy": "Every emitted pair has a nonblank Tatoeba username for both the English and Ukrainian sentence; upstream sentence IDs are retained.",
        "official_urls": OFFICIAL_URLS,
        "input_sha256": {key: _sha256(value) for key, value in inputs.items()},
        "output": output.name,
        "output_sha256": _sha256(output),
        "stats": stats,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="worddeck-tatoeba-ccby-") as temp:
        root = Path(temp)
        eng = root / "eng.tsv.bz2"
        ukr = root / "ukr.tsv.bz2"
        links = root / "links.tsv.bz2"
        output = root / "pairs.tsv"
        with bz2.open(eng, "wt", encoding="utf-8") as fh:
            fh.write("1\teng\tHello world.\tAlice\t2026-01-01\t2026-01-02\n")
            fh.write("2\teng\tNo owner.\t\\N\t2026-01-01\t2026-01-02\n")
        with bz2.open(ukr, "wt", encoding="utf-8") as fh:
            fh.write("10\tukr\tПривіт, світе.\tOlena\t2026-01-01\t2026-01-02\n")
            fh.write("11\tukr\tБез автора.\t\t2026-01-01\t2026-01-02\n")
        with bz2.open(links, "wt", encoding="utf-8") as fh:
            fh.write("1\t10\n2\t10\n1\t11\n")
        en_map, en_skipped = load_detailed_sentences(eng, "eng")
        uk_map, uk_skipped = load_detailed_sentences(ukr, "ukr")
        stats = build_pairs(en_map, uk_map, iter_link_ids(links), output, en_skipped, uk_skipped)
        lines = output.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2, lines
        assert lines[1] == "1\teng\tHello world.\tAlice\t10\tukr\tПривіт, світе.\tOlena"
        assert stats["pairs_emitted"] == 1
        assert stats["english_sentences_skipped_no_author"] == 1
        assert stats["ukrainian_sentences_skipped_no_author"] == 1
        manifest = output.with_suffix(output.suffix + ".manifest.json")
        write_manifest(manifest, {"english_detailed": eng, "ukrainian_detailed": ukr, "links": links}, output, stats)
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert data["license"] == LICENSE
        assert "usernames retained" in data["license_filter"]
    print("Tatoeba attributed CC-BY pair-builder self-test passed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--english-detailed", type=Path)
    parser.add_argument("--ukrainian-detailed", type=Path)
    parser.add_argument("--links", type=Path)
    parser.add_argument("--download-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    if args.download_dir:
        inputs = download_exports(args.download_dir)
    else:
        if not (args.english_detailed and args.ukrainian_detailed and args.links):
            parser.error("provide --download-dir, or all of --english-detailed/--ukrainian-detailed/--links")
        inputs = {
            "english_detailed": args.english_detailed,
            "ukrainian_detailed": args.ukrainian_detailed,
            "links": args.links,
        }
    if args.output is None:
        parser.error("--output is required")

    english, en_skipped = load_detailed_sentences(inputs["english_detailed"], "eng")
    ukrainian, uk_skipped = load_detailed_sentences(inputs["ukrainian_detailed"], "ukr")
    stats = build_pairs(english, ukrainian, iter_link_ids(inputs["links"]), args.output, en_skipped, uk_skipped)
    manifest_path = args.manifest or args.output.with_suffix(args.output.suffix + ".manifest.json")
    write_manifest(manifest_path, inputs, args.output, stats)
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    print(f"Wrote {args.output} and {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
