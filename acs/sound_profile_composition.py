from __future__ import annotations

"""Concrete local composition for durable profile-driven sound behavior.

This module bridges the already-qualified profile/storage/runtime primitives into
one object the shipping V2 composition can own. It deliberately does not create
a remote sound-pack catalog or downloader. Installed custom packs are resolved
from the existing integrity-checked local store; absent/invalid selections fall
back to the packaged ``classic`` authority.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from .sound_events import SoundEvent
from .sound_pack_store import FilesystemSoundPackStore
from .sound_profile_file_store import JsonSoundProfileStorage
from .sound_profile_store import SoundProfileManager
from .sound_profiles import SoundPackManifest, SoundProfile
from .sound_profile_windows import ProfiledWindowsSoundPlaybackAdapter
from .sound_runtime import (
    GameSoundRuntime,
    ProfiledSoundRuntime,
    SoundAssetPlaybackPort,
    SoundAssetRequest,
    SoundPlaybackPort,
)
from .sound_settings_application import SoundSettingsApplication
from .sound_windows import PackagedSoundAssetResolver


@dataclass(frozen=True)
class LocalSoundComposition:
    profile_manager: SoundProfileManager
    pack_store: FilesystemSoundPackStore
    profiled_runtime: ProfiledSoundRuntime
    game_runtime: GameSoundRuntime
    settings: SoundSettingsApplication


class _InjectedClassicPlaybackBridge:
    """Adapt the retained Stage-1 injection seam to profile asset requests.

    Production never uses this bridge; the default path owns the profiled Windows
    adapter. This trusted diagnostic/test boundary permits classic semantic events
    only, so it cannot become a second custom-pack playback authority.
    """

    def __init__(self, playback: Any) -> None:
        play = getattr(playback, "play", None)
        if not callable(play):
            raise TypeError("injected sound playback must expose play_sound() or play()")
        self._playback = playback

    def play_sound(self, request: SoundAssetRequest) -> None:
        if not isinstance(request, SoundAssetRequest):
            raise TypeError("request must be SoundAssetRequest")
        if request.pack_id != "classic":
            raise ValueError("legacy injected playback supports only the classic pack")
        if request.event_id == "low_time":
            if not request.preview:
                raise ValueError("classic low-time is preview-only")
            event = SoundEvent.TICK
        else:
            try:
                event = SoundEvent(request.event_id)
            except ValueError as exc:
                raise ValueError("unknown classic sound event") from exc
            if request.sound_id != request.event_id:
                raise ValueError("legacy injected playback cannot remap classic sound ids")
        self._playback.play(event, volume=request.volume)


def _asset_playback(
    playback: SoundAssetPlaybackPort | SoundPlaybackPort | None,
    *,
    application_dir: Path,
    pack_store: FilesystemSoundPackStore,
    cache_root: Path,
) -> SoundAssetPlaybackPort:
    if playback is None:
        return ProfiledWindowsSoundPlaybackAdapter(
            PackagedSoundAssetResolver(application_dir),
            pack_store,
            cache_dir=cache_root,
        )
    if callable(getattr(playback, "play_sound", None)):
        return playback
    return _InjectedClassicPlaybackBridge(playback)


def _windows_pack_is_playable(manifest: object) -> bool:
    """Whether every declared custom asset is playable by the shipping adapter."""

    if not isinstance(manifest, SoundPackManifest):
        return False
    return all(
        Path(relative).suffix.casefold() == ".wav"
        for relative in manifest.files.values()
    )


def _local_pack_resolver(store: FilesystemSoundPackStore):
    def resolve(pack_id: str) -> str:
        if pack_id == "classic":
            return "classic"
        try:
            manifest = store.installed().get(pack_id)
        except Exception:
            return "classic"
        # The current Windows playback adapter intentionally accepts WAV only.
        # Reconcile an incompatible persisted selection before runtime dispatch
        # instead of accepting a pack that can fail every semantic event later.
        return pack_id if _windows_pack_is_playable(manifest) else "classic"

    return resolve


def _legacy_profile(settings: Mapping[str, object] | None) -> SoundProfile | None:
    if settings is None:
        return None
    if not isinstance(settings, Mapping):
        raise TypeError("legacy sound settings must be a mapping or None")
    if "sounds" not in settings and "volume" not in settings:
        return None
    raw: dict[str, object] = {}
    if "sounds" in settings:
        raw["sounds"] = settings["sounds"]
    if "volume" in settings:
        raw["volume"] = settings["volume"]
    return SoundProfile.from_mapping(raw)


def create_local_sound_composition(
    *,
    application_dir: str | os.PathLike[str],
    data_root: str | os.PathLike[str],
    legacy_settings: Mapping[str, object] | None = None,
    asset_playback: SoundAssetPlaybackPort | SoundPlaybackPort | None = None,
) -> LocalSoundComposition:
    """Create one durable local sound composition for the shipping application.

    ``legacy_settings`` is consulted only when ``sound-profile.json`` does not
    yet exist. This preserves Stage1 ``sounds``/``volume`` choices on first V2
    profile migration without keeping two writable settings authorities.
    """

    app_dir = Path(application_dir)
    root = Path(data_root)
    profile_path = root / "sound-profile.json"
    packs_root = root / "sound-packs"
    cache_root = root / "sound-cache"

    profile_storage = JsonSoundProfileStorage(profile_path)
    pack_store = FilesystemSoundPackStore(packs_root)
    profile_manager = SoundProfileManager(
        profile_storage,
        _local_pack_resolver(pack_store),
    )

    profile_preexisted = os.path.lexists(profile_path)
    profile_manager.load()
    if not profile_preexisted:
        migrated = _legacy_profile(legacy_settings)
        if migrated is not None:
            profile_manager.save(migrated)

    playback = _asset_playback(
        asset_playback,
        application_dir=app_dir,
        pack_store=pack_store,
        cache_root=cache_root,
    )
    profiled = ProfiledSoundRuntime(playback, profile_manager.profile_provider)
    game = GameSoundRuntime(profiled)
    settings = SoundSettingsApplication(profile_manager, profiled)
    return LocalSoundComposition(
        profile_manager=profile_manager,
        pack_store=pack_store,
        profiled_runtime=profiled,
        game_runtime=game,
        settings=settings,
    )


__all__ = ["LocalSoundComposition", "create_local_sound_composition"]
