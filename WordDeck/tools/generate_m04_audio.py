#!/usr/bin/env python3
"""Fail-closed CE-ST-M04 role-aware audio production tooling.

This tool is intentionally separate from generate_british_audio.py. The existing
generator is for one-voice-per-entry dictionary pronunciation. CE-ST-M04 needs
ordered A/B/C role binding, multi-speaker assets, and a deterministic runtime
cue between the two English lines of CE-ST-M04-L01-AS-002.

No audio is produced by --self-test or --validate-only.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

SCHEMA_ID = "worddeck-ce-st-m04-audio-production-v1"
GENERATOR_ID = "worddeck-m04-role-aware-audio-v1"
SOURCE_DRIVE_ID = "1Ejy6-LyO7zSrD10fhpWzSfX6n2g8zPqO0lqKXFfnusM"
SOURCE_REVISION = (
    "ANLCKQnMVNAKt3SFmhQKE_EACNp-z1lUbwTTskt2pu7foK6wE4iZX124yKMjI1fj"
    "EAPJTKsU4EwwVZ_16RprmtIISb4a83V8eEBgRQxo9g"
)
PREFLIGHT_DRIVE_ID = "1RrpUpWCnLEIYRK3__uRdL98B7ZmWUvrBA_QOLIGQNlg"
PREFLIGHT_REVISION = (
    "ANLCKQldVUpirBTwqHMnGAbCshpxoxBONpGqIOcAfdjPoyVN6rIhF_BJ0lvW5taP"
    "VPFAwWDmnIR1jXbHzIdSaM5F83YKtEFQtns75OleYw"
)

KOKORO_REPO_ID = "hexgrad/Kokoro-82M"
KOKORO_HF_REVISION = "f3ff3571791e39611d31c381e3a41a3af07b4987"
KOKORO_PACKAGE_VERSION = "0.9.4"
KOKORO_MODEL_FILE = "kokoro-v1_0.pth"
KOKORO_MODEL_SHA256 = "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4"

VOICE_BINDINGS = {
    "A": {
        "voice_id": "bf_emma",
        "filename": "voices/bf_emma.pt",
        "sha256": "d0a423deabf4a52b4f49318c51742c54e21bb89bbbe9a12141e7758ddb5da701",
    },
    "B": {
        "voice_id": "bm_george",
        "filename": "voices/bm_george.pt",
        "sha256": "f1bc812213dc59774769e5c80004b13eeb79bd78130b11b2d7f934542dab811b",
    },
    "C": {
        "voice_id": "bf_isabella",
        "filename": "voices/bf_isabella.pt",
        "sha256": "cdd4c37003805104d1d08fb1e05855c8fb2c68de24ca6e71f264a30aaa59eefd",
    },
}

SAMPLE_RATE = 24_000
MP3_BITRATE = "64k"
NORMAL_SPEED = 1.0
DEFAULT_PAUSE_MS = 300
L01_INTERLEAVE_ID = "CE-ST-M04-L01-AS-002"
L01_RUNTIME_EVENT = "localized_semantic_state_change"

EXPECTED_SCRIPT_IDS = tuple(
    [f"CE-ST-M04-L{lesson:02d}-AS-{item:03d}" for lesson in range(1, 9) for item in (1, 2)]
    + [f"CE-ST-M04-MSN-AS-{item:03d}" for item in range(1, 5)]
)

REQUIRED_DEPENDENCY_PACKAGES = (
    "kokoro",
    "misaki",
    "huggingface_hub",
    "numpy",
    "soundfile",
    "torch",
)


class ContractError(ValueError):
    """Raised for deterministic, fail-closed production-contract violations."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_spoken_text(segments: list[dict[str, Any]]) -> str:
    """Only approved English segment text participates in source_text_hash."""
    return "\n".join(str(segment["text"]).strip() for segment in segments)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate_dependency_lock(lock: dict[str, Any]) -> None:
    _require(lock.get("schema") == "worddeck-m04-audio-environment-lock-v1",
             "dependency_lock.schema mismatch")
    packages = lock.get("packages")
    _require(isinstance(packages, dict), "dependency_lock.packages must be an object")
    for package in REQUIRED_DEPENDENCY_PACKAGES:
        value = packages.get(package)
        _require(isinstance(value, str) and value.strip() and value.strip().lower() != "unknown",
                 f"dependency lock missing exact version for {package}")
        _require(not any(op in value for op in (">", "<", "*", "~", "^")),
                 f"dependency lock must contain an exact installed version for {package}")
    _require(packages["kokoro"] == KOKORO_PACKAGE_VERSION,
             f"kokoro must be exactly {KOKORO_PACKAGE_VERSION}")
    for binary in ("ffmpeg", "espeak-ng"):
        value = (lock.get("binaries") or {}).get(binary)
        _require(isinstance(value, str) and value.strip() and value.strip().lower() != "unknown",
                 f"dependency lock missing exact {binary} version")


def validate_contract(data: dict[str, Any]) -> None:
    _require(data.get("schema") == SCHEMA_ID, f"schema must be {SCHEMA_ID}")
    _require(data.get("source_drive_id") == SOURCE_DRIVE_ID, "source_drive_id mismatch")
    _require(data.get("source_revision") == SOURCE_REVISION, "source_revision drift")
    _require(data.get("preflight_drive_id") == PREFLIGHT_DRIVE_ID, "preflight_drive_id mismatch")
    _require(data.get("preflight_revision") == PREFLIGHT_REVISION, "preflight_revision mismatch")
    _require(data.get("production_class") == "TTS", "production_class must be TTS")
    _require(data.get("locale") == "en-GB", "locale must be en-GB")
    _require(float(data.get("speed", 0)) == NORMAL_SPEED, "normal-clear speed must be 1.0")
    _require(data.get("kokoro_repo_id") == KOKORO_REPO_ID, "Kokoro repo mismatch")
    _require(data.get("kokoro_hf_revision") == KOKORO_HF_REVISION, "Kokoro revision mismatch")
    _require(data.get("kokoro_model_sha256") == KOKORO_MODEL_SHA256, "Kokoro model SHA mismatch")
    validate_dependency_lock(data.get("dependency_lock") or {})

    scripts = data.get("scripts")
    _require(isinstance(scripts, list), "scripts must be a list")
    _require(len(scripts) == len(EXPECTED_SCRIPT_IDS), "exactly 20 script objects are required")

    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    actual_ids: list[str] = []
    for script in scripts:
        _require(isinstance(script, dict), "each script object must be an object")
        script_id = str(script.get("script_id") or "")
        asset_key = str(script.get("asset_key") or "")
        _require(script_id in EXPECTED_SCRIPT_IDS, f"unexpected script_id {script_id!r}")
        _require(script_id not in seen_ids, f"duplicate script_id {script_id}")
        _require(asset_key and asset_key not in seen_keys, f"blank or duplicate asset_key for {script_id}")
        seen_ids.add(script_id)
        seen_keys.add(asset_key)
        actual_ids.append(script_id)

        _require(script.get("source_text_revision") == SOURCE_REVISION,
                 f"{script_id}: source_text_revision drift")
        _require(script.get("protected") is False, f"{script_id}: protected must be false")
        _require(script.get("assessment_eligibility") in {"STUDY", "TRANSFER"},
                 f"{script_id}: assessment_eligibility must be STUDY or TRANSFER")
        _require(script.get("normal_or_slow") == "NORMAL",
                 f"{script_id}: only NORMAL assets belong to this production batch")

        segments = script.get("segments")
        _require(isinstance(segments, list) and segments, f"{script_id}: segments required")
        for index, segment in enumerate(segments):
            _require(isinstance(segment, dict), f"{script_id}: segment {index} must be an object")
            _require(segment.get("index") == index, f"{script_id}: segment indexes must be contiguous")
            role = segment.get("role")
            _require(role in VOICE_BINDINGS, f"{script_id}: segment {index} role must be A/B/C")
            text = segment.get("text")
            _require(isinstance(text, str) and text.strip(), f"{script_id}: segment {index} text required")
            _require("\n" not in text.strip(), f"{script_id}: split multi-line text into explicit segments")
            pause_ms = segment.get("pause_after_ms", 0 if index == len(segments) - 1 else DEFAULT_PAUSE_MS)
            _require(isinstance(pause_ms, int) and 0 <= pause_ms <= 1500,
                     f"{script_id}: invalid pause_after_ms")
            event = segment.get("runtime_event_after")
            if event is not None:
                _require(event == L01_RUNTIME_EVENT,
                         f"{script_id}: unknown runtime_event_after {event!r}")
                _require(script_id == L01_INTERLEAVE_ID,
                         f"{script_id}: runtime semantic event allowed only on {L01_INTERLEAVE_ID}")
                _require(index < len(segments) - 1,
                         f"{script_id}: runtime event must be between English segments")

        spoken = canonical_spoken_text(segments)
        expected_hash = sha256_text(spoken)
        _require(script.get("source_text_hash") == expected_hash,
                 f"{script_id}: source_text_hash mismatch")

        if script_id == L01_INTERLEAVE_ID:
            _require(len(segments) == 2,
                     f"{script_id}: exactly two English segments are required")
            _require(segments[0].get("runtime_event_after") == L01_RUNTIME_EVENT,
                     f"{script_id}: first segment must carry the semantic interleave marker")
            _require(not segments[1].get("runtime_event_after"),
                     f"{script_id}: second segment must not carry a semantic event")
        else:
            _require(not any(segment.get("runtime_event_after") for segment in segments),
                     f"{script_id}: unexpected semantic interleave marker")

    _require(set(actual_ids) == set(EXPECTED_SCRIPT_IDS), "script inventory is incomplete")


def _installed_version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError as exc:
        raise ContractError(f"required package is not installed: {package}") from exc


def validate_live_environment(lock: dict[str, Any]) -> dict[str, str]:
    validate_dependency_lock(lock)
    actual = {package: _installed_version(package) for package in REQUIRED_DEPENDENCY_PACKAGES}
    for package, expected in lock["packages"].items():
        if package in actual:
            _require(actual[package] == expected,
                     f"installed {package}={actual[package]} does not match lock {expected}")
    _require(actual["kokoro"] == KOKORO_PACKAGE_VERSION,
             f"installed kokoro must be {KOKORO_PACKAGE_VERSION}")
    return actual


def _command_version(executable: str, *args: str) -> str:
    path = shutil.which(executable)
    if not path:
        raise ContractError(f"required executable not found: {executable}")
    result = subprocess.run([path, *args], capture_output=True, text=True, check=True)
    first = (result.stdout or result.stderr).splitlines()[0].strip()
    _require(bool(first), f"could not read version from {executable}")
    return first


def verify_external_binaries(lock: dict[str, Any]) -> dict[str, str]:
    actual = {
        "ffmpeg": _command_version("ffmpeg", "-version"),
        "espeak-ng": _command_version("espeak-ng", "--version"),
    }
    for name, expected in (lock.get("binaries") or {}).items():
        if name in actual:
            _require(expected in actual[name],
                     f"{name} runtime version does not match dependency lock")
    return actual


def download_and_verify_upstream(cache_dir: Path) -> dict[str, Path]:
    from huggingface_hub import hf_hub_download

    files = {
        "config": ("config.json", None),
        "model": (KOKORO_MODEL_FILE, KOKORO_MODEL_SHA256),
        **{
            f"voice_{role}": (binding["filename"], binding["sha256"])
            for role, binding in VOICE_BINDINGS.items()
        },
    }
    resolved: dict[str, Path] = {}
    for key, (filename, expected_sha) in files.items():
        path = Path(
            hf_hub_download(
                repo_id=KOKORO_REPO_ID,
                filename=filename,
                revision=KOKORO_HF_REVISION,
                cache_dir=str(cache_dir),
            )
        )
        if expected_sha is not None:
            actual = sha256_file(path)
            _require(actual == expected_sha,
                     f"{filename}: SHA mismatch {actual} != {expected_sha}")
        resolved[key] = path
    return resolved


def _render_segment(pipeline: Any, text: str, voice_path: Path) -> Any:
    import numpy as np

    chunks = []
    for result in pipeline(text, voice=str(voice_path), speed=NORMAL_SPEED, split_pattern=None):
        if result.audio is not None:
            chunks.append(np.asarray(result.audio, dtype=np.float32))
    if not chunks:
        raise ContractError(f"TTS produced no audio for {text!r}")
    return np.concatenate(chunks)


def _write_mp3(waveform: Any, destination: Path) -> None:
    import soundfile as sf

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "master.wav"
        sf.write(wav, waveform, SAMPLE_RATE, subtype="PCM_16")
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(wav), "-ac", "1", "-ar", str(SAMPLE_RATE),
                "-b:a", MP3_BITRATE, str(destination),
            ],
            check=True,
        )


def produce(data: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    validate_contract(data)
    versions = validate_live_environment(data["dependency_lock"])
    binaries = verify_external_binaries(data["dependency_lock"])

    import numpy as np
    from kokoro import KPipeline
    from kokoro.model import KModel

    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = output_dir / ".hf-cache"
    upstream = download_and_verify_upstream(cache_dir)
    config_sha = sha256_file(upstream["config"])

    model = KModel(
        repo_id=KOKORO_REPO_ID,
        config=str(upstream["config"]),
        model=str(upstream["model"]),
    ).to("cpu").eval()
    pipeline = KPipeline(
        lang_code="b",
        repo_id=KOKORO_REPO_ID,
        model=model,
        device="cpu",
    )

    batch_manifest: dict[str, Any] = {
        "schema": "worddeck-ce-st-m04-audio-batch-manifest-v1",
        "generator_id": GENERATOR_ID,
        "source_drive_id": SOURCE_DRIVE_ID,
        "source_revision": SOURCE_REVISION,
        "preflight_drive_id": PREFLIGHT_DRIVE_ID,
        "preflight_revision": PREFLIGHT_REVISION,
        "production_class": "TTS",
        "locale": "en-GB",
        "speed": NORMAL_SPEED,
        "sample_rate": SAMPLE_RATE,
        "kokoro_repo_id": KOKORO_REPO_ID,
        "kokoro_hf_revision": KOKORO_HF_REVISION,
        "kokoro_package_version": KOKORO_PACKAGE_VERSION,
        "model_file": KOKORO_MODEL_FILE,
        "model_sha256": KOKORO_MODEL_SHA256,
        "config_sha256": config_sha,
        "voices": {
            role: {
                "voice_id": binding["voice_id"],
                "voice_sha256": binding["sha256"],
            }
            for role, binding in VOICE_BINDINGS.items()
        },
        "packages": versions,
        "binaries": binaries,
        "assets": [],
    }

    for script in data["scripts"]:
        rendered = []
        segment_manifest = []
        cursor = 0
        event_cues = []
        for segment in script["segments"]:
            role = segment["role"]
            voice_path = upstream[f"voice_{role}"]
            audio = _render_segment(pipeline, segment["text"].strip(), voice_path)
            start_sample = cursor
            end_sample = start_sample + len(audio)
            rendered.append(audio)
            cursor = end_sample
            event = segment.get("runtime_event_after")
            if event:
                event_cues.append(
                    {
                        "event": event,
                        "after_segment_index": segment["index"],
                        "sample_offset": end_sample,
                        "seconds": end_sample / SAMPLE_RATE,
                    }
                )
            pause_ms = segment.get(
                "pause_after_ms",
                0 if segment["index"] == len(script["segments"]) - 1 else DEFAULT_PAUSE_MS,
            )
            pause_samples = round(SAMPLE_RATE * pause_ms / 1000)
            if pause_samples:
                rendered.append(np.zeros(pause_samples, dtype=np.float32))
                cursor += pause_samples
            segment_manifest.append(
                {
                    "index": segment["index"],
                    "role": role,
                    "voice_id": VOICE_BINDINGS[role]["voice_id"],
                    "voice_sha256": VOICE_BINDINGS[role]["sha256"],
                    "text_sha256": sha256_text(segment["text"].strip()),
                    "start_sample": start_sample,
                    "end_sample": end_sample,
                    "start_seconds": start_sample / SAMPLE_RATE,
                    "end_seconds": end_sample / SAMPLE_RATE,
                    "pause_after_ms": pause_ms,
                    "runtime_event_after": event,
                }
            )

        waveform = np.concatenate(rendered)
        destination = output_dir / f"{script['asset_key']}.mp3"
        _write_mp3(waveform, destination)
        batch_manifest["assets"].append(
            {
                "script_id": script["script_id"],
                "asset_key": script["asset_key"],
                "source_text_revision": script["source_text_revision"],
                "source_text_hash": script["source_text_hash"],
                "voice_role": [segment["role"] for segment in script["segments"]],
                "production_class": "TTS",
                "locale": "en-GB",
                "accent_variety": "Standard British English",
                "scripted_status": "SCRIPTED",
                "normal_or_slow": "NORMAL",
                "assessment_eligibility": script["assessment_eligibility"],
                "protected": False,
                "codec": "mp3",
                "container": "mp3",
                "sample_rate": SAMPLE_RATE,
                "channels": 1,
                "duration_seconds": len(waveform) / SAMPLE_RATE,
                "bytes": destination.stat().st_size,
                "sha256": sha256_file(destination),
                "rights_basis": script["rights_basis"],
                "redistribution_status": script["redistribution_status"],
                "notice_or_attribution_pointer": script["notice_or_attribution_pointer"],
                "segments": segment_manifest,
                "runtime_event_cues": event_cues,
                "qa_status": "NOT_REVIEWED",
                "transcript_match_status": "NOT_REVIEWED",
                "loudness_technical_qa": "NOT_REVIEWED",
                "accessibility_replay_semantics": "PENDING_RUNTIME_QA",
                "file": destination.name,
            }
        )

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(batch_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return batch_manifest


def _synthetic_dependency_lock() -> dict[str, Any]:
    return {
        "schema": "worddeck-m04-audio-environment-lock-v1",
        "packages": {
            "kokoro": "0.9.4",
            "misaki": "0.9.4",
            "huggingface_hub": "0.34.4",
            "numpy": "2.2.6",
            "soundfile": "0.13.1",
            "torch": "2.8.0",
        },
        "binaries": {
            "ffmpeg": "ffmpeg version 7.1.1",
            "espeak-ng": "eSpeak NG text-to-speech: 1.52.0",
        },
    }


def _self_test_contract() -> dict[str, Any]:
    scripts = []
    for i, script_id in enumerate(EXPECTED_SCRIPT_IDS):
        if script_id == L01_INTERLEAVE_ID:
            segments = [
                {
                    "index": 0,
                    "role": "A",
                    "text": "This is Noor.",
                    "pause_after_ms": 300,
                    "runtime_event_after": L01_RUNTIME_EVENT,
                },
                {
                    "index": 1,
                    "role": "A",
                    "text": "That is Noor.",
                    "pause_after_ms": 0,
                },
            ]
        else:
            role = ("A", "B", "C")[i % 3]
            segments = [
                {
                    "index": 0,
                    "role": role,
                    "text": f"Synthetic self test {i + 1}.",
                    "pause_after_ms": 0,
                }
            ]
        scripts.append(
            {
                "script_id": script_id,
                "asset_key": script_id.lower(),
                "source_text_revision": SOURCE_REVISION,
                "source_text_hash": sha256_text(canonical_spoken_text(segments)),
                "assessment_eligibility": "TRANSFER" if i % 3 == 2 else "STUDY",
                "protected": False,
                "normal_or_slow": "NORMAL",
                "rights_basis": "WORDDECK_ORIGINAL",
                "redistribution_status": "PROJECT_RELEASE_ELIGIBLE_PENDING_QA",
                "notice_or_attribution_pointer": "M04_AUDIO_PREFLIGHT",
                "segments": segments,
            }
        )
    return {
        "schema": SCHEMA_ID,
        "source_drive_id": SOURCE_DRIVE_ID,
        "source_revision": SOURCE_REVISION,
        "preflight_drive_id": PREFLIGHT_DRIVE_ID,
        "preflight_revision": PREFLIGHT_REVISION,
        "production_class": "TTS",
        "locale": "en-GB",
        "speed": NORMAL_SPEED,
        "kokoro_repo_id": KOKORO_REPO_ID,
        "kokoro_hf_revision": KOKORO_HF_REVISION,
        "kokoro_model_sha256": KOKORO_MODEL_SHA256,
        "dependency_lock": _synthetic_dependency_lock(),
        "scripts": scripts,
    }


def self_test() -> None:
    data = _self_test_contract()
    validate_contract(data)

    expected_roles = {"A": "bf_emma", "B": "bm_george", "C": "bf_isabella"}
    _require(
        {role: value["voice_id"] for role, value in VOICE_BINDINGS.items()} == expected_roles,
        "voice-role freeze changed",
    )
    _require(len(EXPECTED_SCRIPT_IDS) == 20, "M04 script inventory must remain exactly 20")
    _require(
        len(set(binding["sha256"] for binding in VOICE_BINDINGS.values())) == 3,
        "voice hashes must be distinct",
    )

    mutations = []

    bad = json.loads(json.dumps(data))
    bad["source_revision"] = "drift"
    mutations.append(("source revision drift", bad))

    bad = json.loads(json.dumps(data))
    bad["dependency_lock"]["packages"]["kokoro"] = "0.9.5"
    mutations.append(("kokoro pin drift", bad))

    bad = json.loads(json.dumps(data))
    bad["scripts"][0]["segments"][0]["role"] = "UNKNOWN"
    mutations.append(("unknown voice role", bad))

    bad = json.loads(json.dumps(data))
    l01 = next(x for x in bad["scripts"] if x["script_id"] == L01_INTERLEAVE_ID)
    l01["segments"][0].pop("runtime_event_after")
    mutations.append(("missing L01 semantic interleave marker", bad))

    bad = json.loads(json.dumps(data))
    bad["scripts"][1]["source_text_hash"] = "0" * 64
    mutations.append(("source text hash drift", bad))

    bad = json.loads(json.dumps(data))
    bad["scripts"].pop()
    mutations.append(("missing governed script object", bad))

    for label, candidate in mutations:
        try:
            validate_contract(candidate)
        except ContractError:
            continue
        raise AssertionError(f"self-test expected fail-closed rejection: {label}")

    print(
        "SELF_TEST_PASS "
        f"schema={SCHEMA_ID} scripts={len(EXPECTED_SCRIPT_IDS)} "
        f"model_sha={KOKORO_MODEL_SHA256} "
        f"voices=A:{VOICE_BINDINGS['A']['voice_id']},"
        f"B:{VOICE_BINDINGS['B']['voice_id']},"
        f"C:{VOICE_BINDINGS['C']['voice_id']}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--validate-only", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    modes = sum(bool(value) for value in (args.self_test, args.validate_only, args.input))
    if modes != 1:
        raise SystemExit("choose exactly one of --self-test, --validate-only FILE, or --input FILE")
    if args.self_test:
        self_test()
        return 0

    input_path = args.validate_only or args.input
    assert input_path is not None
    data = json.loads(input_path.read_text(encoding="utf-8"))
    validate_contract(data)

    if args.validate_only:
        print(
            f"VALIDATION_PASS schema={SCHEMA_ID} scripts={len(data['scripts'])} "
            f"source_revision={SOURCE_REVISION}"
        )
        return 0

    if args.output is None:
        raise SystemExit("--output DIR is required with --input")
    manifest = produce(data, args.output)
    print(
        f"PRODUCTION_COMPLETE assets={len(manifest['assets'])} "
        f"manifest={args.output / 'manifest.json'} QA=NOT_REVIEWED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
