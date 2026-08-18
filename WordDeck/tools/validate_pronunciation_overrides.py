#!/usr/bin/env python3
"""Validate WordDeck's development-time British pronunciation override ledger.

This tool intentionally uses only the Python standard library and is never a runtime
WordDeck dependency. It verifies stable IDs/source text against the embedded Oxford
TSV source and can emit a deterministic targeted-regeneration request.

Reviewed heteronyms may use Kokoro/Misaki raw British-English phonemes. This reuses
Kokoro's supported generate_from_tokens path rather than introducing a custom G2P.
"""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import json
from pathlib import Path
from typing import Dict, List

EXPECTED_MARKER_IDS = {
    "oxford-a1-0120", "oxford-a1-0150", "oxford-a1-0211", "oxford-a1-0422",
    "oxford-a1-0434", "oxford-a1-0444", "oxford-a1-0446", "oxford-a1-0480",
    "oxford-a1-0668", "oxford-a1-0669", "oxford-a2-0115", "oxford-a2-0147",
    "oxford-a2-0433", "oxford-a2-0434", "oxford-a2-0440", "oxford-a2-0633",
    "oxford-a2-0652", "oxford-a2-0653", "oxford-a2-0683", "oxford-a2-0859",
    "oxford-b1-0119", "oxford-b1-0151", "oxford-b1-0396", "oxford-b1-0404",
    "oxford-b1-0410", "oxford-b1-0506", "oxford-b1-0608", "oxford-b1-0616",
    "oxford-b1-0768", "oxford-b1-0769", "oxford-b2-0105", "oxford-b2-0468",
    "oxford-b2-0481", "oxford-b2-0655", "oxford-b2-0656", "oxford-b2-0716",
}
EXPECTED_ACRONYMS = {"CD", "DVD", "IT", "OK", "TV"}
VALID_STATUSES = {"ready", "review"}
LEGACY_COLUMNS = ["entry_id", "source", "audio_text", "status", "reason"]
CURRENT_COLUMNS = [*LEGACY_COLUMNS, "phonemes"]
# Misaki's documented British English model vocabulary, plus whitespace which
# is accepted between raw phoneme tokens. Keeping this fail-closed catches IPA
# characters that Kokoro's English model does not consume directly.
MISAKI_BRITISH_PHONEMES = frozenset(
    "AIWYbdfhijklmnpstuvwzðŋɑɔəɛɜɡɪɹʃʊʌʒʤʧˈˌθᵊQaɒː "
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_embedded_dictionary(root: Path) -> Dict[str, dict]:
    parts = sorted((root / "WordDeck" / "Data").glob("oxford3000_uk.tsv.gz.b64part*"))
    if not parts:
        raise RuntimeError("Embedded Oxford base64 parts were not found.")

    encoded = "".join(part.read_text(encoding="ascii").strip() for part in parts)
    text = gzip.decompress(base64.b64decode(encoded)).decode("utf-8-sig")
    entries: Dict[str, dict] = {}
    first_data = True
    for raw in text.splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        fields = raw.split("\t")
        if first_data:
            first_data = False
            if len(fields) >= 4 and fields[0].strip().lower() == "entryid":
                continue
        if len(fields) < 4:
            raise RuntimeError("Malformed embedded dictionary row while validating audio overrides.")
        entry_id, level, source = fields[0].strip(), fields[1].strip(), fields[2].strip()
        target = "\t".join(fields[3:]).strip()
        entries[entry_id] = {"level": level, "source": source, "target": target}
    if len(entries) != 3308:
        raise RuntimeError(f"Expected 3308 embedded entries, found {len(entries)}.")
    return entries


def load_ledger(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames not in (LEGACY_COLUMNS, CURRENT_COLUMNS):
            raise RuntimeError(
                "Ledger columns must be legacy columns or current columns: " + ", ".join(CURRENT_COLUMNS)
            )
        rows = []
        for row in reader:
            normalized = {key: (value or "").strip() for key, value in row.items()}
            normalized.setdefault("phonemes", "")
            rows.append(normalized)
        return rows


def validate_phonemes(entry_id: str, phonemes: str) -> None:
    invalid = sorted(set(phonemes) - MISAKI_BRITISH_PHONEMES)
    if invalid:
        raise RuntimeError(f"Unsupported Kokoro/Misaki phoneme characters for {entry_id}: {invalid}")
    if not phonemes.strip():
        raise RuntimeError(f"Blank phoneme override for {entry_id}")
    if len(phonemes) > 510:
        raise RuntimeError(f"Phoneme override exceeds Kokoro's 510-token limit for {entry_id}")


def validate(entries: Dict[str, dict], rows: List[dict]) -> dict:
    ids = [row["entry_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Pronunciation override ledger contains duplicate entry IDs.")
    if set(ids) != EXPECTED_MARKER_IDS:
        missing = sorted(EXPECTED_MARKER_IDS - set(ids))
        extra = sorted(set(ids) - EXPECTED_MARKER_IDS)
        raise RuntimeError(f"Marker candidate set drifted. Missing={missing}; extra={extra}")

    ready = []
    review = []
    phoneme_ready = []
    for row in rows:
        entry_id = row["entry_id"]
        actual = entries.get(entry_id)
        if actual is None:
            raise RuntimeError(f"Ledger entry ID no longer exists: {entry_id}")
        if actual["source"] != row["source"]:
            raise RuntimeError(
                f"Source drift for {entry_id}: ledger={row['source']!r}, dictionary={actual['source']!r}"
            )
        status = row["status"]
        if status not in VALID_STATUSES:
            raise RuntimeError(f"Invalid status {status!r} for {entry_id}")
        if not row["reason"]:
            raise RuntimeError(f"Missing QA reason for {entry_id}")

        audio_text = row["audio_text"]
        phonemes = row.get("phonemes", "")
        if status == "ready":
            if bool(audio_text) == bool(phonemes):
                raise RuntimeError(
                    f"Ready override must define exactly one of audio_text or phonemes: {entry_id}"
                )
            if audio_text and audio_text == row["source"]:
                raise RuntimeError(f"Ready text override does not change audio text: {entry_id}")
            if phonemes:
                validate_phonemes(entry_id, phonemes)
                phoneme_ready.append(row)
            ready.append(row)
        else:
            if audio_text or phonemes:
                raise RuntimeError(f"Review-only row must not silently define generation data: {entry_id}")
            review.append(row)

    if len(ready) + len(review) != 36:
        raise RuntimeError(f"Expected 36 marker candidates; got {len(ready)} ready and {len(review)} review.")

    acronym_entries = [
        {"entry_id": entry_id, "source": item["source"], "level": item["level"]}
        for entry_id, item in entries.items()
        if item["source"] in EXPECTED_ACRONYMS
    ]
    found_acronyms = {item["source"] for item in acronym_entries}
    if found_acronyms != EXPECTED_ACRONYMS:
        raise RuntimeError(
            f"Expected uppercase QA candidates {sorted(EXPECTED_ACRONYMS)}, found {sorted(found_acronyms)}"
        )

    return {
        "dictionary_entry_count": len(entries),
        "marker_candidate_count": len(rows),
        "ready_override_count": len(ready),
        "phoneme_override_count": len(phoneme_ready),
        "review_only_count": len(review),
        "ready": ready,
        "review": review,
        "acronym_candidates": sorted(acronym_entries, key=lambda item: item["entry_id"]),
    }


def emit_request(path: Path, report: dict) -> None:
    payload = {
        "schema": "worddeck-pronunciation-regeneration-v2",
        "dictionary_id": "oxford-3000-en-uk",
        "accent": "en-GB",
        "ready_overrides": [
            {
                "entry_id": row["entry_id"],
                "source": row["source"],
                "audio_text": row["audio_text"] or None,
                "phonemes": row.get("phonemes") or None,
                "reason": row["reason"],
            }
            for row in report["ready"]
        ],
        "blocked_for_phonetic_or_listening_qa": [
            {"entry_id": row["entry_id"], "source": row["source"], "reason": row["reason"]}
            for row in report["review"]
        ],
        "uppercase_listening_qa": report["acronym_candidates"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--emit-ready", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    root = repo_root()
    ledger = args.ledger or (root / "WordDeck" / "Audio" / "pronunciation-overrides.tsv")
    entries = load_embedded_dictionary(root)
    rows = load_ledger(ledger)
    report = validate(entries, rows)

    if args.emit_ready:
        emit_request(args.emit_ready, report)

    print(
        "Pronunciation override ledger validated: "
        f"{report['marker_candidate_count']} marker candidates; "
        f"{report['ready_override_count']} ready for targeted regeneration "
        f"({report['phoneme_override_count']} raw-phoneme); "
        f"{report['review_only_count']} held for phonetic/listening QA; "
        f"{len(report['acronym_candidates'])} uppercase candidates."
    )
    if args.self_test:
        print("Pronunciation override self-test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
