"""Validate owner WAV bytes and real gameplay delivery; --native requires Windows.

The default mode observes the final PlaySound port without claiming audible output.
No user sound bytes are changed or copied into the repository.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import wave

from acs.sound_events import SoundEvent
from acs.sound_windows import PackagedSoundAssetResolver, WindowsSoundPlaybackAdapter
from acs.version2_upgrade_status_release import create_version2_release_application
from tests.test_stage1_release_composition_ui import _FakeRuntime


def probe(sound_root: Path, *, native: bool = False) -> dict:
    if native and sys.platform != "win32":
        raise RuntimeError("Native playback requires Windows")
    inventory = json.loads((sound_root / "inventory.json").read_text(encoding="utf-8"))
    silent_sources = []
    for item in inventory["files"]:
        path = sound_root / item["file"]
        data = path.read_bytes()
        if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise RuntimeError("Owner sound bytes differ: " + item["file"])
        with wave.open(str(path)) as wav:
            data = wav.readframes(wav.getnframes())
            if not data or wav.getcomptype() != "NONE":
                raise RuntimeError("Invalid PCM: " + item["file"])
            silent = all(v == 128 for v in data) if wav.getsampwidth() == 1 else not any(data)
        if silent:
            silent_sources.append(item["file"])
    if len(inventory["files"]) != 330:
        raise RuntimeError("Expected the exact 330-WAV owner inventory")
    if native:
        import winsound
        native_play = winsound.PlaySound
    else:
        native_play = None
    with tempfile.TemporaryDirectory(prefix="owner-audio-") as temporary:
        root = Path(temporary)
        shutil.copytree(sound_root, root / "assets" / "sounds")
        calls = []
        def observe(filename, flags):
            if filename is None:
                return
            with wave.open(str(filename)) as wav:
                pcm = wav.readframes(wav.getnframes())
                if not pcm:
                    raise RuntimeError("Empty delivered PCM")
                silent = all(v == 128 for v in pcm) if wav.getsampwidth() == 1 else not any(pcm)
            calls.append({"file": Path(filename).name, "flags": flags, "silent": silent})
            if native_play is not None:
                native_play(filename, flags)
        port = SimpleNamespace(SND_FILENAME=0x20000, SND_NODEFAULT=2, SND_ASYNC=1, PlaySound=observe)
        with patch.dict(sys.modules, {"winsound": port}), patch("acs.sound_windows.sys", SimpleNamespace(platform="win32")):
            resolver = PackagedSoundAssetResolver(root)
            selected = {event: "1" for event in SoundEvent}
            adapter = WindowsSoundPlaybackAdapter(resolver, cache_dir=root / "cache", variant_provider=lambda event: selected[event])
            variant_count = 0
            for event in SoundEvent:
                for variant in resolver.variants_for(event):
                    selected[event] = variant.variant_id
                    adapter.play(event, volume=80)
                    variant_count += 1
            variant_calls = len(calls)
            api = app = runtime = None
            try:
                api, app, runtime, _ = create_version2_release_application(application_dir=root, data_root=root / "data", runtime_factory=_FakeRuntime)
                if not api.new_game()["ok"]:
                    raise RuntimeError("New game failed")
                for move in ("e4", "e5", "nf3"):
                    if not api.make_move(move)["ok"]:
                        raise RuntimeError("Move failed: " + move)
                gameplay = calls[variant_calls:]
                if len(gameplay) < 4 or any(call["silent"] for call in gameplay):
                    raise RuntimeError("Gameplay did not deliver non-silent PCM")
            finally:
                if app is not None: app.shutdown()
                if api is not None: api.close_analysis()
                if runtime is not None: runtime.close()
        return {"source_wavs_verified": 330, "silent_source_files": silent_sources, "events": len(list(SoundEvent)), "variants_exercised": variant_count, "variant_playback_calls": variant_calls, "gameplay_calls": gameplay, "native_api_called": native, "audible_windows_verified": False, "human_tested": False, "nvda_verified": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sound_root", type=Path)
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    print(json.dumps(probe(args.sound_root, native=args.native), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
