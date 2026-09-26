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

from .sound_pack_store import FilesystemSoundPackStore
from .sound_profile_file_store import JsonSoundProfileStorage
from .sound_profile_store import SoundProfileManager
from .sound_profiles import SoundProfile
from .sound_profile_windows import ProfiledWindowsSoundPlaybackAdapter
from .sound_runtime import GameSoundRuntime, ProfiledSoundRuntime, SoundAssetPlaybackPort
from .sound_settings_application import SoundSettingsApplication
from .sound_windows import PackagedSoundAssetResolver


@dataclass(frozen=True)
class LocalSoundComposition:
    profile_manager: SoundProfileManager
    pack_store: FilesystemSoundPackStore
    profiled_runtime: ProfiledSoundRuntime
    game_runtime: GameSoundRuntime
    settings: SoundSettingsApplication


def _local_pack_resolver(store: FilesystemSoundPackStore):
    def resolve(pack_id: str) -> str:
        if pack_id == "classic":
            return "classic"
        try:
            installed = store.installed()
        except Exception:
            return "classic"
        return pack_id if pack_id in installed else "classic"

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
    asset_playback: SoundAssetPlaybackPort | None = None,
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

    playback = asset_playback
    if playback is None:
        playback = ProfiledWindowsSoundPlaybackAdapter(
            PackagedSoundAssetResolver(app_dir),
            pack_store,
            cache_dir=cache_root,
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
