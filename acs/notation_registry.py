from __future__ import annotations

"""Registration-based presentation-neutral notation profiles.

Built-in SAN/Ukrainian/English profiles delegate to the canonical formatter in
``acs.notation``. Additional profiles can be registered at the composition
root without adding provider-specific conditionals to chess or UI code.
"""

from dataclasses import dataclass
from typing import Callable, Iterable

from .notation import PROFILES, format_san


NotationFormatter = Callable[[str], str]


@dataclass(frozen=True)
class NotationProfileDescriptor:
    profile_id: str
    title: str
    locale: str | None = None
    built_in: bool = False

    def __post_init__(self) -> None:
        profile_id = self.profile_id.strip()
        title = self.title.strip()
        if not profile_id:
            raise ValueError("profile_id must not be empty")
        if profile_id != self.profile_id:
            raise ValueError("profile_id must not contain surrounding whitespace")
        if profile_id.casefold() != profile_id:
            raise ValueError("profile_id must be lowercase and stable")
        if not title:
            raise ValueError("profile title must not be empty")
        if self.locale is not None and not self.locale.strip():
            raise ValueError("locale must be non-empty when provided")


class NotationProfileRegistry:
    """Stable composition-root registry for notation/localization profiles."""

    def __init__(self, *, include_builtins: bool = True) -> None:
        self._descriptors: dict[str, NotationProfileDescriptor] = {}
        self._formatters: dict[str, NotationFormatter] = {}
        if include_builtins:
            self._register_builtin("san", "SAN", None)
            self._register_builtin("uk_literal", "Українська буквальна", "uk")
            self._register_builtin("en_literal", "English literal", "en")

    def _register_builtin(self, profile_id: str, title: str, locale: str | None) -> None:
        if profile_id not in PROFILES:
            raise RuntimeError(f"canonical notation formatter lacks built-in profile: {profile_id}")
        descriptor = NotationProfileDescriptor(
            profile_id=profile_id,
            title=title,
            locale=locale,
            built_in=True,
        )
        self._descriptors[profile_id] = descriptor
        self._formatters[profile_id] = lambda san, pid=profile_id: format_san(san, pid)

    def register(
        self,
        descriptor: NotationProfileDescriptor,
        formatter: NotationFormatter,
    ) -> None:
        if descriptor.profile_id in self._descriptors:
            raise ValueError(f"notation profile already registered: {descriptor.profile_id}")
        if descriptor.built_in:
            raise ValueError("external registrations cannot claim built_in metadata")
        if not callable(formatter):
            raise TypeError("notation formatter must be callable")
        self._descriptors[descriptor.profile_id] = descriptor
        self._formatters[descriptor.profile_id] = formatter

    def unregister(self, profile_id: str) -> None:
        profile_id = self._normalize_profile_id(profile_id)
        descriptor = self.descriptor(profile_id)
        if descriptor.built_in:
            raise ValueError(f"built-in notation profile cannot be unregistered: {profile_id}")
        del self._descriptors[profile_id]
        del self._formatters[profile_id]

    def descriptor(self, profile_id: str) -> NotationProfileDescriptor:
        profile_id = self._normalize_profile_id(profile_id)
        try:
            return self._descriptors[profile_id]
        except KeyError as exc:
            raise KeyError(f"unknown notation profile: {profile_id}") from exc

    def descriptors(self, *, locale: str | None = None) -> tuple[NotationProfileDescriptor, ...]:
        values: Iterable[NotationProfileDescriptor] = self._descriptors.values()
        if locale is not None:
            needle = locale.strip().casefold()
            if not needle:
                raise ValueError("locale must not be empty")
            values = (
                item
                for item in values
                if item.locale is not None and item.locale.casefold() == needle
            )
        return tuple(values)

    def profile_ids(self, *, locale: str | None = None) -> tuple[str, ...]:
        return tuple(item.profile_id for item in self.descriptors(locale=locale))

    def format(self, san: str, profile_id: str) -> str:
        descriptor = self.descriptor(profile_id)
        result = self._formatters[descriptor.profile_id](san)
        if not isinstance(result, str):
            raise TypeError(
                f"notation profile {descriptor.profile_id} returned non-string output"
            )
        return result

    @staticmethod
    def _normalize_profile_id(profile_id: str) -> str:
        value = str(profile_id).strip().casefold()
        if not value:
            raise ValueError("profile_id must not be empty")
        return value
