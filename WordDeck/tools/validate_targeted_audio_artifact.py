#!/usr/bin/env python3
"""Validate a targeted British AudioPack replacement artifact.

Development/QA utility only. It does not generate speech and does not ship in the
WordDeck runtime. Uses Python standard library only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
from pathlib import Path


def read_ready_ledger(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle, delimiter="\t")]
    ready = [row for row in rows if row.get("status") == "ready"]
    if not ready:
        raise RuntimeError("Pronunciation ledger contains no ready rows")
    ids = [row.get("entry_id", "") for row in ready]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("Ready pronunciation ledger has blank or duplicate stable IDs")
    return ready


def read_manifest(path: Path) -> list[dict]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records:
        raise RuntimeError("Audio manifest is empty")
    return records


def validate(root: Path, ledger_path: Path, expected_count: int | None = None) -> None:
    manifest_path = root / "manifest.jsonl"
    if not manifest_path.is_file():
        raise RuntimeError("manifest.jsonl is missing from targeted audio artifact")
    ledger = read_ready_ledger(ledger_path)
    records = read_manifest(manifest_path)
    if expected_count is None:
        expected_count = len(ledger)
    if len(records) != expected_count:
        raise RuntimeError(f"Expected {expected_count} manifest rows, found {len(records)}")
    if len(ledger) != expected_count:
        raise RuntimeError(f"Ready ledger count {len(ledger)} does not equal expected count {expected_count}")

    expected_by_id = {row["entry_id"]: row for row in ledger}
    seen_ids: set[str] = set()
    seen_files: set[str] = set()
    for record in records:
        entry_id = str(record.get("id") or "")
        file_name = str(record.get("file") or "")
        if entry_id in seen_ids or not entry_id:
            raise RuntimeError(f"Blank or duplicate manifest stable ID: {entry_id!r}")
        if file_name in seen_files or not file_name:
            raise RuntimeError(f"Blank or duplicate manifest file name: {file_name!r}")
        seen_ids.add(entry_id)
        seen_files.add(file_name)

        expected = expected_by_id.get(entry_id)
        if expected is None:
            raise RuntimeError(f"Manifest contains unreviewed stable ID: {entry_id}")
        if str(record.get("source") or "") != expected.get("source", ""):
            raise RuntimeError(f"Source drift for {entry_id}")
        expected_phonemes = expected.get("phonemes", "")
        if str(record.get("phonemes") or "") != expected_phonemes:
            raise RuntimeError(f"Phoneme drift for {entry_id}")
        if not expected_phonemes:
            expected_text = expected.get("audio_text", "")
            if not expected_text or str(record.get("audio_text") or "") != expected_text:
                raise RuntimeError(f"Text-mode audio override drift for {entry_id}")

        if record.get("accent") != "en-GB" or int(record.get("sample_rate") or 0) != 24000:
            raise RuntimeError(f"Unexpected British audio metadata for {entry_id}")
        if float(record.get("speed") or 0) != 1.0:
            raise RuntimeError(f"Unexpected speed for {entry_id}")
        if record.get("voice") not in {"bf_emma", "bm_george"}:
            raise RuntimeError(f"Unexpected voice for {entry_id}: {record.get('voice')}")

        audio_path = root / file_name
        if not audio_path.is_file():
            raise RuntimeError(f"Audio file missing for {entry_id}: {file_name}")
        payload = audio_path.read_bytes()
        if len(payload) <= 512:
            raise RuntimeError(f"Audio file is suspiciously small for {entry_id}: {len(payload)} bytes")
        if int(record.get("bytes") or -1) != len(payload):
            raise RuntimeError(f"Byte-size mismatch for {entry_id}")
        digest = hashlib.sha256(payload).hexdigest()
        if str(record.get("sha256") or "") != digest:
            raise RuntimeError(f"SHA-256 mismatch for {entry_id}")

    missing = sorted(set(expected_by_id) - seen_ids)
    if missing:
        raise RuntimeError(f"Targeted artifact omitted reviewed IDs: {missing[:5]}")
    print(f"Targeted British audio artifact validated: {len(records)} stable-ID replacements.")


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="worddeck-audio-validator-") as temp:
        root = Path(temp)
        ledger = root / "ledger.tsv"
        ledger.write_text(
            "entry_id\tsource\taudio_text\tstatus\tnotes\tphonemes\n"
            "test-1\tclose¹\tclose\tready\ttest\t\n"
            "test-2\tCD\t\tready\ttest\tˌsiː ˈdiː\n",
            encoding="utf-8",
        )
        payload1 = b"ID3" + b"a" * 700
        payload2 = b"ID3" + b"b" * 800
        (root / "test-1.mp3").write_bytes(payload1)
        (root / "test-2.mp3").write_bytes(payload2)
        records = [
            {
                "id": "test-1", "source": "close¹", "audio_text": "close", "phonemes": "",
                "file": "test-1.mp3", "bytes": len(payload1), "sha256": hashlib.sha256(payload1).hexdigest(),
                "accent": "en-GB", "sample_rate": 24000, "speed": 1.0, "voice": "bf_emma",
            },
            {
                "id": "test-2", "source": "CD", "audio_text": "CD", "phonemes": "ˌsiː ˈdiː",
                "file": "test-2.mp3", "bytes": len(payload2), "sha256": hashlib.sha256(payload2).hexdigest(),
                "accent": "en-GB", "sample_rate": 24000, "speed": 1.0, "voice": "bm_george",
            },
        ]
        (root / "manifest.jsonl").write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n", encoding="utf-8")
        validate(root, ledger, 2)

        records[0]["sha256"] = "0" * 64
        (root / "manifest.jsonl").write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n", encoding="utf-8")
        try:
            validate(root, ledger, 2)
        except RuntimeError as exc:
            if "SHA-256 mismatch" not in str(exc):
                raise
        else:
            raise RuntimeError("Self-test failed: corrupted audio hash was accepted")
    print("Targeted audio artifact validator self-test passed.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.artifact_dir is None or args.ledger is None:
        parser.error("--artifact-dir and --ledger are required unless --self-test is used")
    validate(args.artifact_dir, args.ledger, args.expected_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
