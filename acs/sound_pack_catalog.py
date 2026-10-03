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
from types import MappingProxyType
from typing import Mapping, Protocol
from urllib.parse import urlsplit

from .sound_profiles import (
    SoundPackManifest,
    SoundProfile,
    _safe_audio_path,
    _semantic_version_key,
)


DEFAULT_MAX_SOUND_PACK_BYTES = 32 * 1024 * 1024
SOUND_PACK_RIGHTS_SCHEMA_VERSION = 1
_MAX_SOUND_PACK_SIGNATURE_CHARS = 16 * 1024
_MAX_RIGHTS_EVIDENCE_URI_CHARS = 4096
_MAX_RIGHTS_EVIDENCE_LICENSE_CHARS = 256
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SoundPackInstallError(ValueError):
    """Raised when an install/update cannot be proven safe enough to commit."""


@dataclass(frozen=True)
class SoundAssetDigest:
    path: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        path = _safe_audio_path(self.path)
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise TypeError("sound asset size_bytes must be an integer")
        if self.size_bytes <= 0:
            raise ValueError("sound asset size_bytes must be positive")
        if not isinstance(self.sha256, str):
            raise TypeError("sound asset sha256 must be text")
        digest = self.sha256.strip()
        if digest != self.sha256 or not _SHA256_RE.fullmatch(digest):
            raise ValueError("sound asset sha256 must be 64 lowercase hex characters")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "sha256", digest)


def _auditable_rights_uri(label: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"sound pack rights {label} must be text")
    text = value.strip()
    if not text:
        raise ValueError(f"sound pack rights {label} is required")
    if text != value:
        raise ValueError(f"sound pack rights {label} must not contain surrounding whitespace")
    if len(text) > _MAX_RIGHTS_EVIDENCE_URI_CHARS:
        raise ValueError(f"sound pack rights {label} exceeds the resource limit")
    if any(
        ch.isspace()
        or ord(ch) < 32
        or ord(ch) == 127
        or ch in {"\u2028", "\u2029"}
        for ch in text
    ):
        raise ValueError(f"sound pack rights {label} contains whitespace or control characters")
    parsed = urlsplit(text)
    if parsed.query or parsed.fragment:
        raise ValueError(
            f"sound pack rights {label} must not contain query or fragment components"
        )
    if parsed.scheme == "https":
        try:
            hostname = parsed.hostname
            parsed.port
        except ValueError as exc:
            raise ValueError(
                f"sound pack rights {label} must be an auditable HTTPS URL or URN"
            ) from exc
        if (
            not parsed.netloc
            or hostname is None
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(
                f"sound pack rights {label} must be an auditable HTTPS URL or URN"
            )
    elif parsed.scheme == "urn":
        if parsed.netloc or not parsed.path:
            raise ValueError(
                f"sound pack rights {label} must be an auditable HTTPS URL or URN"
            )
    else:
        raise ValueError(
            f"sound pack rights {label} must be an auditable HTTPS URL or URN"
        )
    return text


@dataclass(frozen=True)
class SoundPackRightsEvidence:
    """Catalog-level auditable license/provenance references.

    The manifest remains the downloaded metadata authority.  This record is
    separate so a provider cannot make arbitrary non-empty prose satisfy the
    install-time redistribution/provenance gate.
    """

    license_id: str
    source_uri: str
    license_uri: str

    def __post_init__(self) -> None:
        if not isinstance(self.license_id, str):
            raise TypeError("sound pack rights license_id must be text")
        license_id = self.license_id.strip()
        if not license_id:
            raise ValueError("sound pack rights license_id is required")
        if len(license_id) > _MAX_RIGHTS_EVIDENCE_LICENSE_CHARS:
            raise ValueError("sound pack rights license_id exceeds the resource limit")
        if any(
            ord(ch) < 32 or ord(ch) == 127 or ch in {"\u2028", "\u2029"}
            for ch in license_id
        ):
            raise ValueError("sound pack rights license_id contains control characters")
        object.__setattr__(self, "license_id", license_id)
        object.__setattr__(
            self,
            "source_uri",
            _auditable_rights_uri("source_uri", self.source_uri),
        )
        object.__setattr__(
            self,
            "license_uri",
            _auditable_rights_uri("license_uri", self.license_uri),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": SOUND_PACK_RIGHTS_SCHEMA_VERSION,
            "license_id": self.license_id,
            "source_uri": self.source_uri,
            "license_uri": self.license_uri,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "SoundPackRightsEvidence":
        if not isinstance(raw, Mapping) or any(type(key) is not str for key in raw):
            raise TypeError("sound pack rights evidence must be an object with text keys")
        if set(raw) != {
            "schema_version",
            "license_id",
            "source_uri",
            "license_uri",
        }:
            raise ValueError("sound pack rights evidence fields are invalid")
        schema = raw["schema_version"]
        if type(schema) is not int or schema != SOUND_PACK_RIGHTS_SCHEMA_VERSION:
            raise ValueError(f"unsupported sound pack rights schema: {schema}")
        if any(
            type(raw[name]) is not str
            for name in ("license_id", "source_uri", "license_uri")
        ):
            raise TypeError("sound pack rights evidence must contain text fields")
        return cls(
            license_id=raw["license_id"],
            source_uri=raw["source_uri"],
            license_uri=raw["license_uri"],
        )


@dataclass(frozen=True)
class SoundPackCatalogEntry:
    manifest: SoundPackManifest
    assets: Mapping[str, SoundAssetDigest]
    total_bytes: int
    compatible: bool = True
    signature: str | None = None
    rights_evidence: SoundPackRightsEvidence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, SoundPackManifest):
            raise TypeError("manifest must be SoundPackManifest")
        if not isinstance(self.compatible, bool):
            raise TypeError("compatible must be boolean")
        if isinstance(self.total_bytes, bool) or not isinstance(self.total_bytes, int):
            raise TypeError("total_bytes must be an integer")
        if self.total_bytes < 0:
            raise ValueError("total_bytes cannot be negative")
        if not isinstance(self.assets, Mapping):
            raise TypeError("assets must be a mapping")
        normalized: dict[str, SoundAssetDigest] = {}
        for path, digest in self.assets.items():
            if not isinstance(path, str):
                raise TypeError("asset mapping keys must be text")
            if not isinstance(digest, SoundAssetDigest):
                raise TypeError("assets must contain SoundAssetDigest values")
            key = _safe_audio_path(path)
            if key != digest.path:
                raise ValueError("asset mapping key must match digest path")
            if key in normalized:
                raise ValueError("duplicate normalized sound asset path")
            normalized[key] = digest
        required_paths = set(self.manifest.files.values())
        if set(normalized) != required_paths:
            raise ValueError("catalog asset digests must exactly cover manifest audio files")
        if sum(item.size_bytes for item in normalized.values()) != self.total_bytes:
            raise ValueError("catalog total_bytes must equal the sum of asset sizes")
        if self.rights_evidence is not None:
            if not isinstance(self.rights_evidence, SoundPackRightsEvidence):
                raise TypeError("rights_evidence must be SoundPackRightsEvidence or null")
            if self.rights_evidence.license_id != self.manifest.license_id:
                raise ValueError(
                    "sound pack rights license_id must match manifest license_id"
                )
        if self.signature is not None and not isinstance(self.signature, str):
            raise TypeError("signature must be text or null")
        signature = None if self.signature is None else self.signature.strip()
        if signature == "":
            raise ValueError("signature cannot be blank")
        if self.signature is not None and signature != self.signature:
            raise ValueError("signature must not contain surrounding whitespace")
        if signature is not None and len(signature) > _MAX_SOUND_PACK_SIGNATURE_CHARS:
            raise ValueError("signature exceeds the resource limit")
        if signature is not None and any(
            ord(ch) < 32 or ord(ch) == 127 or ch in {"\u2028", "\u2029"}
            for ch in signature
        ):
            raise ValueError("signature contains control characters")
        object.__setattr__(self, "assets", MappingProxyType(normalized))
        object.__setattr__(self, "signature", signature)


@dataclass(frozen=True)
class DownloadedSoundPack:
    """Opaque staged download plus adapter-calculated asset digests."""

    manifest: SoundPackManifest
    assets: Mapping[str, SoundAssetDigest]
    total_bytes: int
    payload_ref: object
    rights_evidence: SoundPackRightsEvidence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, SoundPackManifest):
            raise TypeError("downloaded manifest must be SoundPackManifest")
        if isinstance(self.total_bytes, bool) or not isinstance(self.total_bytes, int):
            raise TypeError("downloaded total_bytes must be an integer")
        if self.total_bytes < 0:
            raise ValueError("downloaded total_bytes cannot be negative")
        if not isinstance(self.assets, Mapping):
            raise TypeError("downloaded assets must be a mapping")
        if self.rights_evidence is not None and not isinstance(
            self.rights_evidence, SoundPackRightsEvidence
        ):
            raise TypeError(
                "downloaded rights_evidence must be SoundPackRightsEvidence or null"
            )
        snapshot: dict[str, SoundAssetDigest] = {}
        for path, digest in self.assets.items():
            if type(path) is not str:
                raise TypeError("downloaded asset keys must be text")
            if not isinstance(digest, SoundAssetDigest):
                raise TypeError(
                    "downloaded assets must contain SoundAssetDigest values"
                )
            key = _safe_audio_path(path)
            if key != digest.path:
                raise ValueError("downloaded asset key must match digest path")
            if key in snapshot:
                raise ValueError("duplicate normalized downloaded asset path")
            snapshot[key] = digest
        object.__setattr__(
            self,
            "assets",
            MappingProxyType(snapshot),
        )


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
    CATALOG_OLDER = "catalog_older"
    VERSION_CONFLICT = "version_conflict"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class SoundPackCatalogStatus:
    pack_id: str
    catalog_version: str
    installed_version: str | None
    state: SoundPackState


@dataclass(frozen=True)
class SoundPackUninstallPlan:
    """Pure plan so profile persistence can happen before destructive storage work."""

    pack_id: str
    resulting_profile: SoundProfile
    remove_from_storage: bool


class SoundPackManager:
    def __init__(
        self,
        downloader: SoundPackDownloadPort,
        storage: SoundPackStoragePort,
        *,
        signature_verifier: SoundPackSignatureVerifier | None = None,
        max_bytes: int = DEFAULT_MAX_SOUND_PACK_BYTES,
        fallback_pack_id: str = "classic",
        external_fallback_available: bool = False,
    ) -> None:
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
            raise TypeError("max_bytes must be an integer")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if type(external_fallback_available) is not bool:
            raise TypeError("external_fallback_available must be boolean")
        if isinstance(downloader, type) or not callable(
            getattr(downloader, "download", None)
        ):
            raise TypeError("downloader must expose callable download")
        if isinstance(storage, type) or any(
            not callable(getattr(storage, name, None))
            for name in ("installed", "install_atomically", "uninstall")
        ):
            raise TypeError(
                "storage must expose installed, install_atomically and uninstall"
            )
        if signature_verifier is not None and (
            isinstance(signature_verifier, type)
            or not callable(getattr(signature_verifier, "verify", None))
        ):
            raise TypeError("signature_verifier must expose callable verify or be None")
        fallback_pack_id = SoundProfile(pack_id=fallback_pack_id).pack_id
        self._downloader = downloader
        self._storage = storage
        self._signature_verifier = signature_verifier
        self._max_bytes = max_bytes
        self._fallback_pack_id = fallback_pack_id
        self._external_fallback_available = external_fallback_available

    @property
    def fallback_pack_id(self) -> str:
        return self._fallback_pack_id

    def _installed_manifests(self) -> dict[str, SoundPackManifest]:
        raw = self._storage.installed()
        if not isinstance(raw, Mapping):
            raise SoundPackInstallError("installed sound pack inventory is invalid")
        installed: dict[str, SoundPackManifest] = {}
        for pack_id, manifest in raw.items():
            if type(pack_id) is not str or not isinstance(
                manifest, SoundPackManifest
            ):
                raise SoundPackInstallError(
                    "installed sound pack metadata is invalid"
                )
            canonical_pack_id = SoundProfile(pack_id=pack_id).pack_id
            if pack_id != canonical_pack_id or manifest.pack_id != pack_id:
                raise SoundPackInstallError(
                    "installed sound pack identity is invalid"
                )
            if pack_id in installed:
                raise SoundPackInstallError(
                    "installed sound pack inventory contains duplicate identity"
                )
            installed[pack_id] = manifest
        return installed

    def install(self, entry: SoundPackCatalogEntry) -> SoundPackManifest:
        if not entry.compatible:
            raise SoundPackInstallError("sound pack is incompatible with this application")
        if entry.rights_evidence is None:
            raise SoundPackInstallError(
                "sound pack lacks auditable license/provenance evidence"
            )
        if entry.total_bytes > self._max_bytes:
            raise SoundPackInstallError("sound pack exceeds the configured size limit")
        current = self._installed_manifests().get(entry.manifest.pack_id)
        if current is not None:
            if not isinstance(current, SoundPackManifest):
                raise SoundPackInstallError("installed sound pack metadata is invalid")
            if current.version == entry.manifest.version:
                if current != entry.manifest:
                    raise SoundPackInstallError(
                        "sound pack catalog metadata conflicts with the installed version"
                    )
                raise SoundPackInstallError(
                    "sound pack catalog version is already installed"
                )
            if _semantic_version_key(current.version) > _semantic_version_key(
                entry.manifest.version
            ):
                raise SoundPackInstallError(
                    "sound pack catalog version is older than the installed version"
                )

        downloaded = self._downloader.download(entry, max_bytes=self._max_bytes)
        self._validate_download(entry, downloaded)
        if downloaded.rights_evidence is not None:
            raise SoundPackInstallError(
                "download port must not supply sound pack rights authority"
            )
        if entry.signature is not None:
            if self._signature_verifier is None:
                raise SoundPackInstallError("signed sound pack requires a signature verifier")
            verified = self._signature_verifier.verify(entry, downloaded)
            if type(verified) is not bool:
                raise SoundPackInstallError(
                    "sound pack signature verifier returned an invalid result"
                )
            if not verified:
                raise SoundPackInstallError("sound pack signature verification failed")

        committed = replace(
            downloaded,
            rights_evidence=entry.rights_evidence,
        )
        self._storage.install_atomically(committed)
        return committed.manifest

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

    def installed_manifest(self, pack_id: str) -> SoundPackManifest | None:
        """Return the storage-verified active manifest for one installed pack."""

        requested = SoundProfile(pack_id=pack_id).pack_id
        current = self._installed_manifests().get(requested)
        if current is not None and not isinstance(current, SoundPackManifest):
            raise SoundPackInstallError("installed sound pack metadata is invalid")
        return current

    def _fallback_available(self, installed: Mapping[str, SoundPackManifest]) -> bool:
        return (
            self._fallback_pack_id in installed
            or self._external_fallback_available
        )

    def resolve_usable_pack(self, requested_pack_id: str) -> str:
        """Resolve against installed packs plus an optional external fallback authority."""

        requested = SoundProfile(pack_id=requested_pack_id).pack_id
        installed = self._installed_manifests()
        if requested in installed:
            return requested
        if requested == self._fallback_pack_id and self._external_fallback_available:
            return self._fallback_pack_id
        if not self._fallback_available(installed):
            raise SoundPackInstallError(
                "configured sound pack is missing and no fallback is available"
            )
        return self._fallback_pack_id

    def prepare_uninstall(
        self,
        pack_id: str,
        *,
        active_profile: SoundProfile,
    ) -> SoundPackUninstallPlan:
        """Validate uninstall and compute resulting profile without deleting assets."""

        if not isinstance(active_profile, SoundProfile):
            raise TypeError("active_profile must be SoundProfile")
        pack_id = SoundProfile(pack_id=pack_id).pack_id
        if pack_id == self._fallback_pack_id:
            raise SoundPackInstallError("the fallback sound pack cannot be uninstalled")
        installed = self._installed_manifests()
        if pack_id not in installed:
            return SoundPackUninstallPlan(
                pack_id=pack_id,
                resulting_profile=self.resolve_profile(active_profile),
                remove_from_storage=False,
            )
        if (
            active_profile.pack_id == pack_id
            and not self._fallback_available(installed)
        ):
            raise SoundPackInstallError(
                "cannot remove active pack without an available fallback"
            )
        resulting_profile = (
            active_profile.with_pack(self._fallback_pack_id)
            if active_profile.pack_id == pack_id
            else self.resolve_profile(active_profile)
        )
        return SoundPackUninstallPlan(
            pack_id=pack_id,
            resulting_profile=resulting_profile,
            remove_from_storage=True,
        )

    def commit_uninstall(self, plan: SoundPackUninstallPlan) -> None:
        if not isinstance(plan, SoundPackUninstallPlan):
            raise TypeError("plan must be SoundPackUninstallPlan")
        if plan.pack_id == self._fallback_pack_id:
            raise SoundPackInstallError("the fallback sound pack cannot be uninstalled")
        if plan.remove_from_storage:
            self._storage.uninstall(plan.pack_id)

    def uninstall(self, pack_id: str, *, active_profile: SoundProfile) -> SoundProfile:
        """Backward-compatible one-step uninstall.

        Application code that persists profiles should prefer ``prepare_uninstall``
        followed by profile persistence and ``commit_uninstall`` so a failed
        profile write cannot leave the active profile pointing at removed assets.
        """

        plan = self.prepare_uninstall(pack_id, active_profile=active_profile)
        self.commit_uninstall(plan)
        return plan.resulting_profile

    def resolve_profile(self, profile: SoundProfile) -> SoundProfile:
        resolved = self.resolve_usable_pack(profile.pack_id)
        if resolved == profile.pack_id:
            return profile
        return profile.with_pack(resolved)

    @staticmethod
    def status_for_installed_manifest(
        entry: SoundPackCatalogEntry,
        current: SoundPackManifest | None,
    ) -> SoundPackCatalogStatus:
        if not isinstance(entry, SoundPackCatalogEntry):
            raise TypeError("entry must be SoundPackCatalogEntry")
        if current is not None and not isinstance(current, SoundPackManifest):
            raise SoundPackInstallError("installed sound pack metadata is invalid")
        if current is not None and current.pack_id != entry.manifest.pack_id:
            raise SoundPackInstallError("installed sound pack id does not match catalog entry")
        if not entry.compatible:
            state = SoundPackState.INCOMPATIBLE
        elif current is None:
            state = SoundPackState.NOT_INSTALLED
        elif (
            current.version == entry.manifest.version
            and current != entry.manifest
        ):
            state = SoundPackState.VERSION_CONFLICT
        elif current.version == entry.manifest.version:
            state = SoundPackState.CURRENT
        elif _semantic_version_key(current.version) > _semantic_version_key(
            entry.manifest.version
        ):
            state = SoundPackState.CATALOG_OLDER
        else:
            state = SoundPackState.DIFFERENT_VERSION
        return SoundPackCatalogStatus(
            pack_id=entry.manifest.pack_id,
            catalog_version=entry.manifest.version,
            installed_version=None if current is None else current.version,
            state=state,
        )

    def status(self, entry: SoundPackCatalogEntry) -> SoundPackCatalogStatus:
        installed = self._installed_manifests()
        current = installed.get(entry.manifest.pack_id)
        return self.status_for_installed_manifest(entry, current)
