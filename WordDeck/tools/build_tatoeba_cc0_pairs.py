#!/usr/bin/env python3
"""Build a provably-CC0 English/Ukrainian Tatoeba pair TSV for WordDeck.

Development-time tool only. Runtime WordDeck remains offline/self-contained .NET.
It intersects official English and Ukrainian CC0 sentence exports with official
English/Ukrainian translation links, so both text sides are independently
proven to be members of Tatoeba's CC0 subset before a pair is emitted.
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
    "english_cc0": "https://downloads.tatoeba.org/exports/per_language/eng/eng_sentences_CC0.tsv.bz2",
    "ukrainian_cc0": "https://downloads.tatoeba.org/exports/per_language/ukr/ukr_sentences_CC0.tsv.bz2",
    "links": "https://downloads.tatoeba.org/exports/per_language/eng/eng-ukr_links.tsv.bz2",
}


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


def load_cc0_sentences(path: Path, expected_lang: str) -> Dict[int, str]:
    result: Dict[int, str] = {}
    with _open_text(path) as fh:
        for line_no, raw in enumerate(fh, 1):
            raw = raw.rstrip("\r\n")
            if not raw:
                continue
            columns = raw.split("\t")
            if len(columns) < 3:
                raise ValueError(f"{path}: line {line_no} has fewer than 3 columns")
            try:
                sentence_id = int(columns[0])
            except ValueError as exc:
                raise ValueError(f"{path}: line {line_no} has invalid sentence id") from exc
            lang = columns[1].strip().lower()
            if lang != expected_lang:
                raise ValueError(
                    f"{path}: line {line_no} language is {lang!r}, expected {expected_lang!r}"
                )
            text = columns[2].strip()
            if sentence_id <= 0 or not text:
                raise ValueError(f"{path}: line {line_no} has blank/invalid sentence data")
            if "\t" in text:
                raise ValueError(f"{path}: line {line_no} contains an embedded TAB")
            previous = result.get(sentence_id)
            if previous is not None and previous != text:
                raise ValueError(f"{path}: sentence id {sentence_id} has conflicting text")
            result[sentence_id] = text
    return result


def iter_link_ids(path: Path) -> Iterator[Tuple[int, int]]:
    """Read Tatoeba per-language links.

    Current exports are ID links, but accepting 4/6-column pair variants keeps
    this development tool compatible with Tatoeba custom/pair exports without
    trusting their embedded text. Text is always rejoined from the CC0 maps.
    """
    with _open_text(path) as fh:
        for line_no, raw in enumerate(fh, 1):
            raw = raw.rstrip("\r\n")
            if not raw:
                continue
            columns = raw.split("\t")
            if len(columns) == 2:
                en_raw, uk_raw = columns[0], columns[1]
            elif len(columns) == 4:
                en_raw, uk_raw = columns[0], columns[2]
            elif len(columns) == 6:
                en_raw, uk_raw = columns[0], columns[3]
            else:
                raise ValueError(
                    f"{path}: line {line_no} has {len(columns)} columns; expected 2, 4, or 6"
                )
            try:
                en_id = int(en_raw)
                uk_id = int(uk_raw)
            except ValueError as exc:
                raise ValueError(f"{path}: line {line_no} has invalid linked sentence id") from exc
            if en_id <= 0 or uk_id <= 0:
                raise ValueError(f"{path}: line {line_no} has non-positive linked sentence id")
            yield en_id, uk_id


def build_pairs(english: Dict[int, str], ukrainian: Dict[int, str], links: Iterable[Tuple[int, int]], output: Path) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    emitted = 0
    skipped_non_cc0 = 0
    with output.open("w", encoding="utf-8", newline="\n") as out:
        out.write("english_id\tenglish_lang\tenglish\tukrainian_id\tukrainian_lang\tukrainian\n")
        for en_id, uk_id in links:
            key = (en_id, uk_id)
            if key in seen:
                continue
            seen.add(key)
            en = english.get(en_id)
            uk = ukrainian.get(uk_id)
            if en is None or uk is None:
                skipped_non_cc0 += 1
                continue
            if "\t" in en or "\t" in uk or "\n" in en or "\n" in uk:
                raise ValueError(f"sentence pair {en_id}/{uk_id} contains an unsafe TSV newline/TAB")
            out.write(f"{en_id}\teng\t{en}\t{uk_id}\tukr\t{uk}\n")
            emitted += 1
    return {
        "english_cc0_sentences": len(english),
        "ukrainian_cc0_sentences": len(ukrainian),
        "unique_links_seen": len(seen),
        "pairs_emitted": emitted,
        "links_skipped_because_one_or_both_sides_not_cc0": skipped_non_cc0,
    }


def download_exports(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    result = {}
    for key, url in OFFICIAL_URLS.items():
        name = url.rsplit("/", 1)[-1]
        destination = directory / name
        request = urllib.request.Request(url, headers={"User-Agent": "WordDeck-development/1.0"})
        with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as out:
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
        "source": "Tatoeba official weekly exports",
        "license_filter": "CC0 1.0 on BOTH sentence sides",
        "official_urls": OFFICIAL_URLS,
        "input_sha256": {key: _sha256(value) for key, value in inputs.items()},
        "output": output.name,
        "output_sha256": _sha256(output),
        "stats": stats,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="worddeck-tatoeba-cc0-") as temp:
        root = Path(temp)
        eng = root / "eng.tsv.bz2"
        ukr = root / "ukr.tsv.bz2"
        links = root / "links.tsv.bz2"
        output = root / "pairs.tsv"
        with bz2.open(eng, "wt", encoding="utf-8") as fh:
            fh.write("1\teng\tHello world.\t2026-01-01\n2\teng\tNot linked.\t2026-01-01\n")
        with bz2.open(ukr, "wt", encoding="utf-8") as fh:
            fh.write("10\tukr\tПривіт, світе.\t2026-01-01\n11\tukr\tІнше.\t2026-01-01\n")
        with bz2.open(links, "wt", encoding="utf-8") as fh:
            fh.write("1\t10\n1\t10\n2\t999\n999\t11\n")
        en_map = load_cc0_sentences(eng, "eng")
        uk_map = load_cc0_sentences(ukr, "ukr")
        stats = build_pairs(en_map, uk_map, iter_link_ids(links), output)
        lines = output.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2, lines
        assert lines[1] == "1\teng\tHello world.\t10\tukr\tПривіт, світе."
        assert stats["pairs_emitted"] == 1
        assert stats["unique_links_seen"] == 3
        assert stats["links_skipped_because_one_or_both_sides_not_cc0"] == 2
        manifest = root / "manifest.json"
        write_manifest(manifest, {"english_cc0": eng, "ukrainian_cc0": ukr, "links": links}, output, stats)
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert data["license_filter"] == "CC0 1.0 on BOTH sentence sides"
        assert data["stats"]["pairs_emitted"] == 1
    print("Tatoeba CC0 pair-builder self-test passed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--english-cc0", type=Path)
    parser.add_argument("--ukrainian-cc0", type=Path)
    parser.add_argument("--links", type=Path)
    parser.add_argument("--download-dir", type=Path, help="Download current official weekly exports into this directory.")
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
        if not (args.english_cc0 and args.ukrainian_cc0 and args.links):
            parser.error("provide --download-dir, or all of --english-cc0/--ukrainian-cc0/--links")
        inputs = {
            "english_cc0": args.english_cc0,
            "ukrainian_cc0": args.ukrainian_cc0,
            "links": args.links,
        }
    if args.output is None:
        parser.error("--output is required")

    english = load_cc0_sentences(inputs["english_cc0"], "eng")
    ukrainian = load_cc0_sentences(inputs["ukrainian_cc0"], "ukr")
    stats = build_pairs(english, ukrainian, iter_link_ids(inputs["links"]), args.output)
    manifest_path = args.manifest or args.output.with_suffix(args.output.suffix + ".manifest.json")
    write_manifest(manifest_path, inputs, args.output, stats)
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    print(f"Wrote {args.output} and {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
