#!/usr/bin/env python3
"""Fail-closed, role-aware CE-ST-M04 audio production tooling.

Validation and --self-test are stdlib-only. Actual synthesis is build-time only;
no generated audio belongs in source control and producer success is not QA.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

SCHEMA = "worddeck-ce-st-m04-audio-production-v1"
LOCK_SCHEMA = "worddeck-m04-audio-environment-lock-v1"
GENERATOR = "worddeck-m04-role-aware-audio-v1"
SOURCE_DRIVE_ID = "1Ejy6-LyO7zSrD10fhpWzSfX6n2g8zPqO0lqKXFfnusM"
SOURCE_REVISION = "ANLCKQnMVNAKt3SFmhQKE_EACNp-z1lUbwTTskt2pu7foK6wE4iZX124yKMjI1fjEAPJTKsU4EwwVZ_16RprmtIISb4a83V8eEBgRQxo9g"
PREFLIGHT_DRIVE_ID = "1RrpUpWCnLEIYRK3__uRdL98B7ZmWUvrBA_QOLIGQNlg"
PREFLIGHT_REVISION = "ANLCKQldVUpirBTwqHMnGAbCshpxoxBONpGqIOcAfdjPoyVN6rIhF_BJ0lvW5taPVPFAwWDmnIR1jXbHzIdSaM5F83YKtEFQtns75OleYw"
KOKORO_REPO = "hexgrad/Kokoro-82M"
KOKORO_REVISION = "f3ff3571791e39611d31c381e3a41a3af07b4987"
KOKORO_VERSION = "0.9.4"
MODEL_FILE = "kokoro-v1_0.pth"
MODEL_SHA256 = "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4"
VOICES = {
    "A": ("bf_emma", "voices/bf_emma.pt", "d0a423deabf4a52b4f49318c51742c54e21bb89bbbe9a12141e7758ddb5da701"),
    "B": ("bm_george", "voices/bm_george.pt", "f1bc812213dc59774769e5c80004b13eeb79bd78130b11b2d7f934542dab811b"),
    "C": ("bf_isabella", "voices/bf_isabella.pt", "cdd4c37003805104d1d08fb1e05855c8fb2c68de24ca6e71f264a30aaa59eefd"),
}
SAMPLE_RATE = 24_000
SPEED = 1.0
L01 = "CE-ST-M04-L01-AS-002"
EVENT = "localized_semantic_state_change"
EXPECTED_IDS = tuple(
    [f"CE-ST-M04-L{lesson:02d}-AS-{item:03d}" for lesson in range(1, 9) for item in (1, 2)]
    + [f"CE-ST-M04-MSN-AS-{item:03d}" for item in range(1, 5)]
)
PACKAGES = ("kokoro", "misaki", "huggingface_hub", "numpy", "soundfile", "torch")


class ContractError(ValueError):
    pass


def req(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def spoken_text(segments: list[dict[str, Any]]) -> str:
    return "\n".join(str(segment["text"]).strip() for segment in segments)


def validate_lock(lock: dict[str, Any]) -> None:
    req(lock.get("schema") == LOCK_SCHEMA, "dependency lock schema mismatch")
    packages = lock.get("packages")
    req(isinstance(packages, dict), "dependency lock packages must be an object")
    for name in PACKAGES:
        value = packages.get(name)
        req(isinstance(value, str) and value.strip() and value.strip().lower() not in {"unknown", "tbd"},
            f"missing exact package version: {name}")
        req(not any(token in value for token in (">", "<", "*", "~", "^", ",")),
            f"non-exact package version: {name}")
    req(packages["kokoro"] == KOKORO_VERSION, f"kokoro must be exactly {KOKORO_VERSION}")
    binaries = lock.get("binaries")
    req(isinstance(binaries, dict), "dependency lock binaries must be an object")
    for name in ("ffmpeg", "espeak-ng"):
        value = binaries.get(name)
        req(isinstance(value, str) and value.strip() and value.strip().lower() not in {"unknown", "tbd"},
            f"missing exact binary version: {name}")


def validate_contract(data: dict[str, Any]) -> None:
    exact = {
        "schema": SCHEMA,
        "source_drive_id": SOURCE_DRIVE_ID,
        "source_revision": SOURCE_REVISION,
        "preflight_drive_id": PREFLIGHT_DRIVE_ID,
        "preflight_revision": PREFLIGHT_REVISION,
        "production_class": "TTS",
        "locale": "en-GB",
        "kokoro_repo_id": KOKORO_REPO,
        "kokoro_hf_revision": KOKORO_REVISION,
        "kokoro_model_sha256": MODEL_SHA256,
    }
    for field, expected in exact.items():
        req(data.get(field) == expected, f"{field} mismatch/drift")
    req(float(data.get("speed", 0)) == SPEED, "normal-clear speed must be 1.0")
    validate_lock(data.get("dependency_lock") or {})

    scripts = data.get("scripts")
    req(isinstance(scripts, list) and len(scripts) == 20, "exactly 20 script objects required")
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    for script in scripts:
        req(isinstance(script, dict), "script must be an object")
        sid = str(script.get("script_id") or "")
        key = str(script.get("asset_key") or "")
        req(sid in EXPECTED_IDS and sid not in seen_ids, f"unexpected/duplicate script_id: {sid}")
        req(key and key not in seen_keys, f"blank/duplicate asset_key: {sid}")
        seen_ids.add(sid); seen_keys.add(key)
        req(script.get("source_text_revision") == SOURCE_REVISION, f"{sid}: source revision drift")
        req(script.get("protected") is False, f"{sid}: protected must be false")
        req(script.get("assessment_eligibility") in {"STUDY", "TRANSFER"}, f"{sid}: invalid assessment eligibility")
        req(script.get("normal_or_slow") == "NORMAL", f"{sid}: only NORMAL assets allowed")
        for field in ("rights_basis", "redistribution_status", "notice_or_attribution_pointer"):
            value = script.get(field)
            req(isinstance(value, str) and value.strip() and value.strip().upper() not in {"UNKNOWN", "TBD"},
                f"{sid}: {field} must be known")
        for field in ("target_ids", "listening_construct_ids"):
            values = script.get(field)
            req(isinstance(values, list) and all(isinstance(v, str) and v.strip() for v in values),
                f"{sid}: {field} must be a string list")

        segments = script.get("segments")
        req(isinstance(segments, list) and segments, f"{sid}: segments required")
        for index, segment in enumerate(segments):
            req(isinstance(segment, dict) and segment.get("index") == index, f"{sid}: bad segment index")
            req(segment.get("role") in VOICES, f"{sid}: role must be A/B/C")
            value = segment.get("text")
            req(isinstance(value, str) and value.strip() and "\n" not in value.strip(), f"{sid}: invalid segment text")
            pause = segment.get("pause_after_ms", 0 if index == len(segments) - 1 else 300)
            req(isinstance(pause, int) and 0 <= pause <= 1500, f"{sid}: invalid pause")
            event = segment.get("runtime_event_after")
            if event is not None:
                req(sid == L01 and event == EVENT and index < len(segments) - 1, f"{sid}: invalid runtime event")
        req(script.get("source_text_hash") == text_sha(spoken_text(segments)), f"{sid}: source_text_hash mismatch")
        if sid == L01:
            req(len(segments) == 2, f"{sid}: exactly two English segments required")
            req(segments[0].get("runtime_event_after") == EVENT and not segments[1].get("runtime_event_after"),
                f"{sid}: semantic interleave marker missing/misplaced")
        else:
            req(not any(s.get("runtime_event_after") for s in segments), f"{sid}: unexpected runtime event")
    req(seen_ids == set(EXPECTED_IDS), "script inventory incomplete")


def validate_runtime(lock: dict[str, Any]) -> dict[str, str]:
    validate_lock(lock)
    actual: dict[str, str] = {}
    for name in PACKAGES:
        try:
            actual[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ContractError(f"required package missing: {name}") from exc
        req(actual[name] == lock["packages"][name], f"installed {name}={actual[name]} != lock {lock['packages'][name]}")
    for binary, args in (("ffmpeg", ("-version",)), ("espeak-ng", ("--version",))):
        path = shutil.which(binary)
        req(bool(path), f"required binary missing: {binary}")
        result = subprocess.run([str(path), *args], capture_output=True, text=True, check=True)
        first = (result.stdout or result.stderr).splitlines()[0].strip()
        req(lock["binaries"][binary] in first, f"{binary} version does not match lock")
        actual[binary] = first
    return actual


def fetch_upstream(cache: Path) -> dict[str, Path]:
    from huggingface_hub import hf_hub_download
    specs = {
        "config": ("config.json", None),
        "model": (MODEL_FILE, MODEL_SHA256),
        **{f"voice_{role}": (filename, digest) for role, (_, filename, digest) in VOICES.items()},
    }
    found: dict[str, Path] = {}
    for key, (filename, expected) in specs.items():
        path = Path(hf_hub_download(repo_id=KOKORO_REPO, filename=filename, revision=KOKORO_REVISION, cache_dir=str(cache)))
        if expected:
            req(file_sha(path) == expected, f"upstream SHA mismatch: {filename}")
        found[key] = path
    return found


def render(pipeline: Any, text: str, voice: Path) -> Any:
    import numpy as np
    chunks = [np.asarray(result.audio, dtype=np.float32) for result in pipeline(text, voice=str(voice), speed=SPEED, split_pattern=None) if result.audio is not None]
    req(bool(chunks), f"TTS produced no audio for {text!r}")
    return np.concatenate(chunks)


def write_mp3(waveform: Any, destination: Path) -> None:
    import soundfile as sf
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "source.wav"
        sf.write(wav, waveform, SAMPLE_RATE, subtype="PCM_16")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav), "-ac", "1", "-ar", str(SAMPLE_RATE), "-b:a", "64k", str(destination)], check=True)


def produce(data: dict[str, Any], output: Path) -> dict[str, Any]:
    validate_contract(data)
    runtime = validate_runtime(data["dependency_lock"])
    import numpy as np
    from kokoro import KPipeline
    from kokoro.model import KModel

    output.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    pinned = fetch_upstream(output / ".hf-cache")
    model = KModel(repo_id=KOKORO_REPO, config=str(pinned["config"]), model=str(pinned["model"])).to("cpu").eval()
    pipeline = KPipeline(lang_code="b", repo_id=KOKORO_REPO, model=model, device="cpu")
    manifest: dict[str, Any] = {
        "schema": "worddeck-ce-st-m04-audio-batch-manifest-v1",
        "generator_id": GENERATOR,
        "source_drive_id": SOURCE_DRIVE_ID,
        "source_revision": SOURCE_REVISION,
        "preflight_drive_id": PREFLIGHT_DRIVE_ID,
        "preflight_revision": PREFLIGHT_REVISION,
        "production_class": "TTS",
        "provider": "hexgrad",
        "model": "Kokoro-82M",
        "model_version": "v1.0",
        "model_digest": MODEL_SHA256,
        "model_provider_licence_basis": "Apache-2.0",
        "kokoro_repo_id": KOKORO_REPO,
        "kokoro_hf_revision": KOKORO_REVISION,
        "kokoro_package_version": KOKORO_VERSION,
        "config_sha256": file_sha(pinned["config"]),
        "generation_date": generated_at,
        "production_method": GENERATOR,
        "locale": "en-GB",
        "speed": SPEED,
        "sample_rate": SAMPLE_RATE,
        "runtime_versions": runtime,
        "voices": {role: {"voice_id": voice_id, "sha256": digest} for role, (voice_id, _, digest) in VOICES.items()},
        "assets": [],
    }
    for script in data["scripts"]:
        pieces = []
        segments_out = []
        event_cues = []
        cursor = 0
        for segment in script["segments"]:
            role = segment["role"]
            audio = render(pipeline, segment["text"].strip(), pinned[f"voice_{role}"])
            start, end = cursor, cursor + len(audio)
            pieces.append(audio); cursor = end
            event = segment.get("runtime_event_after")
            if event:
                event_cues.append({"event": event, "after_segment_index": segment["index"], "sample_offset": end, "seconds": end / SAMPLE_RATE})
            pause_ms = segment.get("pause_after_ms", 0 if segment["index"] == len(script["segments"]) - 1 else 300)
            pause_samples = round(SAMPLE_RATE * pause_ms / 1000)
            if pause_samples:
                pieces.append(np.zeros(pause_samples, dtype=np.float32)); cursor += pause_samples
            voice_id, _, voice_sha = VOICES[role]
            segments_out.append({
                "index": segment["index"], "role": role, "voice_id": voice_id, "voice_sha256": voice_sha,
                "text_sha256": text_sha(segment["text"].strip()), "start_sample": start, "end_sample": end,
                "start_seconds": start / SAMPLE_RATE, "end_seconds": end / SAMPLE_RATE,
                "pause_after_ms": pause_ms, "runtime_event_after": event,
            })
        waveform = np.concatenate(pieces)
        destination = output / f"{script['asset_key']}.mp3"
        write_mp3(waveform, destination)
        roles = list(dict.fromkeys(segment["role"] for segment in script["segments"]))
        voice_ids = [VOICES[role][0] for role in roles]
        duration = len(waveform) / SAMPLE_RATE
        manifest["assets"].append({
            "script_id": script["script_id"], "asset_key": script["asset_key"],
            "source_text_revision": script["source_text_revision"], "source_text_hash": script["source_text_hash"],
            "voice_role": roles[0] if len(roles) == 1 else "+".join(roles), "voice_roles": roles,
            "provider_voice_id": voice_ids[0] if len(voice_ids) == 1 else "+".join(voice_ids), "provider_voice_ids": voice_ids,
            "production_class": "TTS", "provider": "hexgrad", "model": "Kokoro-82M", "model_version": "v1.0",
            "model_digest": MODEL_SHA256, "model_provider_licence_basis": "Apache-2.0",
            "generation_or_recording_date": generated_at, "production_method": GENERATOR,
            "locale": "en-GB", "accent_variety": "Standard British English", "scripted_status": "SCRIPTED",
            "normal_or_slow": "NORMAL", "target_ids": script["target_ids"], "listening_construct_ids": script["listening_construct_ids"],
            "assessment_eligibility": script["assessment_eligibility"], "protected": False,
            "codec": "mp3", "container": "mp3", "sample_rate": SAMPLE_RATE, "channels": 1,
            "duration": duration, "duration_seconds": duration, "bytes": destination.stat().st_size, "sha256": file_sha(destination),
            "rights_basis": script["rights_basis"], "redistribution_status": script["redistribution_status"],
            "notice_or_attribution_pointer": script["notice_or_attribution_pointer"],
            "segments": segments_out, "runtime_event_cues": event_cues,
            "qa_status": "NOT_REVIEWED", "transcript_match_status": "NOT_REVIEWED",
            "loudness_technical_qa": "NOT_REVIEWED", "accessibility_replay_semantics": "PENDING_RUNTIME_QA",
            "file": destination.name,
        })
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def selftest_contract() -> dict[str, Any]:
    scripts = []
    for i, sid in enumerate(EXPECTED_IDS):
        if sid == L01:
            segments = [
                {"index": 0, "role": "A", "text": "This is Noor.", "pause_after_ms": 300, "runtime_event_after": EVENT},
                {"index": 1, "role": "A", "text": "That is Noor.", "pause_after_ms": 0},
            ]
        else:
            segments = [{"index": 0, "role": ("A", "B", "C")[i % 3], "text": f"Synthetic self test {i + 1}.", "pause_after_ms": 0}]
        scripts.append({
            "script_id": sid, "asset_key": sid.lower(), "source_text_revision": SOURCE_REVISION,
            "source_text_hash": text_sha(spoken_text(segments)), "assessment_eligibility": "TRANSFER" if i % 3 == 2 else "STUDY",
            "protected": False, "normal_or_slow": "NORMAL", "target_ids": [f"CE-ST-M04-TL{(i % 17) + 1:03d}"],
            "listening_construct_ids": [f"CE-ST-M04-LISTEN-{(i % 8) + 1:02d}"],
            "rights_basis": "WORDDECK_ORIGINAL", "redistribution_status": "PROJECT_RELEASE_ELIGIBLE_PENDING_QA",
            "notice_or_attribution_pointer": "M04_AUDIO_PREFLIGHT", "segments": segments,
        })
    return {
        "schema": SCHEMA, "source_drive_id": SOURCE_DRIVE_ID, "source_revision": SOURCE_REVISION,
        "preflight_drive_id": PREFLIGHT_DRIVE_ID, "preflight_revision": PREFLIGHT_REVISION,
        "production_class": "TTS", "locale": "en-GB", "speed": SPEED,
        "kokoro_repo_id": KOKORO_REPO, "kokoro_hf_revision": KOKORO_REVISION, "kokoro_model_sha256": MODEL_SHA256,
        "dependency_lock": {"schema": LOCK_SCHEMA, "packages": {
            "kokoro": "0.9.4", "misaki": "0.9.4", "huggingface_hub": "0.34.4", "numpy": "2.2.6", "soundfile": "0.13.1", "torch": "2.8.0"
        }, "binaries": {"ffmpeg": "ffmpeg version 7.1.1", "espeak-ng": "eSpeak NG text-to-speech: 1.52.0"}},
        "scripts": scripts,
    }


def self_test() -> None:
    data = selftest_contract(); validate_contract(data)
    req({k: v[0] for k, v in VOICES.items()} == {"A": "bf_emma", "B": "bm_george", "C": "bf_isabella"}, "voice role freeze changed")
    mutations: list[tuple[str, dict[str, Any]]] = []
    def clone() -> dict[str, Any]: return json.loads(json.dumps(data))
    bad = clone(); bad["source_revision"] = "drift"; mutations.append(("source revision drift", bad))
    bad = clone(); bad["dependency_lock"]["packages"]["kokoro"] = ">=0.9.2"; mutations.append(("non-exact Kokoro pin", bad))
    bad = clone(); bad["scripts"][0]["segments"][0]["role"] = "UNKNOWN"; mutations.append(("unknown voice role", bad))
    bad = clone(); next(x for x in bad["scripts"] if x["script_id"] == L01)["segments"][0].pop("runtime_event_after"); mutations.append(("missing L01 event", bad))
    bad = clone(); bad["scripts"][1]["source_text_hash"] = "0" * 64; mutations.append(("source hash drift", bad))
    bad = clone(); bad["scripts"][2]["rights_basis"] = "TBD"; mutations.append(("unknown rights", bad))
    bad = clone(); bad["scripts"].pop(); mutations.append(("missing object", bad))
    for label, candidate in mutations:
        try: validate_contract(candidate)
        except ContractError: continue
        raise AssertionError(f"expected fail-closed rejection: {label}")
    print(f"SELF_TEST_PASS schema={SCHEMA} scripts=20 model_sha={MODEL_SHA256} voices=A:bf_emma,B:bm_george,C:bf_isabella")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--validate-only", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    req(sum(bool(v) for v in (args.self_test, args.validate_only, args.input)) == 1,
        "choose exactly one of --self-test, --validate-only FILE, or --input FILE")
    if args.self_test:
        self_test(); return 0
    source = args.validate_only or args.input
    assert source is not None
    data = json.loads(source.read_text(encoding="utf-8")); validate_contract(data)
    if args.validate_only:
        print(f"VALIDATION_PASS schema={SCHEMA} scripts={len(data['scripts'])} source_revision={SOURCE_REVISION}"); return 0
    req(args.output is not None, "--output DIR is required with --input")
    manifest = produce(data, args.output)
    print(f"PRODUCTION_COMPLETE assets={len(manifest['assets'])} manifest={args.output / 'manifest.json'} QA=NOT_REVIEWED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
