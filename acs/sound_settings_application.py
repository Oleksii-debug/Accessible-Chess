from __future__ import annotations

"""Trusted application boundary for accessible sound settings.

The browser may request only closed-world semantic mutations. Profile
persistence, pack verification/storage and playback remain owned by the existing
sound-profile, pack-coordinator and profiled-runtime authorities.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .sound_pack_catalog import SoundPackCatalogEntry, SoundPackState
from .sound_pack_profile import SoundPackProfileCoordinator
from .sound_profile_store import SoundProfileManager
from .sound_profiles import CORE_SOUND_EVENTS, SoundEventPreference, SoundPackManifest
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
        self._profiles = profile_manager
        self._runtime = runtime
        self._packs = pack_coordinator
        self._catalog = normalized
        self._installed_pack_provider = installed_pack_provider

    @staticmethod
    def _language(value: object) -> str:
        return "en" if value == "en" else "uk"

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

    def snapshot(self, *, language: str = "uk") -> dict[str, object]:
        lang = self._language(language)
        profile = self._profiles.current
        events: list[dict[str, object]] = []
        for event_id in CORE_SOUND_EVENTS:
            pref = profile.preference_for(event_id)
            labels = _EVENT_LABELS[event_id]
            events.append(
                {
                    "event_id": event_id,
                    "label": labels[1] if lang == "en" else labels[0],
                    "enabled": pref.enabled,
                    "volume_percent": pref.volume_percent,
                    "sound_id": profile.selected_sound_id(event_id),
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
                represented.add(manifest.pack_id)
                packs.append(
                    {
                        "pack_id": manifest.pack_id,
                        "title": manifest.title,
                        "version": manifest.version,
                        "author": manifest.author,
                        "license_id": manifest.license_id,
                        "compatible": entry.compatible,
                        "installed_version": status.installed_version,
                        "state": status.state.value,
                        "active": profile.pack_id == manifest.pack_id,
                        "can_install": status.state
                        in {SoundPackState.NOT_INSTALLED, SoundPackState.DIFFERENT_VERSION},
                        "can_uninstall": status.installed_version is not None
                        and manifest.pack_id != self._packs.fallback_pack_id,
                    }
                )

        for pack_id, manifest in sorted(self._installed_local_packs().items()):
            if pack_id == "classic" or pack_id in represented:
                continue
            packs.append(
                {
                    "pack_id": manifest.pack_id,
                    "title": manifest.title,
                    "version": manifest.version,
                    "author": manifest.author,
                    "license_id": manifest.license_id,
                    "compatible": True,
                    "installed_version": manifest.version,
                    "state": "local_installed",
                    "active": profile.pack_id == manifest.pack_id,
                    "can_install": False,
                    "can_uninstall": False,
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
        if event_id not in CORE_SOUND_EVENTS:
            raise ValueError("unknown sound event")
        current = self._profiles.current.preference_for(event_id)
        if enabled is not None and type(enabled) is not bool:
            raise TypeError("enabled must be boolean or null")
        if volume_percent is not None and type(volume_percent) is not int:
            raise TypeError("volume_percent must be an integer or null")
        preference = SoundEventPreference(
            enabled=current.enabled if enabled is None else enabled,
            volume_percent=current.volume_percent if volume_percent is None else volume_percent,
            sound_id=current.sound_id if sound_id is None else sound_id,
        )
        self._profiles.set_event(event_id, preference)
        message = "Sound event saved." if language == "en" else "Налаштування події звуку збережено."
        return self._result(message, language=language)

    def preview(self, event_id: str, *, language: str = "uk") -> SoundSettingsResult:
        if event_id not in CORE_SOUND_EVENTS:
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
        if pack_id == "classic":
            selected = self._profiles.set_pack(pack_id)
            if selected.pack_id != "classic":
                raise RuntimeError("classic sound pack fallback is unavailable")
        elif self._packs is not None and pack_id in self._catalog:
            resolved = self._packs.resolve_usable_pack(pack_id)
            if resolved != pack_id:
                raise ValueError("sound pack is not installed")
            selected = self._profiles.set_pack(pack_id)
            if selected.pack_id != pack_id:
                raise RuntimeError("selected sound pack could not be retained")
        else:
            installed = self._installed_local_packs()
            if pack_id not in installed:
                raise ValueError("unknown sound pack")
            selected = self._profiles.set_pack(pack_id)
            if selected.pack_id != pack_id:
                raise RuntimeError("selected local sound pack is unavailable")
        message = "Sound pack selected." if language == "en" else "Набір звуків вибрано."
        return self._result(message, language=language)

    def install_pack(
        self,
        pack_id: str,
        *,
        activate: bool = False,
        language: str = "uk",
    ) -> SoundSettingsResult:
        if self._packs is None:
            raise RuntimeError("sound pack management is unavailable")
        if type(activate) is not bool:
            raise TypeError("activate must be boolean")
        try:
            entry = self._catalog[pack_id]
        except KeyError as exc:
            raise ValueError("unknown sound pack") from exc
        self._packs.install(entry, activate=activate)
        message = "Sound pack installed." if language == "en" else "Набір звуків установлено."
        return self._result(message, language=language)

    def uninstall_pack(self, pack_id: str, *, language: str = "uk") -> SoundSettingsResult:
        if self._packs is None:
            raise RuntimeError("sound pack management is unavailable")
        if pack_id not in self._catalog:
            raise ValueError("unknown sound pack")
        self._packs.uninstall(pack_id)
        message = "Sound pack removed." if language == "en" else "Набір звуків видалено."
        return self._result(message, language=language)


__all__ = ["SoundSettingsApplication", "SoundSettingsResult"]
