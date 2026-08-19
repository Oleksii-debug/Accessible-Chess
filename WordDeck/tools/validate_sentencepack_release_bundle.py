#!/usr/bin/env python3
"""Fail-closed validation for a distributable SentencePack bundle.

Development/CI utility only. Uses Python standard library. It deliberately
requires the disk-backed SQLite companion so a release cannot silently regress
from the measured low-memory runtime path to eager JSON/GZIP loading.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

REQUIRED_METADATA = {
    "schema_version": "2",
    "pack_id": None,
    "source_language": "en",
    "target_language": "uk",
    "provenance": None,
    "license": None,
}


def validate(sqlite_path: Path, gzip_path: Path, manifest_path: Path, coverage_path: Path) -> dict[str, object]:
    for path in (sqlite_path, gzip_path, manifest_path, coverage_path):
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"Required SentencePack release file is missing or empty: {path}")

    # sqlite3.Connection's context manager commits/rolls back but does not close the
    # connection. Use closing() so Windows does not keep pack.sqlite locked after QA.
    with closing(sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro", uri=True)) as db:
        metadata = dict(db.execute("SELECT key, value FROM metadata"))
        for key, expected in REQUIRED_METADATA.items():
            value = metadata.get(key, "").strip()
            if not value:
                raise RuntimeError(f"SQLite metadata is missing {key}")
            if expected is not None and value != expected:
                raise RuntimeError(f"SQLite metadata {key} expected {expected!r}, got {value!r}")
        sentence_count = int(db.execute("SELECT COUNT(*) FROM sentences").fetchone()[0])
        target_count = int(db.execute("SELECT COUNT(*) FROM target_entries").fetchone()[0])
        if sentence_count <= 0 or target_count <= 0:
            raise RuntimeError("SQLite corpus is structurally empty")

    with gzip.open(gzip_path, "rb") as handle:
        prefix = handle.read(1)
        if prefix not in (b"{", b"["):
            raise RuntimeError("Compressed SentencePack does not begin with JSON after decompression")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    coverage = json.loads(coverage_path.read_text(encoding="utf-8-sig"))
    if not manifest:
        raise RuntimeError("Provenance manifest is empty")
    if coverage.get("sentences") != sentence_count:
        raise RuntimeError(f"Coverage sentence count {coverage.get('sentences')} differs from SQLite {sentence_count}")
    if coverage.get("unique_indexed_oxford_entry_ids") != target_count:
        raise RuntimeError("Coverage target count differs from SQLite target_entries")

    return {
        "pack_id": metadata["pack_id"],
        "license": metadata["license"],
        "sentences": sentence_count,
        "indexed_targets": target_count,
        "sqlite_bytes": sqlite_path.stat().st_size,
        "gzip_bytes": gzip_path.stat().st_size,
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="worddeck-sentence-release-") as root_text:
        root = Path(root_text)
        db_path = root / "pack.sqlite"
        # Explicitly close the writer too. This matters on Windows, where an open
        # SQLite handle prevents the negative-path unlink below and temp cleanup.
        with closing(sqlite3.connect(db_path)) as db:
            db.executescript("""
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE sentences(sentence_num INTEGER PRIMARY KEY);
                CREATE TABLE target_entries(target_num INTEGER PRIMARY KEY, entry_id TEXT NOT NULL UNIQUE);
            """)
            db.executemany("INSERT INTO metadata(key,value) VALUES(?,?)", [
                ("schema_version", "2"), ("pack_id", "synthetic"),
                ("source_language", "en"), ("target_language", "uk"),
                ("provenance", "synthetic"), ("license", "CC BY 2.0 FR")])
            db.execute("INSERT INTO sentences(sentence_num) VALUES(1)")
            db.execute("INSERT INTO target_entries(target_num,entry_id) VALUES(1,'ox-test')")
            db.commit()
        gzip_path = root / "pack.json.gz"
        with gzip.open(gzip_path, "wt", encoding="utf-8") as handle:
            json.dump({"PackId": "synthetic"}, handle)
        manifest = root / "manifest.json"
        manifest.write_text('{"source":"synthetic"}', encoding="utf-8")
        coverage = root / "coverage.json"
        coverage.write_text('{"sentences":1,"unique_indexed_oxford_entry_ids":1}', encoding="utf-8")
        result = validate(db_path, gzip_path, manifest, coverage)
        if result["sentences"] != 1:
            raise RuntimeError("Synthetic release-bundle validation failed")
        db_path.unlink()
        try:
            validate(db_path, gzip_path, manifest, coverage)
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Validator accepted a release bundle without SQLite")
    print("SentencePack release-bundle validator self-test passed.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", type=Path)
    parser.add_argument("--gzip", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.sqlite, args.gzip, args.manifest, args.coverage)):
        parser.error("--sqlite, --gzip, --manifest and --coverage are required unless --self-test is used")
    print(json.dumps(validate(args.sqlite, args.gzip, args.manifest, args.coverage), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
