#!/usr/bin/env python3
"""Batch-generate offline British-English pronunciation for WordDeck.

Designed for resumable generation. Input is UTF-8 TSV containing at least
`entryId`/`entry_id`/`id` and `source` columns. WordDeck metadata comment lines
are accepted. Output is one MP3 per entry plus manifest.jsonl. The voice is
selected deterministically so a given entry keeps the same voice across reruns.

A reviewed row may optionally contain `phonemes` in Kokoro/Misaki English
phoneme notation. When present, generation uses Kokoro's supported raw-phoneme
`generate_from_tokens` path and bypasses ambiguous grapheme-to-phoneme lookup.
This is development-time generation only; WordDeck runtime remains offline .NET.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import numpy as np
import soundfile as sf
from kokoro import KPipeline

SAMPLE_RATE = 24000
FEMALE_VOICE = "bf_emma"
MALE_VOICE = "bm_george"


def args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--limit", type=int, default=0, help="0 means all remaining entries")
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--female-voice", default=FEMALE_VOICE)
    p.add_argument("--male-voice", default=MALE_VOICE)
    p.add_argument("--format", choices=("mp3", "wav"), default="mp3")
    return p.parse_args()


def audio_text(source: str) -> str:
    # Oxford uses numeric sense markers in a few headwords (bass1, bow1,
    # content2, minute2, recount1). They distinguish dictionary senses but
    # must not be spoken aloud.
    return re.sub(r"(?<=\D)[12]$", "", source.strip())


def safe_name(entry_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", entry_id)


def voice_for(entry_id: str, female: str, male: str) -> str:
    # Stable ~50/50 split, independent of list ordering.
    return female if hashlib.sha256(entry_id.encode("utf-8")).digest()[0] < 128 else male


def load_rows(path: Path) -> list[dict[str, str]]:
    raw_lines = path.read_text(encoding="utf-8-sig").splitlines()
    data_lines = [line for line in raw_lines if line.strip() and not line.lstrip().startswith("#")]
    if not data_lines:
        raise SystemExit("Input TSV is empty")

    reader = csv.DictReader(io.StringIO("\n".join(data_lines)), delimiter="\t")
    rows = list(reader)
    if not rows or reader.fieldnames is None:
        raise SystemExit("Input TSV has no usable rows")

    id_column = next((name for name in ("entryId", "entry_id", "id") if name in reader.fieldnames), None)
    if id_column is None or "source" not in reader.fieldnames:
        raise SystemExit("Input TSV must contain entryId, entry_id, or id plus source")

    normalized: list[dict[str, str]] = []
    for row in rows:
        entry_id = (row.get(id_column) or "").strip()
        source = (row.get("source") or "").strip()
        if not entry_id or not source:
            raise SystemExit("Input contains a blank id or source")
        normalized.append({**row, "id": entry_id, "source": source})

    ids = [r["id"] for r in normalized]
    if len(set(ids)) != len(ids):
        raise SystemExit("Input contains duplicate ids")
    return normalized


def render(
    pipeline: KPipeline,
    text: str,
    voice: str,
    speed: float,
    phonemes: str = "",
) -> np.ndarray:
    chunks: list[np.ndarray] = []
    if phonemes:
        # Kokoro officially supports raw Misaki phoneme strings through
        # generate_from_tokens(). This is intentionally preferred for reviewed
        # heteronyms because ordinary G2P cannot infer a dictionary sense from
        # an isolated spelling such as "wind" or "tear".
        for result in pipeline.generate_from_tokens(tokens=phonemes, voice=voice, speed=speed):
            if result.audio is not None:
                chunks.append(np.asarray(result.audio, dtype=np.float32))
    else:
        for _graphemes, _phonemes, audio in pipeline(text, voice=voice, speed=speed):
            chunks.append(np.asarray(audio, dtype=np.float32))
    if not chunks:
        description = phonemes if phonemes else text
        raise RuntimeError(f"TTS produced no audio for {description!r}")
    return np.concatenate(chunks)


def write_audio(audio: np.ndarray, destination: Path, fmt: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "source.wav"
        sf.write(wav, audio, SAMPLE_RATE, subtype="PCM_16")
        if fmt == "wav":
            os.replace(wav, destination)
            return
        # 64 kbps mono MP3 is ample for single-word pronunciation and keeps
        # the final offline audio pack small.
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav),
             "-ac", "1", "-ar", str(SAMPLE_RATE), "-b:a", "64k", str(destination)],
            check=True,
        )


def main() -> int:
    a = args()
    if a.speed <= 0:
        raise SystemExit("--speed must be > 0")
    rows = load_rows(a.input)
    selected = rows[a.start:] if a.limit <= 0 else rows[a.start:a.start + a.limit]
    a.output.mkdir(parents=True, exist_ok=True)
    manifest_path = a.output / "manifest.jsonl"

    pipeline = KPipeline(lang_code="b")
    completed = 0
    with manifest_path.open("a", encoding="utf-8") as manifest:
        for absolute_index, row in enumerate(selected, start=a.start):
            entry_id = row["id"].strip()
            source = row["source"].strip()
            spoken = (row.get("audio_text") or "").strip() or audio_text(source)
            phonemes = (row.get("phonemes") or "").strip()
            voice = voice_for(entry_id, a.female_voice, a.male_voice)
            ext = a.format
            out = a.output / f"{safe_name(entry_id)}.{ext}"

            if out.exists() and out.stat().st_size > 512:
                continue

            audio = render(pipeline, spoken, voice, a.speed, phonemes=phonemes)
            write_audio(audio, out, a.format)
            record = {
                "index": absolute_index,
                "id": entry_id,
                "source": source,
                "audio_text": spoken,
                "phonemes": phonemes or None,
                "voice": voice,
                "accent": "en-GB",
                "speed": a.speed,
                "sample_rate": SAMPLE_RATE,
                "file": out.name,
                "bytes": out.stat().st_size,
            }
            manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
            manifest.flush()
            completed += 1
            mode = f"phonemes={phonemes}" if phonemes else f"text={spoken}"
            print(f"{absolute_index + 1}/{len(rows)} {entry_id}: {mode} -> {out.name} ({voice})")

    print(f"Generated {completed} new files; output={a.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
