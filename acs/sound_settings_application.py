from __future__ import annotations

"""Trusted application boundary for accessible sound settings.

The browser may request only closed-world semantic mutations. Profile
persistence, pack verification/storage and playback remain owned by the existing
sound-profile, pack-coordinator and profiled-runtime authorities.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .sound_pack_catalog import (
    SoundPackCatalogEntry,
    SoundPackRightsEvidence,
    SoundPackState,
)
from .sound_pack_profile import SoundPackProfileCoordinator
from .sound_profile_store import SoundProfileManager, SoundProfileWriteBlockedError
from .sound_profiles import (
    CORE_SOUND_EVENTS,
    OPTIONAL_CLASSROOM_SOUND_EVENTS,
    SoundEventPreference,
    SoundPackManifest,
    SoundProfile,
)
from .sound_runtime import ProfiledSoundRuntime


_EVENT_LABELS = {
    "start": ("Початок партії", "Game start"),
    "move": ("Звичайний хід", "Move"),
    "capture": ("Взяття", "Capture"),
    "check": ("Шах", "Check"),
    "castle": ("Рокіровка", "Castling"),
    "promotion": ("Перетворення пішака", "Promotion"),
    "illegal": ("Нелегальний хід", "Illegal move"),
    "end": ("Кінець партії", "Game end"),
    "tick": ("Тік годинника", "Clock tick"),
    "low_time": ("Мало часу", "Low time"),
    "classroom.join": ("Приєднання до класу", "Classroom join"),
    "classroom.leave": ("Вихід із класу", "Classroom leave"),
    "classroom.hand_raise": ("Піднята рука", "Hand raised"),
    "classroom.permission": ("Дозвіл у класі", "Classroom permission"),
    "lesson.position_deployed": ("Позицію уроку надіслано", "Lesson position deployed"),
    "chat.message": ("Повідомлення чату", "Chat message"),
    "file.transfer_complete": ("Передавання файлу завершено", "File transfer complete"),
}


@dataclass(frozen=True)
class SoundSettingsResult:
    ok: bool
    snapshot: Mapping[str, object]
    announcement: str = ""


class SoundSettingsApplication:
    def __init__(
        self,
        profile_manager: SoundProfileManager,
        runtime: ProfiledSoundRuntime,
        *,
        pack_coordinator: SoundPackProfileCoordinator | None = None,
        catalog: Mapping[str, SoundPackCatalogEntry] | None = None,
        installed_pack_provider: Callable[[], Mapping[str, SoundPackManifest]] | None = None,
        installed_rights_provider: Callable[[str], SoundPackRightsEvidence | None] | None = None,
        pack_compatibility_provider: Callable[[SoundPackManifest], bool] | None = None,
    ) -> None:
        if not isinstance(profile_manager, SoundProfileManager):
            raise TypeError("profile_manager must be SoundProfileManager")
        if not isinstance(runtime, ProfiledSoundRuntime):
            raise TypeError("runtime must be ProfiledSoundRuntime")
        if pack_coordinator is not None and not isinstance(
            pack_coordinator, SoundPackProfileCoordinator
        ):
            raise TypeError("pack_coordinator must be SoundPackProfileCoordinator or None")
        if catalog is None:
            catalog = {}
        if not isinstance(catalog, Mapping):
            raise TypeError("catalog must be a mapping")
        normalized: dict[str, SoundPackCatalogEntry] = {}
        for pack_id, entry in catalog.items():
            if not isinstance(pack_id, str) or not isinstance(entry, SoundPackCatalogEntry):
                raise TypeError("catalog must map text pack IDs to SoundPackCatalogEntry")
            if pack_id != entry.manifest.pack_id:
                raise ValueError("catalog key must equal manifest pack_id")
            normalized[pack_id] = entry
        if normalized and pack_coordinator is None:
            raise ValueError("catalog actions require a pack coordinator")
        if installed_pack_provider is not None and not callable(installed_pack_provider):
            raise TypeError("installed_pack_provider must be callable or None")
        if installed_rights_provider is not None and not callable(
            installed_rights_provider
        ):
            raise TypeError("installed_rights_provider must be callable or None")
        if pack_compatibility_provider is not None and not callable(
            pack_compatibility_provider
        ):
            raise TypeError("pack_compatibility_provider must be callable or None")
        self._profiles = profile_manager
        self._runtime = runtime
        self._packs = pack_coordinator
        self._catalog = normalized
        self._installed_pack_provider = installed_pack_provider
        self._installed_rights_provider = installed_rights_provider
        self._pack_compatibility_provider = pack_compatibility_provider

    @staticmethod
    def _language(value: object) -> str:
        return "en" if value == "en" else "uk"

    def _require_writable(self) -> None:
        if self._profiles.writes_blocked:
            raise SoundProfileWriteBlockedError(
                "sound profile mutations are blocked by a newer schema"
            )

    def _installed_local_packs(self) -> dict[str, SoundPackManifest]:
        provider = self._installed_pack_provider
        if provider is None:
            return {}
        raw = provider()
        if not isinstance(raw, Mapping):
            raise TypeError("installed pack provider must return a mapping")
        result: dict[str, SoundPackManifest] = {}
        for pack_id, manifest in raw.items():
            if not isinstance(pack_id, str) or not isinstance(manifest, SoundPackManifest):
                raise TypeError("installed pack provider returned an invalid mapping")
            if pack_id != manifest.pack_id:
                raise ValueError("installed pack key must equal manifest pack_id")
            result[pack_id] = manifest
        return result

    def _local_pack_rights(
        self,
        pack_id: str,
        manifest: SoundPackManifest,
    ) -> SoundPackRightsEvidence | None:
        provider = self._installed_rights_provider
        if provider is None:
            return None
        rights = provider(pack_id)
        if rights is not None and not isinstance(rights, SoundPackRightsEvidence):
            raise TypeError(
                "installed rights provider must return SoundPackRightsEvidence or null"
            )
        if rights is not None and rights.license_id != manifest.license_id:
            raise ValueError(
                "installed rights evidence license must match installed manifest"
            )
        return rights

    def _local_pack_compatible(self, manifest: SoundPackManifest) -> bool:
        entry = self._catalog.get(manifest.pack_id)
        if (
            entry is not None
            and entry.manifest.version == manifest.version
            and not entry.compatible
        ):
            return False
        provider = self._pack_compatibility_provider
        if provider is None:
            return True
        compatible = provider(manifest)
        if type(compatible) is not bool:
            raise TypeError("pack compatibility provider must return boolean")
        return compatible

    def _active_manifest(
        self,
        profile,
        installed_local: Mapping[str, SoundPackManifest],
    ) -> SoundPackManifest | None:
        if profile.pack_id == "classic":
            return None
        local = installed_local.get(profile.pack_id)
        if local is not None:
            return local if self._local_pack_compatible(local) else None
        entry = self._catalog.get(profile.pack_id)
        if entry is None or self._packs is None or not entry.compatible:
            return None
        status = self._packs.status(entry)
        if status.state is not SoundPackState.CURRENT:
            return None
        if self._packs.resolve_usable_pack(profile.pack_id) != profile.pack_id:
            return None
        return entry.manifest

    @staticmethod
    def _visible_event_ids(
        profile,
        active_manifest: SoundPackManifest | None,
    ) -> tuple[str, ...]:
        event_ids = list(CORE_SOUND_EVENTS)
        if profile.pack_id != "classic" and active_manifest is not None:
            event_ids.extend(
                event_id
                for event_id in OPTIONAL_CLASSROOM_SOUND_EVENTS
                if event_id in active_manifest.files
            )
        return tuple(event_ids)

    @staticmethod
    def _sound_choices(
        profile,
        event_id: str,
        active_manifest: SoundPackManifest | None,
    ) -> tuple[str, ...]:
        if profile.pack_id == "classic":
            return (event_id,)
        if active_manifest is None:
            return (profile.selected_sound_id(event_id),)
        return tuple(sorted(active_manifest.files))

    def _normalized_profile_for_pack(
        self,
        pack_id: str,
        manifest: SoundPackManifest | None,
    ) -> SoundProfile:
        current = self._profiles.current
        events: dict[str, SoundEventPreference] = {}
        allowed = None if manifest is None else set(manifest.files)
        pack_changed = current.pack_id != pack_id
        for event_id, preference in current.events.items():
            sound_id = preference.sound_id
            if sound_id is not None:
                if (
                    pack_changed
                    or pack_id == "classic"
                    or allowed is None
                    or sound_id not in allowed
                ):
                    sound_id = None
            events[event_id] = SoundEventPreference(
                enabled=preference.enabled,
                volume_percent=preference.volume_percent,
                sound_id=sound_id,
            )
        return SoundProfile(
            pack_id=pack_id,
            master_enabled=current.master_enabled,
            master_volume_percent=current.master_volume_percent,
            events=events,
        )

    def _save_pack_profile(
        self,
        pack_id: str,
        manifest: SoundPackManifest | None,
    ) -> SoundProfile:
        target = self._normalized_profile_for_pack(pack_id, manifest)
        if target == self._profiles.current:
            return target
        saved = self._profiles.save(target)
        if saved.pack_id != pack_id:
            raise RuntimeError("selected sound pack could not be retained")
        return saved

    def reconcile_active_profile(self) -> SoundProfile:
        """Normalize persisted sound IDs against the exact active pack authority."""

        current = self._profiles.current
        if self._profiles.writes_blocked:
            return current
        installed_local = self._installed_local_packs()
        manifest = self._active_manifest(current, installed_local)
        if current.pack_id != "classic" and manifest is None:
            local = installed_local.get(current.pack_id)
            if local is not None and not self._local_pack_compatible(local):
                return self._save_pack_profile("classic", None)
            return current
        return self._save_pack_profile(current.pack_id, manifest)

    def snapshot(self, *, language: str = "uk") -> dict[str, object]:
        lang = self._language(language)
        profile = self._profiles.current
        installed_local = self._installed_local_packs()
        active_manifest = self._active_manifest(profile, installed_local)
        events: list[dict[str, object]] = []
        for event_id in self._visible_event_ids(profile, active_manifest):
            pref = profile.preference_for(event_id)
            labels = _EVENT_LABELS[event_id]
            events.append(
                {
                    "event_id": event_id,
                    "label": labels[1] if lang == "en" else labels[0],
                    "enabled": pref.enabled,
                    "volume_percent": pref.volume_percent,
                    "sound_id": profile.selected_sound_id(event_id),
                    "sound_choices": self._sound_choices(
                        profile,
                        event_id,
                        active_manifest,
                    ),
                    "effective_volume": profile.effective_volume(event_id),
                }
            )

        packs: list[dict[str, object]] = []
        represented: set[str] = set()
        if self._packs is not None:
            for pack_id in sorted(self._catalog):
                entry = self._catalog[pack_id]
                status = self._packs.status(entry)
                manifest = entry.manifest
                installed_manifest = installed_local.get(pack_id)
                installed_compatible = (
                    None
                    if installed_manifest is None
                    else self._local_pack_compatible(installed_manifest)
                )
                display_manifest = (
                    installed_manifest
                    if installed_manifest is not None
                    else manifest
                )
                stored_rights = (
                    None
                    if installed_manifest is None
                    else self._local_pack_rights(pack_id, installed_manifest)
                )
                rights = (
                    entry.rights_evidence
                    if installed_manifest is None
                    else stored_rights
                )
                catalog_rights = entry.rights_evidence
                projected_state = status.state.value
                if installed_manifest is not None and installed_manifest == manifest:
                    if stored_rights is None:
                        projected_state = "rights_unverified"
                    elif stored_rights != catalog_rights:
                        projected_state = "rights_conflict"
                represented.add(manifest.pack_id)
                packs.append(
                    {
                        "pack_id": manifest.pack_id,
                        "title": display_manifest.title,
                        "version": display_manifest.version,
                        "author": display_manifest.author,
                        "license_id": display_manifest.license_id,
                        "provenance": display_manifest.provenance,
                        "catalog_version": manifest.version,
                        "catalog_title": manifest.title,
                        "catalog_author": manifest.author,
                        "catalog_license_id": manifest.license_id,
                        "catalog_provenance": manifest.provenance,
                        "rights_auditable": rights is not None,
                        "rights_source_uri": "" if rights is None else rights.source_uri,
                        "license_uri": "" if rights is None else rights.license_uri,
                        "catalog_rights_auditable": catalog_rights is not None,
                        "catalog_rights_source_uri": (
                            "" if catalog_rights is None else catalog_rights.source_uri
                        ),
                        "catalog_license_uri": (
                            "" if catalog_rights is None else catalog_rights.license_uri
                        ),
                        "compatible": entry.compatible,
                        "installed_compatible": installed_compatible,
                        "installed_version": status.installed_version,
                        "state": projected_state,
                        "active": profile.pack_id == manifest.pack_id,
                        "can_install": catalog_rights is not None
                        and status.state
                        in {SoundPackState.NOT_INSTALLED, SoundPackState.DIFFERENT_VERSION},
                        "can_uninstall": status.installed_version is not None
                        and manifest.pack_id != self._packs.fallback_pack_id,
                    }
                )

        for pack_id, manifest in sorted(installed_local.items()):
            if pack_id == "classic" or pack_id in represented:
                continue
            compatible = self._local_pack_compatible(manifest)
            rights = self._local_pack_rights(pack_id, manifest)
            packs.append(
                {
                    "pack_id": manifest.pack_id,
                    "title": manifest.title,
                    "version": manifest.version,
                    "author": manifest.author,
                    "license_id": manifest.license_id,
                    "provenance": manifest.provenance,
                    "rights_auditable": rights is not None,
                    "rights_source_uri": "" if rights is None else rights.source_uri,
                    "license_uri": "" if rights is None else rights.license_uri,
                    "catalog_rights_auditable": False,
                    "catalog_rights_source_uri": "",
                    "catalog_license_uri": "",
                    "compatible": compatible,
                    "installed_compatible": compatible,
                    "installed_version": manifest.version,
                    "state": "local_installed" if compatible else "incompatible",
                    "active": profile.pack_id == manifest.pack_id,
                    "can_install": False,
                    "can_uninstall": self._packs is not None
                    and manifest.pack_id != self._packs.fallback_pack_id,
                }
            )

        return {
            "master_enabled": profile.master_enabled,
            "master_volume_percent": profile.master_volume_percent,
            "active_pack_id": profile.pack_id,
            "can_select_classic": profile.pack_id != "classic",
            "writes_blocked": self._profiles.writes_blocked,
            "events": tuple(events),
            "packs": tuple(packs),
        }

    def _result(self, announcement: str, *, language: str) -> SoundSettingsResult:
        return SoundSettingsResult(True, self.snapshot(language=language), announcement)

    def set_master(
        self,
        *,
        enabled: bool | None = None,
        volume_percent: int | None = None,
        language: str = "uk",
    ) -> SoundSettingsResult:
        self._require_writable()
        if enabled is not None and type(enabled) is not bool:
            raise TypeError("enabled must be boolean or null")
        if volume_percent is not None and type(volume_percent) is not int:
            raise TypeError("volume_percent must be an integer or null")
        self._profiles.set_master(enabled=enabled, volume_percent=volume_percent)
        message = "Sound settings saved." if language == "en" else "Налаштування звуку збережено."
        return self._result(message, language=language)

    def set_event(
        self,
        event_id: str,
        *,
        enabled: bool | None = None,
        volume_percent: int | None = None,
        sound_id: str | None = None,
        language: str = "uk",
    ) -> SoundSettingsResult:
        self._require_writable()
        profile = self._profiles.current
        installed_local = self._installed_local_packs()
        active_manifest = self._active_manifest(profile, installed_local)
        if event_id not in self._visible_event_ids(profile, active_manifest):
            raise ValueError("unknown sound event")
        current = profile.preference_for(event_id)
        if enabled is not None and type(enabled) is not bool:
            raise TypeError("enabled must be boolean or null")
        if volume_percent is not None and type(volume_percent) is not int:
            raise TypeError("volume_percent must be an integer or null")
        if sound_id is not None and type(sound_id) is not str:
            raise TypeError("sound_id must be text or null")
        if (
            sound_id is not None
            and (
                self._installed_pack_provider is not None
                or profile.pack_id in self._catalog
            )
            and sound_id not in self._sound_choices(profile, event_id, active_manifest)
        ):
            raise ValueError("sound_id is not available in the active sound pack")
        preference = SoundEventPreference(
            enabled=current.enabled if enabled is None else enabled,
            volume_percent=current.volume_percent if volume_percent is None else volume_percent,
            sound_id=current.sound_id if sound_id is None else sound_id,
        )
        self._profiles.set_event(event_id, preference)
        message = "Sound event saved." if language == "en" else "Налаштування події звуку збережено."
        return self._result(message, language=language)

    def preview(self, event_id: str, *, language: str = "uk") -> SoundSettingsResult:
        profile = self._profiles.current
        installed_local = self._installed_local_packs()
        active_manifest = self._active_manifest(profile, installed_local)
        if event_id not in self._visible_event_ids(profile, active_manifest):
            raise ValueError("unknown sound event")
        preview = self._runtime.preview(event_id)
        if preview.error_type is not None:
            raise RuntimeError("sound preview failed")
        if not preview.delivered:
            message = (
                "Preview is muted by the current profile."
                if language == "en"
                else "Попередній звук вимкнено поточним профілем."
            )
        else:
            message = "Sound preview played." if language == "en" else "Попередній звук відтворено."
        return self._result(message, language=language)

    def select_pack(self, pack_id: str, *, language: str = "uk") -> SoundSettingsResult:
        self._require_writable()
        manifest: SoundPackManifest | None = None
        if pack_id == "classic":
            pass
        else:
            installed = self._installed_local_packs()
            manifest = installed.get(pack_id)
            if manifest is not None and not self._local_pack_compatible(manifest):
                raise ValueError("sound pack is incompatible with this application")
            if manifest is None and self._packs is not None and pack_id in self._catalog:
                entry = self._catalog[pack_id]
                status = self._packs.status(entry)
                if status.state is not SoundPackState.CURRENT:
                    raise ValueError("sound pack catalog version is not the installed version")
                if self._packs.resolve_usable_pack(pack_id) != pack_id:
                    raise ValueError("sound pack is not installed")
                manifest = entry.manifest
            if manifest is None:
                raise ValueError("unknown sound pack")
        self._save_pack_profile(pack_id, manifest)
        message = "Sound pack selected." if language == "en" else "Набір звуків вибрано."
        return self._result(message, language=language)

    def install_pack(
        self,
        pack_id: str,
        *,
        activate: bool = False,
        language: str = "uk",
    ) -> SoundSettingsResult:
        self._require_writable()
        if self._packs is None:
            raise RuntimeError("sound pack management is unavailable")
        if type(activate) is not bool:
            raise TypeError("activate must be boolean")
        try:
            entry = self._catalog[pack_id]
        except KeyError as exc:
            raise ValueError("unknown sound pack") from exc
        status = self._packs.status(entry)
        if (
            entry.rights_evidence is None
            or status.state
            not in {SoundPackState.NOT_INSTALLED, SoundPackState.DIFFERENT_VERSION}
        ):
            raise ValueError("sound pack is not installable in its current state")
        installed = self._packs.install(entry, activate=False)
        if activate:
            self._save_pack_profile(installed.manifest.pack_id, installed.manifest)
        message = "Sound pack installed." if language == "en" else "Набір звуків установлено."
        return self._result(message, language=language)

    def uninstall_pack(self, pack_id: str, *, language: str = "uk") -> SoundSettingsResult:
        self._require_writable()
        if self._packs is None:
            raise RuntimeError("sound pack management is unavailable")
        installed_local = self._installed_local_packs()
        if pack_id not in self._catalog and pack_id not in installed_local:
            raise ValueError("unknown sound pack")
        if self._packs.fallback_pack_id != "classic":
            raise RuntimeError("unsupported sound pack fallback authority")
        self._packs.uninstall(pack_id)
        message = "Sound pack removed." if language == "en" else "Набір звуків видалено."
        return self._result(message, language=language)


__all__ = ["SoundSettingsApplication", "SoundSettingsResult"]
