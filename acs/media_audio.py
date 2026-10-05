from __future__ import annotations

"""Small provider-neutral audio primitives reused from Nika-Core.

Donor:
Oleksii-debug/Nika-Core@main
src/nika_core/media/audio.py blob 2a305f0d0edbf9c6a99d0eaac11e1dd9c5d1ca50

Only dependency-free WAV inspection is ported here. The Nika ffmpeg process
wrapper is intentionally not copied because Accessible Chess must own its own
media/process and provider-compliance boundaries.
"""

import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AudioInspectionPolicy:
    max_frames: int = 16_000 * 60 * 10
    silence_peak_threshold: int = 8

    def __post_init__(self) -> None:
        if type(self.max_frames) is not int or self.max_frames <= 0:
            raise ValueError("max_frames must be a positive integer")
        if type(self.silence_peak_threshold) is not int or self.silence_peak_threshold < 0:
            raise ValueError("silence_peak_threshold must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class WavInspection:
    sample_rate_hz: int
    channels: int
    frames: int
    duration_ms: int
    peak_pcm16: int

    @property
    def is_empty(self) -> bool:
        return self.frames == 0

    def is_silent(self, *, peak_threshold: int = 8) -> bool:
        if type(peak_threshold) is not int or peak_threshold < 0:
            raise ValueError("peak_threshold must be a non-negative integer")
        return self.frames == 0 or self.peak_pcm16 <= peak_threshold


def inspect_pcm16_wav(
    path: str | Path,
    *,
    policy: AudioInspectionPolicy | None = None,
) -> WavInspection:
    """Inspect bounded mono/stereo PCM16 WAV without decoding dependencies."""

    selected = policy or AudioInspectionPolicy()
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("WAV path must be a file")
    with wave.open(str(resolved), "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        sample_rate = handle.getframerate()
        frames = handle.getnframes()
        if channels not in {1, 2} or sample_width != 2 or sample_rate <= 0:
            raise ValueError("expected mono/stereo PCM16 WAV with a positive sample rate")
        if frames > selected.max_frames:
            raise ValueError("WAV inspection frame limit exceeded")
        raw = handle.readframes(frames)

    peak = 0
    for offset in range(0, len(raw) - 1, 2):
        sample = int.from_bytes(raw[offset : offset + 2], "little", signed=True)
        peak = max(peak, abs(sample))

    return WavInspection(
        sample_rate_hz=sample_rate,
        channels=channels,
        frames=frames,
        duration_ms=round(frames / sample_rate * 1000),
        peak_pcm16=peak,
    )


__all__ = ["AudioInspectionPolicy", "WavInspection", "inspect_pcm16_wav"]
