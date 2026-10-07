from __future__ import annotations

"""Accessible, provider-neutral release update coordination.

A replaceable channel stages a candidate; the existing update_security authority
authenticates exact metadata and bytes; a replaceable installer receives only
the retained verified read handle. The coordinator owns no network client,
signing private key, or installer implementation.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from .update_security import (
    SignatureVerifier,
    TrustedTimeSource,
    UpdateSecurityError,
    VerifiedUpdate,
    open_verified_update,
    verify_update_package,
)

_MAX_STATUS_TEXT = 600


class ReleaseUpdateError(RuntimeError):
    """Sanitized application-boundary error for release update work."""


@dataclass(frozen=True, slots=True)
class StagedUpdate:
    """One channel-staged update candidate."""

    metadata: bytes
    package_path: Path
    source_url: str

    def __post_init__(self) -> None:
        if type(self.metadata) is not bytes or not self.metadata:
            raise ValueError("staged update metadata must be non-empty bytes")
        if type(self.package_path) is not Path:
            raise TypeError("staged update package_path must be Path")
        if type(self.source_url) is not str or not self.source_url:
            raise ValueError("staged update source_url must be non-empty text")


class ReleaseUpdateChannel(Protocol):
    def stage(self, *, current_version: str) -> StagedUpdate | None:
        ...


class ReleaseUpdateInstaller(Protocol):
    def install(self, *, version: str, stream: BinaryIO) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class ReleaseUpdateSnapshot:
    state: str
    current_version: str
    target_version: str | None
    announcement: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "state": self.state,
            "current_version": self.current_version,
            "target_version": self.target_version,
            "announcement": self.announcement,
        }


class ReleaseUpdateCenter:
    """Fail-closed coordinator for one application process.

    check() accepts only a candidate that passes signed metadata, version,
    trusted-time, source URL, size and SHA-256 policy. apply() revalidates the
    same bytes immediately before the installer consumes the retained handle.
    Downgrade/rollback policy is inherited from verify_update_package.
    """

    def __init__(
        self,
        *,
        current_version: str,
        channel: ReleaseUpdateChannel,
        verifier: SignatureVerifier,
        time_source: TrustedTimeSource,
        installer: ReleaseUpdateInstaller,
    ) -> None:
        if type(current_version) is not str or not current_version:
            raise ValueError("current_version must be non-empty text")
        if not callable(getattr(channel, "stage", None)):
            raise TypeError("channel must implement ReleaseUpdateChannel")
        if not callable(getattr(verifier, "verify", None)):
            raise TypeError("verifier must implement SignatureVerifier")
        if not callable(getattr(time_source, "utc_now", None)):
            raise TypeError("time_source must implement TrustedTimeSource")
        if not callable(getattr(installer, "install", None)):
            raise TypeError("installer must implement ReleaseUpdateInstaller")
        self._current_version = current_version
        self._channel = channel
        self._verifier = verifier
        self._time_source = time_source
        self._installer = installer
        self._verified: VerifiedUpdate | None = None
        self._busy = False

    @property
    def current_version(self) -> str:
        return self._current_version

    @property
    def target_version(self) -> str | None:
        return None if self._verified is None else self._verified.version

    def snapshot(self, *, language: str = "uk") -> ReleaseUpdateSnapshot:
        lang = _language(language)
        if self._busy:
            state = "busy"
            message = {
                "uk": "Операція оновлення виконується.",
                "en": "An update operation is in progress.",
            }[lang]
        elif self._verified is not None:
            state = "ready"
            message = {
                "uk": f"Оновлення {self._verified.version} перевірено й готове до встановлення.",
                "en": f"Update {self._verified.version} is verified and ready to install.",
            }[lang]
        else:
            state = "idle"
            message = {
                "uk": f"Поточна версія {self._current_version}. Перевірене оновлення не підготовлено.",
                "en": f"Current version {self._current_version}. No verified update is staged.",
            }[lang]
        return ReleaseUpdateSnapshot(
            state=state,
            current_version=self._current_version,
            target_version=self.target_version,
            announcement=_bounded_status(message),
        )

    def check(self, *, language: str = "uk") -> ReleaseUpdateSnapshot:
        lang = _language(language)
        self._enter()
        try:
            try:
                candidate = self._channel.stage(current_version=self._current_version)
            except Exception as exc:
                raise ReleaseUpdateError(
                    {"uk": "Не вдалося перевірити наявність оновлень.",
                     "en": "Could not check for updates."}[lang]
                ) from exc
            if candidate is None:
                self._verified = None
                return ReleaseUpdateSnapshot(
                    state="current",
                    current_version=self._current_version,
                    target_version=None,
                    announcement={"uk": "Встановлено актуальну версію.",
                                  "en": "The installed version is current."}[lang],
                )
            if type(candidate) is not StagedUpdate:
                raise ReleaseUpdateError(
                    {"uk": "Канал оновлень повернув некоректні дані.",
                     "en": "The update channel returned invalid data."}[lang]
                )
            try:
                verified = verify_update_package(
                    candidate.metadata,
                    candidate.package_path,
                    current_version=self._current_version,
                    verifier=self._verifier,
                    time_source=self._time_source,
                )
            except (UpdateSecurityError, TypeError, ValueError) as exc:
                self._verified = None
                raise ReleaseUpdateError(
                    {"uk": "Оновлення не пройшло перевірку безпеки.",
                     "en": "The update failed security verification."}[lang]
                ) from exc
            if candidate.source_url != verified.download_url:
                self._verified = None
                raise ReleaseUpdateError(
                    {"uk": "Джерело оновлення не відповідає підписаним даним.",
                     "en": "The update source does not match signed metadata."}[lang]
                )
            self._verified = verified
            return ReleaseUpdateSnapshot(
                state="ready",
                current_version=self._current_version,
                target_version=verified.version,
                announcement={
                    "uk": f"Оновлення {verified.version} перевірено й готове до встановлення.",
                    "en": f"Update {verified.version} is verified and ready to install.",
                }[lang],
            )
        finally:
            self._leave()

    def apply(self, *, language: str = "uk") -> ReleaseUpdateSnapshot:
        lang = _language(language)
        verified = self._verified
        if verified is None:
            raise ReleaseUpdateError(
                {"uk": "Спочатку перевірте наявність оновлень.",
                 "en": "Check for updates before installing."}[lang]
            )
        self._enter()
        self._verified = None
        try:
            try:
                with open_verified_update(verified, time_source=self._time_source) as stream:
                    installed = self._installer.install(
                        version=verified.version,
                        stream=stream,
                    )
            except Exception as exc:
                raise ReleaseUpdateError(
                    {"uk": "Не вдалося безпечно встановити оновлення. Дані користувача не змінювалися цим модулем.",
                     "en": "The update could not be installed safely. This module did not modify user data."}[lang]
                ) from exc
            if installed is not True:
                raise ReleaseUpdateError(
                    {"uk": "Інсталятор не підтвердив успішне оновлення.",
                     "en": "The installer did not confirm a successful update."}[lang]
                )
            return ReleaseUpdateSnapshot(
                state="installed",
                current_version=self._current_version,
                target_version=verified.version,
                announcement={
                    "uk": f"Оновлення {verified.version} передано перевіреному інсталятору.",
                    "en": f"Update {verified.version} was handed to the verified installer.",
                }[lang],
            )
        finally:
            self._leave()

    def _enter(self) -> None:
        if self._busy:
            raise ReleaseUpdateError("update operation is already in progress")
        self._busy = True

    def _leave(self) -> None:
        self._busy = False


def _language(value: str) -> str:
    if type(value) is not str or value not in {"uk", "en"}:
        raise ValueError("language must be 'uk' or 'en'")
    return value


def _bounded_status(value: str) -> str:
    if type(value) is not str or not value or len(value) > _MAX_STATUS_TEXT:
        raise ValueError("release status text is invalid")
    if "\x00" in value:
        raise ValueError("release status text contains NUL")
    return value


__all__ = [
    "ReleaseUpdateCenter",
    "ReleaseUpdateChannel",
    "ReleaseUpdateError",
    "ReleaseUpdateInstaller",
    "ReleaseUpdateSnapshot",
    "StagedUpdate",
]
