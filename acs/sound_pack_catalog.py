from __future__ import annotations

"""Provider-neutral sound-pack catalog and installation orchestration.

This module deliberately owns no filesystem, network, Windows audio or UI details.
Adapters download/stage bytes and install them atomically; Core validates catalog
identity, size, integrity and signature policy before storage is allowed to
commit a pack. Playback remains owned by ``SoundRuntime``/``GameSoundRuntime``.
"""

from dataclasses import dataclass, replace
from enum import Enum
import re
from typing import Mapping, Protocol

from .sound_profiles import SoundPackManifest, SoundProfile


DEFAULT_MAX_SOUND_PACK_BYTES = 32 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SoundPackInstallError(ValueError):
    """Raised when an install/update cannot be proven safe enough to commit."""


@dataclass(frozen=True)
class SoundAssetDigest:
    path: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        path = str(self.path).strip().replace("\\", "/")
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise ValueError("sound asset digest path must stay below pack root")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise TypeError("sound asset size_bytes must be an integer")
        if self.size_bytes < 0:
            raise ValueError("sound asset size_bytes cannot be negative")
        digest = str(self.sha256).strip().lower()
        if not _SHA256_RE.fullmatch(digest):
            raise ValueError("sound asset sha256 must be 64 lowercase hex characters")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "sha256", digest)


@dataclass(frozen=True)
class SoundPackCatalogEntry:
    manifest: SoundPackManifest
    assets: Mapping[str, SoundAssetDigest]
    total_bytes: int
    compatible: bool = True
    signature: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, SoundPackManifest):
            raise TypeError("manifest must be SoundPackManifest")
        if not isinstance(self.compatible, bool):
            raise TypeError("compatible must be boolean")
        if isinstance(self.total_bytes, bool) or not isinstance(self.total_bytes, int):
            raise TypeError("total_bytes must be an integer")
        if self.total_bytes < 0:
            raise ValueError("total_bytes cannot be negative")
        normalized: dict[str, SoundAssetDigest] = {}
        for path, digest in dict(self.assets).items():
            if not isinstance(digest, SoundAssetDigest):
                raise TypeError("assets must contain SoundAssetDigest values")
            key = str(path).strip().replace("\\", "/")
            if key != digest.path:
                raise ValueError("asset mapping key must match digest path")
            normalized[key] = digest
        required_paths = set(self.manifest.files.values())
        if set(normalized) != required_paths:
            raise ValueError("catalog asset digests must exactly cover manifest audio files")
        if sum(item.size_bytes for item in normalized.values()) != self.total_bytes:
            raise ValueError("catalog total_bytes must equal the sum of asset sizes")
        signature = None if self.signature is None else str(self.signature).strip()
        if signature == "":
            raise ValueError("signature cannot be blank")
        object.__setattr__(self, "assets", normalized)
        object.__setattr__(self, "signature", signature)


@dataclass(frozen=True)
class DownloadedSoundPack:
    """Opaque staged download plus adapter-calculated asset digests."""

    manifest: SoundPackManifest
    assets: Mapping[str, SoundAssetDigest]
    total_bytes: int
    payload_ref: object


class SoundPackDownloadPort(Protocol):
    def download(
        self,
        entry: SoundPackCatalogEntry,
        *,
        max_bytes: int,
    ) -> DownloadedSoundPack: ...


class SoundPackStoragePort(Protocol):
    def installed(self) -> Mapping[str, SoundPackManifest]: ...

    def install_atomically(self, downloaded: DownloadedSoundPack) -> None: ...

    def uninstall(self, pack_id: str) -> None: ...


class SoundPackSignatureVerifier(Protocol):
    def verify(
        self,
        entry: SoundPackCatalogEntry,
        downloaded: DownloadedSoundPack,
    ) -> bool: ...


class SoundPackState(str, Enum):
    NOT_INSTALLED = "not_installed"
    CURRENT = "current"
    DIFFERENT_VERSION = "different_version"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class SoundPackCatalogStatus:
    pack_id: str
    catalog_version: str
    installed_version: str | None
    state: SoundPackState


class SoundPackManager:
    def __init__(
        self,
        downloader: SoundPackDownloadPort,
        storage: SoundPackStoragePort,
        *,
        signature_verifier: SoundPackSignatureVerifier | None = None,
        max_bytes: int = DEFAULT_MAX_SOUND_PACK_BYTES,
        fallback_pack_id: str = "classic",
    ) -> None:
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
            raise TypeError("max_bytes must be an integer")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        fallback_pack_id = str(fallback_pack_id).strip().lower()
        if not fallback_pack_id:
            raise ValueError("fallback_pack_id is required")
        self._downloader = downloader
        self._storage = storage
        self._signature_verifier = signature_verifier
        self._max_bytes = max_bytes
        self._fallback_pack_id = fallback_pack_id

    def install(self, entry: SoundPackCatalogEntry) -> SoundPackManifest:
        if not entry.compatible:
            raise SoundPackInstallError("sound pack is incompatible with this application")
        if entry.total_bytes > self._max_bytes:
            raise SoundPackInstallError("sound pack exceeds the configured size limit")

        downloaded = self._downloader.download(entry, max_bytes=self._max_bytes)
        self._validate_download(entry, downloaded)
        if entry.signature is not None:
            if self._signature_verifier is None:
                raise SoundPackInstallError("signed sound pack requires a signature verifier")
            if not self._signature_verifier.verify(entry, downloaded):
                raise SoundPackInstallError("sound pack signature verification failed")

        self._storage.install_atomically(downloaded)
        return downloaded.manifest

    def _validate_download(
        self,
        entry: SoundPackCatalogEntry,
        downloaded: DownloadedSoundPack,
    ) -> None:
        if not isinstance(downloaded, DownloadedSoundPack):
            raise TypeError("download port must return DownloadedSoundPack")
        if downloaded.manifest != entry.manifest:
            raise SoundPackInstallError("downloaded manifest does not match catalog entry")
        if isinstance(downloaded.total_bytes, bool) or not isinstance(downloaded.total_bytes, int):
            raise SoundPackInstallError("downloaded total size is invalid")
        if downloaded.total_bytes < 0 or downloaded.total_bytes > self._max_bytes:
            raise SoundPackInstallError("downloaded sound pack exceeds the configured size limit")
        actual = dict(downloaded.assets)
        if set(actual) != set(entry.assets):
            raise SoundPackInstallError("downloaded asset set does not match catalog entry")
        for item in actual.values():
            if not isinstance(item, SoundAssetDigest):
                raise SoundPackInstallError("downloaded asset digest is invalid")
        if sum(item.size_bytes for item in actual.values()) != downloaded.total_bytes:
            raise SoundPackInstallError("downloaded asset sizes do not match total size")
        if downloaded.total_bytes != entry.total_bytes:
            raise SoundPackInstallError("downloaded size does not match catalog metadata")
        for path, expected in entry.assets.items():
            received = actual[path]
            if received.path != expected.path:
                raise SoundPackInstallError("downloaded asset path does not match catalog metadata")
            if received.size_bytes != expected.size_bytes:
                raise SoundPackInstallError("downloaded asset size does not match catalog metadata")
            if received.sha256 != expected.sha256:
                raise SoundPackInstallError("downloaded asset checksum verification failed")

    def uninstall(self, pack_id: str, *, active_profile: SoundProfile) -> SoundProfile:
        pack_id = str(pack_id).strip().lower()
        if pack_id == self._fallback_pack_id:
            raise SoundPackInstallError("the fallback sound pack cannot be uninstalled")
        installed = dict(self._storage.installed())
        if pack_id not in installed:
            return self.resolve_profile(active_profile)
        if active_profile.pack_id == pack_id and self._fallback_pack_id not in installed:
            raise SoundPackInstallError("cannot remove active pack without an installed fallback")
        self._storage.uninstall(pack_id)
        if active_profile.pack_id == pack_id:
            return replace(active_profile, pack_id=self._fallback_pack_id)
        return self.resolve_profile(active_profile)

    def resolve_profile(self, profile: SoundProfile) -> SoundProfile:
        installed = dict(self._storage.installed())
        if profile.pack_id in installed:
            return profile
        if self._fallback_pack_id not in installed:
            raise SoundPackInstallError("configured sound pack is missing and no fallback is installed")
        return replace(profile, pack_id=self._fallback_pack_id)

    def status(self, entry: SoundPackCatalogEntry) -> SoundPackCatalogStatus:
        installed = dict(self._storage.installed())
        current = installed.get(entry.manifest.pack_id)
        if not entry.compatible:
            state = SoundPackState.INCOMPATIBLE
        elif current is None:
            state = SoundPackState.NOT_INSTALLED
        elif current.version == entry.manifest.version:
            state = SoundPackState.CURRENT
        else:
            state = SoundPackState.DIFFERENT_VERSION
        return SoundPackCatalogStatus(
            pack_id=entry.manifest.pack_id,
            catalog_version=entry.manifest.version,
            installed_version=None if current is None else current.version,
            state=state,
        )
