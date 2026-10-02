from __future__ import annotations

"""Windows playback adapter for profile-selected sound assets.

Classic semantic events continue to use the incumbent packaged resolver. Custom
packs resolve only through ``FilesystemSoundPackStore``'s integrity-checked
active-version boundary. This module owns no chess-event ordering or profile
persistence.
"""

import hashlib
import io
import logging
import os
from pathlib import Path
import struct
import sys
import tempfile
import wave

from .sound_events import SoundEvent
from .sound_pack_store import FilesystemSoundPackStore
from .sound_runtime import SoundAssetRequest
from .sound_windows import PackagedSoundAssetResolver


PROFILED_SCALED_SOUND_CACHE_FORMAT_VERSION = 1


class ProfiledWindowsSoundPlaybackAdapter:
    def __init__(
        self,
        packaged: PackagedSoundAssetResolver,
        installed: FilesystemSoundPackStore,
        *,
        cache_dir: str | Path,
        classic_pack_id: str = "classic",
        logger: logging.Logger | None = None,
    ) -> None:
        if not isinstance(packaged, PackagedSoundAssetResolver):
            raise TypeError("packaged must be PackagedSoundAssetResolver")
        if not isinstance(installed, FilesystemSoundPackStore):
            raise TypeError("installed must be FilesystemSoundPackStore")
        if not isinstance(classic_pack_id, str) or not classic_pack_id.strip():
            raise TypeError("classic_pack_id must be non-empty text")
        self._packaged = packaged
        self._installed = installed
        self._cache_dir = Path(cache_dir)
        self._classic = classic_pack_id.strip()
        self._logger = logger or logging.getLogger(__name__)

    def _classic_event(self, request: SoundAssetRequest) -> SoundEvent:
        if request.pack_id != self._classic:
            raise ValueError("request is not for the configured classic pack")
        if request.event_id == "low_time":
            if not request.preview:
                raise ValueError("classic low-time is preview-only until a distinct asset ships")
            if request.sound_id not in {"low_time", "tick"}:
                raise ValueError("classic low-time preview cannot select an arbitrary asset")
            return SoundEvent.TICK
        try:
            event = SoundEvent(request.event_id)
        except ValueError as exc:
            raise ValueError("classic pack does not own this sound event") from exc
        if request.sound_id != request.event_id:
            raise ValueError("classic pack sound_id must equal the semantic event id")
        return event

    def _resolve(self, request: SoundAssetRequest) -> tuple[Path, str]:
        if request.pack_id == self._classic:
            # Keep the shipped packaged manifest as the sole classic authority.
            event = self._classic_event(request)
            return self._packaged.resolve(event), f"classic-{event.value}"
        source = self._installed.resolve_asset(request.pack_id, request.sound_id)
        if source is None:
            raise FileNotFoundError("selected sound-pack asset is unavailable")
        if source.suffix.casefold() != ".wav":
            raise ValueError("Windows profile playback currently requires WAV assets")
        key = hashlib.sha256(
            f"{request.pack_id}\0{request.sound_id}".encode("utf-8")
        ).hexdigest()[:24]
        return source, f"custom-{key}"

    def play_sound(self, request: SoundAssetRequest) -> None:
        if not isinstance(request, SoundAssetRequest):
            raise TypeError("request must be SoundAssetRequest")
        if sys.platform != "win32":
            raise RuntimeError("profiled Windows sound playback requires win32")
        if request.volume == 0:
            return
        try:
            source, cache_key = self._resolve(request)
            playable = (
                source
                if request.volume == 100
                else self._scaled_copy(source, cache_key, request.volume)
            )
            import winsound

            winsound.PlaySound(
                str(playable),
                winsound.SND_FILENAME | winsound.SND_NODEFAULT,
            )
        except Exception as exc:
            self._logger.error(
                "profiled sound playback failed pack=%s event=%s error_type=%s",
                request.pack_id,
                request.event_id,
                type(exc).__name__,
            )
            raise

    def _scaled_copy(self, source: Path, cache_key: str, volume: int) -> Path:
        """Return an exact, content-addressed scaled WAV snapshot.

        Installed pack updates and release extraction may preserve or move mtimes
        backwards, so timestamp-based cache reuse can serve audio derived from old
        bytes. Read the source exactly once, bind cache identity to those bytes and
        publish the derived WAV atomically.
        """

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        source_bytes = source.read_bytes()
        source_digest = hashlib.sha256(source_bytes).hexdigest()
        destination = self._cache_dir / (
            f"{cache_key}-v{volume}-s{PROFILED_SCALED_SOUND_CACHE_FORMAT_VERSION}-"
            f"{source_digest}.wav"
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
            self._prune_scaled_variants(destination, cache_key, volume)
            return destination

        descriptor, temporary_name = tempfile.mkstemp(
            dir=self._cache_dir,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        os.close(descriptor)
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
            except OSError as exc:
                self._logger.warning(
                    "could not remove temporary profiled sound cache file error_type=%s",
                    type(exc).__name__,
                )

        self._prune_scaled_variants(destination, cache_key, volume)
        return destination

    @staticmethod
    def _cached_scaled_wave_is_valid(
        destination: Path,
        expected_params,
        expected_frames: bytes,
    ) -> bool:
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
        cache_key: str,
        volume: int,
    ) -> None:
        legacy = self._cache_dir / f"{cache_key}-v{volume}.wav"
        pattern = f"{cache_key}-v{volume}-*.wav"
        for candidate in (legacy, *self._cache_dir.glob(pattern)):
            if candidate == destination:
                continue
            try:
                candidate.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                self._logger.warning(
                    "could not prune stale profiled sound cache file error_type=%s",
                    type(exc).__name__,
                )


__all__ = ["ProfiledWindowsSoundPlaybackAdapter"]
