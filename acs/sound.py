from __future__ import annotations

"""Compatibility sound facade backed only by packaged user-selected WAV assets.

The former procedural generator was intentionally removed.  This module never
creates replacement sounds and never falls back to a Windows system beep.
"""

import sys
from pathlib import Path

from .sound_events import SoundEvent
from .sound_windows import PackagedSoundAssetResolver, WindowsSoundPlaybackAdapter


class SoundManager:
    """Legacy-compatible facade over the canonical packaged sound runtime."""

    def __init__(self, root, enabled=True, volume=80):
        self.root = Path(root)
        self.enabled = bool(enabled)
        self.volume = max(0, min(100, int(volume)))
        self._playback = WindowsSoundPlaybackAdapter(
            PackagedSoundAssetResolver(self.root),
            cache_dir=self.root / "sound-cache",
        )

    def configure(self, enabled=None, volume=None):
        if enabled is not None:
            self.enabled = bool(enabled)
        if volume is not None:
            self.volume = max(0, min(100, int(volume)))

    def play(self, kind):
        if not self.enabled or self.volume <= 0 or sys.platform != "win32":
            return
        try:
            event = kind if isinstance(kind, SoundEvent) else SoundEvent(str(kind))
            self._playback.play(event, volume=self.volume)
        except Exception:
            # Sound failure must never mutate chess state or trigger a system beep.
            return
