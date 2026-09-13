#!/usr/bin/env python3
"""Fail-closed CE-A1-M09 governed Listening audio producer.

Development/build-time utility only. It validates an exact governed production
contract without importing ML dependencies, and only imports Kokoro/Torch when
actual synthesis is requested. Generated assets remain QA_NOT_REVIEWED and are
not runtime/release authorized by this tool.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from typing import Any

SCHEMA = "worddeck-ce-a1-m09-audio-production-v1"
SOURCE_DRIVE_ID = "1yFgbMnybo5maRL7mxbe67buC9-aRDov-avorLJNSKMA"
SOURCE_REVISION = "ANLCKQkFQ-Szags_9njW1_3yf9_jbYj3TIIXX3jACIDo731tW0HJiwIYcGk_Mei2t6V4NkCjGyw2Mz4sjLfBVeneiy2CDgvQNRtHm8p5UA"
SOURCE_INTEGRATION_DRIVE_ID = "1iqDYCo7U5BaI7r1GWiU2-Y5kQtk61FRsSz75YIny5ns"
SOURCE_INTEGRATION_REVISION = "ANLCKQl4N5fEhtF9rsukG-_YshrJoJTPs8h5MCLeJzhimS0KmsRG0XkYNV0_JuUgwogHj1vqZGeS7DYSir8-K4SaxN3s-zZ5Y0DEoqd7IQ"
NAMESPACE_AUTHORITY_DRIVE_ID = "1IS0JJUZp_pgcv6fw5L8xlRiOckFrwQamwfZdBDLw6vo"
NAMESPACE_AUTHORITY_REVISION = "ANLCKQnksiSjM5vozvxK6INya73WytQBU2fEeODgVpNqNapQ_91KEJWljHbRdxaOn7uCLpo84Rgs0vaVFA5OykRtVmJdXdbVsXX3GAVxjQ"
MODEL_REPO = "hexgrad/Kokoro-82M"
MODEL_REVISION = "f3ff3571791e39611d31c381e3a41a3af07b4987"
MODEL_FILE = "kokoro-v1_0.pth"
MODEL_SHA256 = "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4"
KOKORO_WHEEL_SHA256 = "a129dc6364a286bd6a92c396e9862459d3d3e45f2c15596ed5a94dcee5789efd"
SAMPLE_RATE = 24000
SPEED = 1.0
EXPECTED_SOURCE_IDS = [f"CE-A1-M09-LSN{i:04d}" for i in range(1, 11)]
EXPECTED_AUDIO_IDS = [f"CE-A1-M09-AUD{i:04d}" for i in range(1, 11)]
VOICE_LOCK = {
    "A": ("bf_emma", "voices/bf_emma.pt", "d0a423deabf4a52b4f49318c51742c54e21bb89bbbe9a12141e7758ddb5da701"),
    "B": ("bm_george", "voices/bm_george.pt", "f1bc812213dc59774769e5c80004b13eeb79bd78130b11b2d7f934542dab811b"),
    "C": ("bf_isabella", "voices/bf_isabella.pt", "cdd4c37003805104d1d08fb1e05855c8fb2c68de24ca6e71f264a30aaa59eefd"),
}
PACKAGE_LOCK = {
    "kokoro": "0.9.4",
    "misaki": "0.9.4",
    "huggingface_hub": "0.34.4",
    "numpy": "2.2.6",
    "soundfile": "0.13.1",
    "torch": "2.8.0",
}


class ContractError(RuntimeError):
    pass


def req(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reconstructed_transcript(segments: list[dict[str, Any]]) -> str:
    req(bool(segments), "segments must not be empty")
    if len(segments) == 1:
        return str(segments[0]["text"]).strip()
    return " ".join(f"{segment['role']}: {str(segment['text']).strip()}" for segment in segments)


def validate_contract(data: dict[str, Any]) -> None:
    req(data.get("schema") == SCHEMA, "schema mismatch")
    exact = {
        "course_id": "CE-A1",
        "module_id": "CE-A1-M09",
        "ownership_coordinate": "COMPLETE_ENGLISH|A1|CE-A1-M09|AUDIO_PRODUCTION",
        "namespace_version": "A1OID-v0.2",
        "source_drive_id": SOURCE_DRIVE_ID,
        "source_revision": SOURCE_REVISION,
        "source_integration_drive_id": SOURCE_INTEGRATION_DRIVE_ID,
        "source_integration_revision": SOURCE_INTEGRATION_REVISION,
        "namespace_authority_drive_id": NAMESPACE_AUTHORITY_DRIVE_ID,
        "namespace_authority_revision": NAMESPACE_AUTHORITY_REVISION,
        "production_class": "TTS",
        "locale": "en-GB",
        "accent_variety": "Standard British English",
        "speed": SPEED,
        "sample_rate": SAMPLE_RATE,
        "channels": 1,
        "codec": "mp3",
        "bitrate_kbps": 64,
        "provider": "hexgrad",
        "model": "Kokoro-82M",
        "model_version": "v1.0",
        "kokoro_repo_id": MODEL_REPO,
        "kokoro_hf_revision": MODEL_REVISION,
        "kokoro_model_file": MODEL_FILE,
        "kokoro_model_sha256": MODEL_SHA256,
        "kokoro_package_version": PACKAGE_LOCK["kokoro"],
        "kokoro_wheel_sha256": KOKORO_WHEEL_SHA256,
        "model_provider_license": "Apache-2.0",
        "rights_basis": "WORDDECK_PROJECT_AUTHORED_AI_ASSISTED_SOURCE",
        "redistribution_status": "CANDIDATE_QA_ONLY_PENDING_PROJECT_RIGHTS_RELEASE",
        "commercial_release": "HOLD",
        "runtime_binding": "NOT_PERFORMED",
        "qa_status": "NOT_REVIEWED",
    }
    for key, value in exact.items():
        req(data.get(key) == value, f"{key} mismatch")

    deps = data.get("dependency_lock", {}).get("packages")
    req(deps == PACKAGE_LOCK, "dependency package lock mismatch")

    voices = data.get("voices")
    req(isinstance(voices, dict) and set(voices) == set(VOICE_LOCK), "voice-role set mismatch")
    for role, (voice_id, filename, digest) in VOICE_LOCK.items():
        row = voices[role]
        req(row.get("voice_id") == voice_id, f"{role}: voice id mismatch")
        req(row.get("file") == filename, f"{role}: voice file mismatch")
        req(row.get("sha256") == digest, f"{role}: voice hash mismatch")

    assets = data.get("assets")
    req(isinstance(assets, list) and len(assets) == 10, "exactly 10 assets required")
    req([row.get("source_object_id") for row in assets] == EXPECTED_SOURCE_IDS, "LSN inventory/order mismatch")
    req([row.get("audio_id") for row in assets] == EXPECTED_AUDIO_IDS, "AUD inventory/order mismatch")
    req(len({row["source_object_id"] for row in assets}) == 10, "duplicate source object")
    req(len({row["audio_id"] for row in assets}) == 10, "duplicate audio id")

    for index, asset in enumerate(assets, start=1):
        aid = asset["audio_id"]
        sid = asset["source_object_id"]
        req(asset.get("source_object_revision") == SOURCE_REVISION, f"{aid}: source revision drift")
        transcript = asset.get("exact_transcript")
        script_hash = asset.get("script_sha256")
        req(isinstance(transcript, str) and transcript.strip() == transcript and "\n" not in transcript, f"{aid}: invalid transcript")
        req(script_hash == text_sha(transcript), f"{aid}: transcript SHA mismatch")
        req(asset.get("normal_or_slow") == "NORMAL", f"{aid}: only normal asset allowed")
        req(asset.get("protected") is False, f"{aid}: protected must be false")
        req(asset.get("eligible_for_mastery") is False, f"{aid}: producer cannot mint mastery eligibility")
        req(asset.get("qa_status") == "NOT_REVIEWED", f"{aid}: producer cannot pre-approve QA")
        expected_exposure = "TRANSFER_FRESH_UNSEEN" if index >= 9 else "PRACTICE"
        req(asset.get("exposure_class") == expected_exposure, f"{aid}: exposure class mismatch")

        segments = asset.get("segments")
        req(isinstance(segments, list) and 1 <= len(segments) <= 4, f"{aid}: invalid segments")
        req([seg.get("index") for seg in segments] == list(range(len(segments))), f"{aid}: segment indexes not contiguous")
        for seg_index, segment in enumerate(segments):
            role = segment.get("role")
            value = segment.get("text")
            req(role in VOICE_LOCK, f"{aid}: unknown role {role!r}")
            req(isinstance(value, str) and value.strip() == value and value and "\n" not in value, f"{aid}: invalid segment text")
            pause = segment.get("pause_after_ms")
            req(isinstance(pause, int) and 0 <= pause <= 1500, f"{aid}: invalid pause")
            if seg_index == len(segments) - 1:
                req(pause == 0, f"{aid}: final pause must be zero")

        req(reconstructed_transcript(segments) == transcript, f"{aid}: segment reconstruction != exact transcript")
        if len(segments) > 1:
            req({segment["role"] for segment in segments} == {"A", "B"}, f"{aid}: dialogue must use exactly distinct roles A/B")
        if sid == "CE-A1-M09-LSN0009":
            req(len(segments) == 1 and segments[0]["role"] == "C", f"{aid}: fresh transfer LSN0009 must use frozen C voice")


def validate_runtime_and_wheel(data: dict[str, Any], kokoro_wheel: Path) -> dict[str, str]:
    validate_contract(data)
    req(kokoro_wheel.is_file(), "exact Kokoro wheel evidence file missing")
    req(file_sha(kokoro_wheel) == KOKORO_WHEEL_SHA256, "Kokoro wheel SHA-256 mismatch")
    actual: dict[str, str] = {}
    for name, expected in PACKAGE_LOCK.items():
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ContractError(f"required package missing: {name}") from exc
        req(version == expected, f"installed {name}={version} != lock {expected}")
        actual[name] = version

    for binary, args in (("ffmpeg", ("-version",)), ("espeak-ng", ("--version",))):
        path = shutil.which(binary)
        req(bool(path), f"required binary missing: {binary}")
        result = subprocess.run([str(path), *args], capture_output=True, text=True, check=True)
        lines = (result.stdout or result.stderr).splitlines()
        req(bool(lines), f"{binary}: cannot capture version")
        actual[binary] = lines[0].strip()
    actual["python"] = sys.version.replace("\n", " ")
    actual["platform"] = platform.platform()
    actual["kokoro_wheel_sha256"] = file_sha(kokoro_wheel)
    return actual


def fetch_upstream(cache: Path) -> dict[str, Path]:
    from huggingface_hub import hf_hub_download

    specs = {
        "config": ("config.json", None),
        "model": (MODEL_FILE, MODEL_SHA256),
        **{f"voice_{role}": (filename, digest) for role, (_voice, filename, digest) in VOICE_LOCK.items()},
    }
    found: dict[str, Path] = {}
    for key, (filename, expected) in specs.items():
        path = Path(hf_hub_download(
            repo_id=MODEL_REPO,
            filename=filename,
            revision=MODEL_REVISION,
            cache_dir=str(cache),
        ))
        if expected:
            req(file_sha(path) == expected, f"upstream SHA mismatch: {filename}")
        found[key] = path
    return found


def render(pipeline: Any, text: str, voice_file: Path) -> Any:
    import numpy as np

    chunks = [
        np.asarray(result.audio, dtype=np.float32)
        for result in pipeline(text, voice=str(voice_file), speed=SPEED, split_pattern=None)
        if result.audio is not None
    ]
    req(bool(chunks), f"TTS produced no audio for {text!r}")
    return np.concatenate(chunks)


def write_mp3(waveform: Any, destination: Path) -> None:
    import soundfile as sf

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="worddeck-m09-audio-") as td:
        wav = Path(td) / "source.wav"
        sf.write(wav, waveform, SAMPLE_RATE, subtype="PCM_16")
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(wav), "-ac", "1", "-ar", str(SAMPLE_RATE),
            "-b:a", "64k", str(destination),
        ], check=True)


def produce(data: dict[str, Any], output: Path, kokoro_wheel: Path) -> dict[str, Any]:
    runtime = validate_runtime_and_wheel(data, kokoro_wheel)
    import numpy as np
    from kokoro import KPipeline
    from kokoro.model import KModel

    output.mkdir(parents=True, exist_ok=True)
    pinned = fetch_upstream(output / ".hf-cache")
    model = KModel(repo_id=MODEL_REPO, config=str(pinned["config"]), model=str(pinned["model"])).to("cpu").eval()
    pipeline = KPipeline(lang_code="b", repo_id=MODEL_REPO, model=model, device="cpu")
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    manifest: dict[str, Any] = {
        "schema": "worddeck-ce-a1-m09-audio-batch-manifest-v1",
        "contract_schema": SCHEMA,
        "course_id": "CE-A1",
        "module_id": "CE-A1-M09",
        "source_drive_id": SOURCE_DRIVE_ID,
        "source_revision": SOURCE_REVISION,
        "source_integration_drive_id": SOURCE_INTEGRATION_DRIVE_ID,
        "source_integration_revision": SOURCE_INTEGRATION_REVISION,
        "namespace_authority_drive_id": NAMESPACE_AUTHORITY_DRIVE_ID,
        "namespace_authority_revision": NAMESPACE_AUTHORITY_REVISION,
        "production_class": "TTS",
        "provider": "hexgrad",
        "model": "Kokoro-82M",
        "model_version": "v1.0",
        "model_sha256": MODEL_SHA256,
        "model_provider_license": "Apache-2.0",
        "kokoro_repo_id": MODEL_REPO,
        "kokoro_hf_revision": MODEL_REVISION,
        "kokoro_package_version": PACKAGE_LOCK["kokoro"],
        "kokoro_wheel_sha256": KOKORO_WHEEL_SHA256,
        "config_sha256": file_sha(pinned["config"]),
        "voices": {
            role: {"voice_id": voice_id, "sha256": digest}
            for role, (voice_id, _filename, digest) in VOICE_LOCK.items()
        },
        "generation_date": generated_at,
        "locale": "en-GB",
        "accent_variety": "Standard British English",
        "speed": SPEED,
        "sample_rate": SAMPLE_RATE,
        "channels": 1,
        "codec": "mp3",
        "bitrate_kbps": 64,
        "runtime_versions": runtime,
        "rights_basis": data["rights_basis"],
        "redistribution_status": data["redistribution_status"],
        "notice_or_attribution_pointer": data["notice_or_attribution_pointer"],
        "qa_status": "NOT_REVIEWED",
        "runtime_binding": "NOT_PERFORMED",
        "commercial_release": "HOLD",
        "assets": [],
    }

    for asset in data["assets"]:
        pieces = []
        segments_out = []
        cursor = 0
        for segment in asset["segments"]:
            role = segment["role"]
            waveform = render(pipeline, segment["text"], pinned[f"voice_{role}"])
            start = cursor
            end = cursor + len(waveform)
            pieces.append(waveform)
            cursor = end
            pause_ms = segment["pause_after_ms"]
            pause_samples = round(SAMPLE_RATE * pause_ms / 1000)
            if pause_samples:
                pieces.append(np.zeros(pause_samples, dtype=np.float32))
                cursor += pause_samples
            voice_id, _voice_file, voice_sha = VOICE_LOCK[role]
            segments_out.append({
                "index": segment["index"],
                "role": role,
                "voice_id": voice_id,
                "voice_sha256": voice_sha,
                "text_sha256": text_sha(segment["text"]),
                "start_sample": start,
                "end_sample": end,
                "start_seconds": start / SAMPLE_RATE,
                "end_seconds": end / SAMPLE_RATE,
                "pause_after_ms": pause_ms,
                "qa_status": "NOT_REVIEWED",
            })

        waveform = np.concatenate(pieces)
        destination = output / f"{asset['audio_id']}.mp3"
        write_mp3(waveform, destination)
        manifest["assets"].append({
            "audio_id": asset["audio_id"],
            "source_object_id": asset["source_object_id"],
            "source_object_revision": asset["source_object_revision"],
            "script_sha256": asset["script_sha256"],
            "exact_transcript": asset["exact_transcript"],
            "file": destination.name,
            "bytes": destination.stat().st_size,
            "sha256": file_sha(destination),
            "duration_seconds": len(waveform) / SAMPLE_RATE,
            "normal_or_slow": "NORMAL",
            "exposure_class": asset["exposure_class"],
            "protected": False,
            "eligible_for_mastery": False,
            "qa_status": "NOT_REVIEWED",
            "transcript_match_status": "NOT_REVIEWED",
            "acoustic_qa_status": "NOT_REVIEWED",
            "technical_qa_status": "NOT_REVIEWED",
            "accessibility_qa_status": "NOT_REVIEWED",
            "runtime_binding": "NOT_PERFORMED",
            "commercial_release": "HOLD",
            "segments": segments_out,
        })

    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def self_test(contract_path: Path) -> None:
    data = json.loads(contract_path.read_text(encoding="utf-8"))
    validate_contract(data)

    def clone() -> dict[str, Any]:
        return json.loads(json.dumps(data))

    mutations: list[tuple[str, dict[str, Any]]] = []
    bad = clone(); bad["source_revision"] = "drift"; mutations.append(("source revision drift", bad))
    bad = clone(); bad["assets"][0]["script_sha256"] = "0" * 64; mutations.append(("transcript hash drift", bad))
    bad = clone(); bad["assets"][1]["segments"][0]["text"] += " changed"; mutations.append(("dialogue reconstruction drift", bad))
    bad = clone(); bad["assets"][1]["segments"][1]["role"] = "A"; mutations.append(("dialogue role collapse", bad))
    bad = clone(); bad["assets"][8]["segments"][0]["role"] = "A"; mutations.append(("fresh-transfer voice drift", bad))
    bad = clone(); bad["assets"][0]["eligible_for_mastery"] = True; mutations.append(("producer mastery escalation", bad))
    bad = clone(); bad["assets"].pop(); mutations.append(("missing audio object", bad))
    bad = clone(); bad["voices"]["A"]["sha256"] = "0" * 64; mutations.append(("voice hash drift", bad))
    bad = clone(); bad["dependency_lock"]["packages"]["kokoro"] = ">=0.9.4"; mutations.append(("non-exact package pin", bad))

    for label, candidate in mutations:
        try:
            validate_contract(candidate)
        except ContractError:
            continue
        raise AssertionError(f"expected fail-closed rejection: {label}")

    print(
        "SELF_TEST_PASS "
        f"schema={SCHEMA} assets=10 source={SOURCE_DRIVE_ID}@{SOURCE_REVISION} "
        f"aud_range={EXPECTED_AUDIO_IDS[0]}..{EXPECTED_AUDIO_IDS[-1]}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", type=Path, metavar="CONTRACT")
    parser.add_argument("--validate-only", type=Path, metavar="CONTRACT")
    parser.add_argument("--input", type=Path, metavar="CONTRACT")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--kokoro-wheel", type=Path)
    args = parser.parse_args()

    modes = [args.self_test is not None, args.validate_only is not None, args.input is not None]
    req(sum(modes) == 1, "choose exactly one of --self-test, --validate-only, or --input")

    if args.self_test is not None:
        self_test(args.self_test)
        return 0

    source = args.validate_only or args.input
    assert source is not None
    data = json.loads(source.read_text(encoding="utf-8"))
    validate_contract(data)
    if args.validate_only is not None:
        print(f"VALIDATION_PASS schema={SCHEMA} assets=10 source_revision={SOURCE_REVISION}")
        return 0

    req(args.output is not None, "--output DIR is required with --input")
    req(args.kokoro_wheel is not None, "--kokoro-wheel FILE is required with --input")
    manifest = produce(data, args.output, args.kokoro_wheel)
    print(
        f"PRODUCTION_COMPLETE assets={len(manifest['assets'])} "
        f"manifest={args.output / 'manifest.json'} QA=NOT_REVIEWED RELEASE=HOLD"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
