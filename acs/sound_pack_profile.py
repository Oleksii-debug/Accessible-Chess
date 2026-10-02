from __future__ import annotations

"""Application-level coordination between sound-pack lifecycle and SoundProfile.

The coordinator owns no filesystem, network, playback, Windows or chess-event
policy. It only sequences existing neutral managers so persisted profile state
cannot be left pointing at assets that were removed.
"""

from dataclasses import dataclass, replace

from .sound_pack_catalog import (
    SoundPackCatalogEntry,
    SoundPackCatalogStatus,
    SoundPackManager,
)
from .sound_profile_store import SoundProfileManager
from .sound_profiles import SoundPackManifest, SoundProfile


@dataclass(frozen=True)
class SoundPackProfileInstallResult:
    manifest: SoundPackManifest
    profile: SoundProfile
    activated: bool


@dataclass(frozen=True)
class SoundPackProfileUninstallResult:
    pack_id: str
    profile: SoundProfile
    removed: bool


def _profile_for_manifest(
    profile: SoundProfile,
    manifest: SoundPackManifest,
) -> SoundProfile:
    """Keep only explicit asset ids that the target manifest still owns."""

    events = {
        event_id: (
            replace(preference, sound_id=None)
            if preference.sound_id is not None
            and preference.sound_id not in manifest.files
            else preference
        )
        for event_id, preference in profile.events.items()
    }
    return replace(profile, pack_id=manifest.pack_id, events=events)


class SoundPackProfileCoordinator:
    """Keep pack installation/removal and persisted profile selection coherent."""

    def __init__(
        self,
        pack_manager: SoundPackManager,
        profile_manager: SoundProfileManager,
    ) -> None:
        if not isinstance(pack_manager, SoundPackManager):
            raise TypeError("pack_manager must be SoundPackManager")
        if not isinstance(profile_manager, SoundProfileManager):
            raise TypeError("profile_manager must be SoundProfileManager")
        self._packs = pack_manager
        self._profiles = profile_manager

    @property
    def current_profile(self) -> SoundProfile:
        return self._profiles.current

    @property
    def fallback_pack_id(self) -> str:
        """Expose only the stable fallback identity needed by presentation policy."""

        return self._packs.fallback_pack_id

    def resolve_usable_pack(self, pack_id: str) -> str:
        """Resolve through the same installed-pack authority used by profiles."""

        return self._packs.resolve_usable_pack(pack_id)

    def status(self, entry: SoundPackCatalogEntry) -> SoundPackCatalogStatus:
        """Project catalog/install status without exposing storage internals."""

        return self._packs.status(entry)

    def install(
        self,
        entry: SoundPackCatalogEntry,
        *,
        activate: bool = False,
    ) -> SoundPackProfileInstallResult:
        """Install/update a verified pack and optionally select it.

        Storage installation happens first. If profile persistence then fails, the
        extra installed pack is harmless and the previously persisted active pack
        remains valid; this is intentionally safer than selecting missing assets.
        """

        profile = self._profiles.current
        if entry.compatible and profile.pack_id == entry.manifest.pack_id:
            prepared = _profile_for_manifest(profile, entry.manifest)
            if prepared != profile:
                # Persist a default-safe mapping before the active version changes.
                profile = self._profiles.save(prepared)

        manifest = self._packs.install(entry)
        profile = self._profiles.current
        if activate and profile.pack_id != manifest.pack_id:
            profile = self._profiles.save(_profile_for_manifest(profile, manifest))
        return SoundPackProfileInstallResult(manifest, profile, activate)

    def uninstall(self, pack_id: str) -> SoundPackProfileUninstallResult:
        """Remove a pack without ever persisting a reference to removed assets.

        For an active pack, fallback profile persistence is committed *before*
        asset deletion. If profile persistence fails, no pack is deleted. If pack
        deletion fails afterwards, the profile already points to the guaranteed
        fallback while the old pack merely remains installed, which is safe.
        """

        current = self._profiles.current
        plan = self._packs.prepare_uninstall(pack_id, active_profile=current)
        if plan.resulting_profile != current:
            self._profiles.save(plan.resulting_profile)
        self._packs.commit_uninstall(plan)
        return SoundPackProfileUninstallResult(
            pack_id=plan.pack_id,
            profile=self._profiles.current,
            removed=plan.remove_from_storage,
        )

    def reconcile(self) -> SoundProfile:
        """Repair a stale selected pack using the pack manager's guaranteed fallback."""

        current = self._profiles.current
        resolved = self._packs.resolve_profile(current)
        if resolved == current:
            return current
        return self._profiles.save(resolved)
