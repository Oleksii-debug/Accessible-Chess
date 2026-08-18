#!/usr/bin/env python3
"""Build a deterministic WordDeck AudioPack manifest from stable-ID MP3 files.

Development/release utility only; Python never ships with WordDeck. Uses only
standard-library hashing/JSON. The builder is intentionally storage-agnostic:
validated replacement MP3s can overwrite base files by stable ID before this
final manifest is produced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

MIN_MP3_BYTES = 513


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(audio_root: Path, output: Path, dictionary_id: str) -> dict[str, object]:
    if not dictionary_id.strip():
        raise RuntimeError("dictionary_id must not be blank")
    if not audio_root.is_dir():
        raise RuntimeError(f"Audio directory does not exist: {audio_root}")

    files = sorted(audio_root.glob("*.mp3"), key=lambda p: p.stem.casefold())
    if not files:
        raise RuntimeError("AudioPack contains no MP3 files")

    seen: set[str] = set()
    records: list[dict[str, object]] = []
    for path in files:
        entry_id = path.stem.strip()
        key = entry_id.casefold()
        if not entry_id or key in seen:
            raise RuntimeError(f"Duplicate or blank stable entry ID: {entry_id!r}")
        seen.add(key)
        size = path.stat().st_size
        if size < MIN_MP3_BYTES:
            raise RuntimeError(f"Suspiciously small MP3 for {entry_id}: {size} bytes")
        records.append({
            "entry_id": entry_id,
            "file": path.name,
            "bytes": size,
            "sha256": sha256(path),
        })

    manifest = {
        "format": "worddeck-audiopack-v1",
        "dictionary_id": dictionary_id.strip(),
        "audio_format": "mp3",
        "entry_count": len(records),
        "entries": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="worddeck-audiopack-") as root_text:
        root = Path(root_text)
        audio = root / "audio"
        audio.mkdir()
        (audio / "ox-a.mp3").write_bytes(b"ID3" + b"a" * 700)
        (audio / "ox-b.mp3").write_bytes(b"ID3" + b"b" * 900)
        out = root / "manifest.json"
        manifest = build(audio, out, "synthetic-en-uk")
        if manifest["entry_count"] != 2 or [row["entry_id"] for row in manifest["entries"]] != ["ox-a", "ox-b"]:
            raise RuntimeError("AudioPack deterministic ordering/count self-test failed")
        first = out.read_bytes()
        build(audio, out, "synthetic-en-uk")
        if out.read_bytes() != first:
            raise RuntimeError("AudioPack manifest is not deterministic")
        (audio / "bad.mp3").write_bytes(b"tiny")
        try:
            build(audio, out, "synthetic-en-uk")
        except RuntimeError:
            pass
        else:
            raise RuntimeError("AudioPack builder accepted a suspiciously small MP3")
    print("AudioPack manifest builder self-test passed.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dictionary-id")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.audio_root is None or args.output is None or args.dictionary_id is None:
        parser.error("--audio-root, --output and --dictionary-id are required unless --self-test is used")
    manifest = build(args.audio_root, args.output, args.dictionary_id)
    print(f"AudioPack manifest built: {manifest['entry_count']} entries -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
