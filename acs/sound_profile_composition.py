from __future__ import annotations

"""Concrete local composition for durable profile-driven sound behavior.

This module bridges the already-qualified profile/storage/runtime primitives into
one object the shipping V2 composition can own. It deliberately does not create
a remote sound-pack catalog or downloader. Installed custom packs are resolved
from the existing integrity-checked local store; absent/invalid selections fall
back to the packaged ``classic`` authority.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
import os
from pathlib import Path
from typing import Any

from .classroom_sound import ClassroomSoundRuntime
from .sound_events import SoundEvent
from .sound_pack_catalog import (
    MAX_SOUND_PACK_CATALOG_ENTRIES,
    SoundPackCatalogEntry,
    SoundPackDownloadPort,
    SoundPackInstallError,
    SoundPackInstalledAudit,
    SoundPackManager,
    SoundPackSignatureVerifier,
)
from .sound_pack_profile import SoundPackProfileCoordinator
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
    pack_coordinator: SoundPackProfileCoordinator
    profiled_runtime: ProfiledSoundRuntime
    game_runtime: GameSoundRuntime
    classroom_runtime: ClassroomSoundRuntime
    settings: SoundSettingsApplication


class _UnavailableSoundPackDownloader:
    """Fail closed when no optional provider deployment is configured."""

    def download(self, entry: SoundPackCatalogEntry, *, max_bytes: int):
        del entry, max_bytes
        raise SoundPackInstallError("sound pack download provider is unavailable")


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
            try:
                event = SoundEvent("low_time")
            except ValueError:
                # Until the packaged-sound owner lands in the current Product
                # base, retain the diagnostic preview-only Tick bridge. Once
                # low_time exists canonically, use that event directly.
                if not request.preview:
                    raise ValueError(
                        "classic low-time is preview-only until the packaged sound "
                        "authority exposes a distinct low_time event"
                    )
                event = SoundEvent.TICK
            else:
                if request.sound_id != "low_time":
                    raise ValueError(
                        "legacy injected low-time playback requires low_time sound id"
                    )
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


def _installed_pack_inventory(
    store: FilesystemSoundPackStore,
) -> dict[str, SoundPackManifest]:
    try:
        installed = store.installed()
    except Exception:
        # Custom packs are optional. The resolver independently reconciles an
        # unreadable selected pack to classic, so inventory failure must not
        # make the whole shipping application unavailable.
        return {}
    return dict(installed)


def _installed_pack_audit(
    store: FilesystemSoundPackStore,
) -> dict[str, SoundPackInstalledAudit]:
    try:
        return dict(store.installed_audit())
    except Exception:
        # Custom packs are optional. Preserve classic startup/settings even when
        # the local custom-pack inventory is temporarily unreadable.
        return {}


def _playable_installed_packs(
    store: FilesystemSoundPackStore,
) -> dict[str, SoundPackManifest]:
    return {
        pack_id: manifest
        for pack_id, manifest in _installed_pack_inventory(store).items()
        if _windows_pack_is_playable(manifest)
    }


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


def _provider_catalog(
    catalog: Mapping[str, SoundPackCatalogEntry] | None,
) -> dict[str, SoundPackCatalogEntry]:
    if catalog is None:
        return {}
    if not isinstance(catalog, Mapping):
        raise TypeError("sound pack catalog must be a mapping or None")
    if len(catalog) > MAX_SOUND_PACK_CATALOG_ENTRIES:
        raise ValueError("sound pack catalog exceeds the resource limit")
    normalized: dict[str, SoundPackCatalogEntry] = {}
    for pack_id, entry in catalog.items():
        if type(pack_id) is not str or not isinstance(entry, SoundPackCatalogEntry):
            raise TypeError(
                "sound pack catalog must map text ids to SoundPackCatalogEntry"
            )
        if pack_id != entry.manifest.pack_id:
            raise ValueError("sound pack catalog key must match manifest pack_id")
        if pack_id == "classic":
            raise ValueError("provider catalog cannot replace the packaged classic authority")
        if not _windows_pack_is_playable(entry.manifest) and entry.compatible:
            entry = replace(entry, compatible=False)
        normalized[pack_id] = entry
    return normalized


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
    catalog: Mapping[str, SoundPackCatalogEntry] | None = None,
    pack_downloader: SoundPackDownloadPort | None = None,
    signature_verifier: SoundPackSignatureVerifier | None = None,
) -> LocalSoundComposition:
    """Create one durable local sound composition for the shipping application.

    ``legacy_settings`` is consulted only when ``sound-profile.json`` does not
    yet exist. This preserves Stage1 ``sounds``/``volume`` choices on first V2
    profile migration without keeping two writable settings authorities.
    """

    normalized_catalog = _provider_catalog(catalog)
    if normalized_catalog and pack_downloader is None:
        raise ValueError("sound pack catalog requires a download provider")
    if pack_downloader is not None and (
        isinstance(pack_downloader, type)
        or not callable(getattr(pack_downloader, "download", None))
    ):
        raise TypeError("pack_downloader must expose download() or be None")
    if signature_verifier is not None and (
        isinstance(signature_verifier, type)
        or not callable(getattr(signature_verifier, "verify", None))
    ):
        raise TypeError("signature_verifier must expose verify() or be None")

    app_dir = Path(application_dir)
    root = Path(data_root)
    profile_path = root / "sound-profile.json"
    packs_root = root / "sound-packs"
    cache_root = root / "sound-cache"

    profile_storage = JsonSoundProfileStorage(profile_path)
    pack_store = FilesystemSoundPackStore(packs_root)

    # Parse legacy state before materializing any new profile file. Otherwise a
    # malformed legacy payload could leave a default sound-profile.json behind,
    # causing the next startup to treat migration as already completed.
    profile_preexisted = os.path.lexists(profile_path)
    migrated = None if profile_preexisted else _legacy_profile(legacy_settings)
    profile_manager = SoundProfileManager(
        profile_storage,
        _local_pack_resolver(pack_store),
        default_profile=migrated,
    )
    profile_manager.load()

    pack_manager = SoundPackManager(
        pack_downloader if pack_downloader is not None else _UnavailableSoundPackDownloader(),
        pack_store,
        signature_verifier=signature_verifier,
        external_fallback_available=True,
    )
    pack_coordinator = SoundPackProfileCoordinator(pack_manager, profile_manager)

    playback = _asset_playback(
        asset_playback,
        application_dir=app_dir,
        pack_store=pack_store,
        cache_root=cache_root,
    )
    profiled = ProfiledSoundRuntime(playback, profile_manager.profile_provider)
    game = GameSoundRuntime(profiled)
    classroom = ClassroomSoundRuntime(playback, profile_manager.profile_provider)
    settings = SoundSettingsApplication(
        profile_manager,
        profiled,
        pack_coordinator=pack_coordinator,
        catalog=normalized_catalog,
        installed_audit_provider=lambda: _installed_pack_audit(pack_store),
        pack_compatibility_provider=_windows_pack_is_playable,
    )
    settings.reconcile_active_profile()
    return LocalSoundComposition(
        profile_manager=profile_manager,
        pack_store=pack_store,
        pack_coordinator=pack_coordinator,
        profiled_runtime=profiled,
        game_runtime=game,
        classroom_runtime=classroom,
        settings=settings,
    )


__all__ = ["LocalSoundComposition", "create_local_sound_composition"]
