#!/usr/bin/env python3
"""Materialize an exact CE-ST-M04 production input from the reviewed source template.

The template is descriptive source data. Hashes and the environment lock are always
recomputed from the current exact text and the actually installed production stack.
This prevents copied/manual digests from becoming production authority.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import subprocess
import sys
from typing import Any

PACKAGES = ("kokoro", "misaki", "huggingface_hub", "numpy", "soundfile", "torch")
LOCK_SCHEMA = "worddeck-m04-audio-environment-lock-v1"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def spoken_text(segments: list[dict[str, Any]]) -> str:
    return "\n".join(str(segment["text"]).strip() for segment in segments)


def first_line(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    text = result.stdout or result.stderr
    lines = text.splitlines()
    if not lines:
        raise RuntimeError(f"no version output from {command[0]}")
    return lines[0].strip()


def materialize(template: Path, output: Path, evidence: Path) -> None:
    raw = template.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    scripts = data.get("scripts")
    if not isinstance(scripts, list) or len(scripts) != 20:
        raise RuntimeError("exactly 20 M04 scripts are required")

    for script in scripts:
        segments = script.get("segments")
        if not isinstance(segments, list) or not segments:
            raise RuntimeError(f"segments missing for {script.get('script_id')}")
        source_text = spoken_text(segments)
        script["source_text_hash"] = hashlib.sha256(source_text.encode("utf-8")).hexdigest()

    package_versions = {name: importlib.metadata.version(name) for name in PACKAGES}
    binary_versions = {
        "ffmpeg": first_line(["ffmpeg", "-version"]),
        "espeak-ng": first_line(["espeak-ng", "--version"]),
    }
    data["dependency_lock"] = {
        "schema": LOCK_SCHEMA,
        "packages": package_versions,
        "binaries": binary_versions,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    ev = {
        "schema": "worddeck-m04-audio-materialization-evidence-v1",
        "template_path": str(template),
        "template_sha256": hashlib.sha256(raw).hexdigest(),
        "materialized_input_path": str(output),
        "materialized_input_sha256": sha256_file(output),
        "python": sys.version,
        "platform": platform.platform(),
        "packages": package_versions,
        "binaries": binary_versions,
        "script_count": len(scripts),
        "source_text_hashes": {script["script_id"]: script["source_text_hash"] for script in scripts},
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(ev, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    materialize(args.template, args.output, args.evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
