from __future__ import annotations

"""Windows infrastructure adapter for packaged Accessible Chess sound assets.

This module is intentionally outside chess/domain contracts. It owns filesystem
layout, WAV scaling/cache and ``winsound`` usage. Worker 4 packages the assets and
runs the real Windows smoke; Core only defines the exact contract.
"""

import json
import logging
import struct
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

from .sound_events import SoundEvent


SOUND_MANIFEST_SCHEMA_VERSION = 1
DEFAULT_SOUND_RELATIVE_DIR = Path("assets") / "sounds"
DEFAULT_SOUND_MANIFEST = "manifest.json"
REQUIRED_SOUND_EVENTS = tuple(SoundEvent)


@dataclass(frozen=True)
class PackagedSoundManifest:
    root: Path
    files: dict[SoundEvent, Path]


class PackagedSoundAssetResolver:
    """Resolve immutable packaged sound assets from an application directory.

    Packaging contract:
      <application_dir>/assets/sounds/manifest.json
      <application_dir>/assets/sounds/<declared wav files>

    The manifest is JSON schema 1:
      {"schema_version": 1, "files": {"move": "move.wav", ...}}
    Every ``SoundEvent`` including ``tick`` is mandatory. Missing or unsafe paths
    are explicit errors; there is no generated/system-sound fallback.
    """

    def __init__(self, application_dir: str | Path) -> None:
        self.application_dir = Path(application_dir)
        self.root = self.application_dir / DEFAULT_SOUND_RELATIVE_DIR

    def load_manifest(self) -> PackagedSoundManifest:
        manifest_path = self.root / DEFAULT_SOUND_MANIFEST
        if not manifest_path.is_file():
            raise FileNotFoundError(f"sound manifest missing: {manifest_path}")
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != SOUND_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported sound manifest schema")
        mapping = raw.get("files")
        if not isinstance(mapping, dict):
            raise ValueError("sound manifest files must be an object")

        files: dict[SoundEvent, Path] = {}
        for event in REQUIRED_SOUND_EVENTS:
            value = mapping.get(event.value)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"sound manifest missing event: {event.value}")
            relative = Path(value)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"unsafe sound asset path for {event.value}")
            path = (self.root / relative).resolve()
            root = self.root.resolve()
            if root not in path.parents and path != root:
                raise ValueError(f"sound asset escapes packaged root: {event.value}")
            if path.suffix.casefold() != ".wav":
                raise ValueError(f"sound asset must be WAV: {event.value}")
            if not path.is_file():
                raise FileNotFoundError(f"sound asset missing for {event.value}: {path}")
            files[event] = path
        return PackagedSoundManifest(self.root, files)

    def resolve(self, event: SoundEvent) -> Path:
        return self.load_manifest().files[event]


class WindowsSoundPlaybackAdapter:
    """Synchronous Windows WAV player implementing ``SoundPlaybackPort``.

    ``SND_NODEFAULT`` is mandatory: a missing/broken file must raise/log, never
    become a Windows system beep. Partial volume is implemented by scaling into a
    writable cache directory; packaged assets remain immutable.
    """

    def __init__(
        self,
        resolver: PackagedSoundAssetResolver,
        *,
        cache_dir: str | Path,
        logger: logging.Logger | None = None,
    ) -> None:
        self._resolver = resolver
        self._cache_dir = Path(cache_dir)
        self._logger = logger or logging.getLogger(__name__)

    def play(self, event: SoundEvent, *, volume: int) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows sound playback adapter requires win32")
        if isinstance(volume, bool) or not isinstance(volume, int) or not 0 <= volume <= 100:
            raise ValueError("volume must be in 0..100")
        if volume == 0:
            return

        try:
            source = self._resolver.resolve(event)
            playable = source if volume == 100 else self._scaled_copy(source, event, volume)
            import winsound

            winsound.PlaySound(
                str(playable),
                winsound.SND_FILENAME | winsound.SND_SYNC | winsound.SND_NODEFAULT,
            )
        except Exception:
            self._logger.exception("chess sound playback failed for event=%s", event.value)
            raise

    def _scaled_copy(self, source: Path, event: SoundEvent, volume: int) -> Path:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        destination = self._cache_dir / f"{event.value}-v{volume}.wav"
        if destination.is_file() and destination.stat().st_mtime_ns >= source.stat().st_mtime_ns:
            return destination

        with wave.open(str(source), "rb") as reader:
            params = reader.getparams()
            if params.sampwidth != 2:
                raise ValueError("only 16-bit PCM WAV assets support volume scaling")
            frames = reader.readframes(reader.getnframes())

        samples = struct.unpack("<" + "h" * (len(frames) // 2), frames)
        factor = volume / 100.0
        scaled = b"".join(
            struct.pack("<h", max(-32768, min(32767, int(sample * factor))))
            for sample in samples
        )
        with wave.open(str(destination), "wb") as writer:
            writer.setparams(params)
            writer.writeframes(scaled)
        return destination
