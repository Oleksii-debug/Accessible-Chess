from __future__ import annotations

"""Windows infrastructure adapter for packaged Accessible Chess sound assets.

This module is intentionally outside chess/domain contracts. It owns filesystem
layout, WAV scaling/cache and ``winsound`` usage. Worker 4 packages the assets and
runs the real Windows smoke; Core only defines the exact contract.
"""

import hashlib
import io
import json
import logging
import os
import struct
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

from .sound_events import SoundEvent


SOUND_MANIFEST_SCHEMA_VERSION = 1
DEFAULT_SOUND_RELATIVE_DIR = Path("assets") / "sounds"
DEFAULT_SOUND_MANIFEST = "manifest.json"
REQUIRED_SOUND_EVENTS = tuple(SoundEvent)
SCALED_SOUND_CACHE_FORMAT_VERSION = 1


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

            # PlaySound is synchronous unless SND_ASYNC is requested. Avoid
            # SND_SYNC because Python only exposes that alias from 3.14 onward;
            # the packaged Windows runtime still supports Python 3.12.
            winsound.PlaySound(
                str(playable),
                winsound.SND_FILENAME | winsound.SND_NODEFAULT,
            )
        except Exception:
            self._logger.exception("chess sound playback failed for event=%s", event.value)
            raise

    def _scaled_copy(self, source: Path, event: SoundEvent, volume: int) -> Path:
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # Cache identity must follow the actual packaged bytes, not filesystem
        # timestamps. Release extraction, pack replacement and restore can
        # legitimately preserve or move mtimes backwards.
        source_bytes = source.read_bytes()
        source_digest = hashlib.sha256(source_bytes).hexdigest()
        destination = self._cache_dir / (
            f"{event.value}-v{volume}-s{SCALED_SOUND_CACHE_FORMAT_VERSION}-{source_digest}.wav"
        )
        with wave.open(io.BytesIO(source_bytes), "rb") as reader:
            params = reader.getparams()
            if params.sampwidth != 2:
                raise ValueError("only 16-bit PCM WAV assets support volume scaling")
            frames = reader.readframes(reader.getnframes())
        expected_frame_bytes = params.nframes * params.nchannels * params.sampwidth
        if len(frames) != expected_frame_bytes:
            raise ValueError("truncated 16-bit PCM WAV asset")

        samples = struct.unpack("<" + "h" * (len(frames) // 2), frames)
        factor = volume / 100.0
        scaled = b"".join(
            struct.pack("<h", max(-32768, min(32767, int(sample * factor))))
            for sample in samples
        )
        if destination.is_file() and self._cached_scaled_wave_is_valid(
            destination,
            params,
            scaled,
        ):
            self._prune_scaled_variants(destination, event, volume)
            return destination
        fd, temporary_name = tempfile.mkstemp(
            dir=self._cache_dir,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with wave.open(str(temporary), "wb") as writer:
                writer.setparams(params)
                writer.writeframes(scaled)
            os.replace(temporary, destination)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                # Temporary-cache cleanup is housekeeping. In particular, a
                # short Windows file lock must not replace the primary scaling
                # or publication exception with a less useful cleanup error.
                self._logger.warning(
                    "could not remove temporary chess sound cache file: %s",
                    temporary,
                    exc_info=True,
                )
        self._prune_scaled_variants(destination, event, volume)
        return destination

    @staticmethod
    def _cached_scaled_wave_is_valid(
        destination: Path,
        expected_params,
        expected_frames: bytes,
    ) -> bool:
        """Return whether an existing derived WAV exactly matches this transform."""

        try:
            with wave.open(str(destination), "rb") as reader:
                params = reader.getparams()
                if params != expected_params:
                    return False
                frames = reader.readframes(reader.getnframes())
        except (EOFError, OSError, ValueError, struct.error, wave.Error):
            return False
        return frames == expected_frames

    def _prune_scaled_variants(
        self,
        destination: Path,
        event: SoundEvent,
        volume: int,
    ) -> None:
        """Best-effort removal of superseded content-addressed cache variants."""

        # Remove the pre-content-addressed cache name as well as obsolete
        # digest/schema variants. The schema component makes future changes to
        # the scaling transform invalidate old derived audio deterministically.
        legacy = self._cache_dir / f"{event.value}-v{volume}.wav"
        pattern = f"{event.value}-v{volume}-*.wav"
        for candidate in (legacy, *self._cache_dir.glob(pattern)):
            if candidate == destination:
                continue
            try:
                candidate.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                # Cache housekeeping must never turn successful playback into a
                # product failure. The stale entry can be retried next time.
                self._logger.warning(
                    "could not prune stale chess sound cache file: %s",
                    candidate,
                    exc_info=True,
                )
