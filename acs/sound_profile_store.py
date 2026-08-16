from __future__ import annotations

"""Versioned persistence/recovery boundary for sound profiles.

This module deliberately knows nothing about filesystem layout, SQLite, Windows
playback APIs or remote catalogs. It owns only canonical profile persistence and
recovery policy. ``SoundRuntime``/``GameSoundRuntime`` remain the playback and
semantic chess-event authorities.
"""

from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable, Mapping, Protocol

from .sound_profiles import SOUND_PROFILE_SCHEMA_VERSION, SoundEventPreference, SoundProfile


class SoundProfileStoragePort(Protocol):
    """Atomic persistence boundary implemented by an infrastructure adapter."""

    def read_profile(self) -> Mapping[str, object] | None: ...

    def write_profile_atomically(self, payload: Mapping[str, object]) -> None: ...


class SoundPackResolverPort(Protocol):
    """Resolve a requested pack to an installed compatible pack.

    Implementations must return a usable pack id and provide their own guaranteed
    fallback (normally ``classic``). Core does not inspect pack files here.
    """

    def resolve_usable_pack(self, requested_pack_id: str) -> str: ...


class SoundProfileRecoveryReason(str, Enum):
    ABSENT = "absent"
    LEGACY_MIGRATED = "legacy_migrated"
    MALFORMED = "malformed"
    FUTURE_SCHEMA = "future_schema"
    PACK_FALLBACK = "pack_fallback"


@dataclass(frozen=True)
class SoundProfileLoadResult:
    profile: SoundProfile
    recovery_reasons: tuple[SoundProfileRecoveryReason, ...] = ()
    persisted_canonical: bool = False

    @property
    def recovered(self) -> bool:
        return bool(self.recovery_reasons)


class SoundProfileManager:
    """Single application-level source for persisted ``SoundProfile`` state.

    Malformed/legacy payloads are normalized to the current schema. A payload
    from a future schema is *not overwritten*: the current process uses a safe
    in-memory default so downgrade/rollback cannot destroy newer user settings.
    Pack reconciliation changes only ``pack_id`` and therefore preserves master
    and per-event preferences.
    """

    def __init__(
        self,
        storage: SoundProfileStoragePort,
        pack_resolver: SoundPackResolverPort | Callable[[str], str],
        *,
        default_profile: SoundProfile | None = None,
    ) -> None:
        self._storage = storage
        self._pack_resolver = pack_resolver
        self._default = default_profile or SoundProfile()
        if not isinstance(self._default, SoundProfile):
            raise TypeError("default_profile must be SoundProfile")
        self._current: SoundProfile | None = None

    @property
    def current(self) -> SoundProfile:
        if self._current is None:
            return self.load().profile
        return self._current

    def profile_provider(self) -> SoundProfile:
        """Callable-compatible provider for ``ProfiledSoundRuntime``."""

        return self.current

    def load(self) -> SoundProfileLoadResult:
        raw = self._storage.read_profile()
        reasons: list[SoundProfileRecoveryReason] = []
        persist = False

        if raw is None:
            profile = self._default
            reasons.append(SoundProfileRecoveryReason.ABSENT)
            persist = True
        else:
            schema = raw.get("schema_version") if isinstance(raw, Mapping) else None
            if isinstance(schema, int) and schema > SOUND_PROFILE_SCHEMA_VERSION:
                profile = self._reconcile_pack(self._default, reasons)
                self._current = profile
                return SoundProfileLoadResult(
                    profile,
                    (SoundProfileRecoveryReason.FUTURE_SCHEMA, *tuple(reasons)),
                    persisted_canonical=False,
                )
            try:
                profile = SoundProfile.from_mapping(raw)
            except (TypeError, ValueError, OverflowError):
                profile = self._default
                reasons.append(SoundProfileRecoveryReason.MALFORMED)
                persist = True
            else:
                if schema is None:
                    reasons.append(SoundProfileRecoveryReason.LEGACY_MIGRATED)
                    persist = True

        reconciled = self._reconcile_pack(profile, reasons)
        if reconciled != profile:
            persist = True
        profile = reconciled
        if persist:
            self._persist(profile)
        self._current = profile
        return SoundProfileLoadResult(profile, tuple(reasons), persisted_canonical=persist)

    def save(self, profile: SoundProfile) -> SoundProfile:
        if not isinstance(profile, SoundProfile):
            raise TypeError("profile must be SoundProfile")
        reasons: list[SoundProfileRecoveryReason] = []
        profile = self._reconcile_pack(profile, reasons)
        self._persist(profile)
        self._current = profile
        return profile

    def set_master(self, *, enabled: bool | None = None, volume_percent: int | None = None) -> SoundProfile:
        profile = self.current
        updated = SoundProfile(
            pack_id=profile.pack_id,
            master_enabled=profile.master_enabled if enabled is None else enabled,
            master_volume_percent=(
                profile.master_volume_percent if volume_percent is None else volume_percent
            ),
            events=profile.events,
        )
        return self.save(updated)

    def set_pack(self, pack_id: str) -> SoundProfile:
        return self.save(replace(self.current, pack_id=pack_id))

    def set_event(self, event_id: str, preference: SoundEventPreference) -> SoundProfile:
        if not isinstance(preference, SoundEventPreference):
            raise TypeError("preference must be SoundEventPreference")
        events = dict(self.current.events)
        events[event_id] = preference
        return self.save(replace(self.current, events=events))

    def reset_event(self, event_id: str) -> SoundProfile:
        events = dict(self.current.events)
        events.pop(event_id, None)
        return self.save(replace(self.current, events=events))

    def _resolve_pack(self, requested_pack_id: str) -> str:
        resolver = self._pack_resolver
        resolved = (
            resolver(requested_pack_id)
            if callable(resolver)
            else resolver.resolve_usable_pack(requested_pack_id)
        )
        resolved = str(resolved).strip().lower()
        if not resolved:
            raise ValueError("pack resolver must return a usable pack id")
        # Let SoundProfile perform canonical stable-id validation.
        return SoundProfile(pack_id=resolved).pack_id

    def _reconcile_pack(
        self,
        profile: SoundProfile,
        reasons: list[SoundProfileRecoveryReason],
    ) -> SoundProfile:
        resolved = self._resolve_pack(profile.pack_id)
        if resolved == profile.pack_id:
            return profile
        reasons.append(SoundProfileRecoveryReason.PACK_FALLBACK)
        return replace(profile, pack_id=resolved)

    def _persist(self, profile: SoundProfile) -> None:
        self._storage.write_profile_atomically(profile.to_mapping())
