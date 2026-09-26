from __future__ import annotations

"""Local install/update/uninstall authority for versioned sound packs.

Remote acquisition is deliberately outside this module.  A provider downloads and
extracts into a private staging directory; this store treats that directory as
untrusted input and validates every byte it publishes.
"""

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .sound_profiles import (
    SOUND_PACK_MANIFEST_SCHEMA_VERSION,
    SoundPackCatalogEntry,
    SoundPackManifest,
    SoundProfileStore,
)


SOUND_PACK_MANIFEST_FILENAME = "manifest.json"
PRODUCT_SOUND_API_VERSION = 1
DEFAULT_MAX_PACK_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_ASSET_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_FILES = 128


class SoundPackAcquisitionPort(Protocol):
    """Optional provider-neutral remote acquisition seam.

    Implementations must verify the catalogue archive size/digest before returning
    an extracted private staging directory.  The local store then performs its own
    manifest/path/per-file integrity validation before publication.
    """

    def acquire(self, entry: SoundPackCatalogEntry, *, staging_parent: Path) -> Path: ...


@dataclass(frozen=True)
class InstalledSoundPack:
    pack_id: str
    valid: bool
    version: str | None = None
    title: str | None = None
    license_id: str | None = None
    author: str | None = None
    provenance: str | None = None
    error: str = ""


@dataclass(frozen=True)
class SoundPackCatalogState:
    pack_id: str
    installed: bool
    update_available: bool
    compatible: bool
    installed_version: str | None
    catalog_version: str
    reason: str = ""


def _digest_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _sync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


class SoundPackStore:
    """Strict local pack store rooted below the user's data directory."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_pack_bytes: int = DEFAULT_MAX_PACK_BYTES,
        max_asset_bytes: int = DEFAULT_MAX_ASSET_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> None:
        self.root = Path(root)
        for name, value in (
            ("max_pack_bytes", max_pack_bytes),
            ("max_asset_bytes", max_asset_bytes),
            ("max_files", max_files),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if max_asset_bytes > max_pack_bytes:
            raise ValueError("max_asset_bytes cannot exceed max_pack_bytes")
        self.max_pack_bytes = max_pack_bytes
        self.max_asset_bytes = max_asset_bytes
        self.max_files = max_files

    @staticmethod
    def _pack_id(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("pack_id must be text")
        text = value.strip().lower()
        allowed = "abcdefghijklmnopqrstuvwxyz0123456789_.-"
        if not text or any(ch not in allowed for ch in text):
            raise ValueError("invalid sound pack id")
        if text == "classic":
            return text
        return text

    def _pack_dir(self, pack_id: str) -> Path:
        key = self._pack_id(pack_id)
        if key == "classic":
            raise ValueError("built-in classic sound pack is not stored in the user pack store")
        return self.root / key

    @staticmethod
    def _read_manifest(path: Path) -> SoundPackManifest:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("sound pack manifest must contain a JSON object")
        return SoundPackManifest.from_mapping(raw)

    def load_manifest(self, pack_id: str) -> SoundPackManifest:
        directory = self._pack_dir(pack_id)
        if not directory.is_dir() or directory.is_symlink():
            raise FileNotFoundError(f"sound pack is not installed: {pack_id}")
        manifest_path = directory / SOUND_PACK_MANIFEST_FILENAME
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise FileNotFoundError(f"sound pack manifest missing: {pack_id}")
        manifest = self._read_manifest(manifest_path)
        if manifest.pack_id != self._pack_id(pack_id):
            raise ValueError("installed sound pack id does not match directory")
        return manifest

    def _validate_staging(self, staging_dir: Path) -> SoundPackManifest:
        if not staging_dir.is_dir() or staging_dir.is_symlink():
            raise ValueError("sound pack staging root must be a real directory")
        manifest_path = staging_dir / SOUND_PACK_MANIFEST_FILENAME
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise FileNotFoundError("sound pack staging manifest is missing")
        manifest = self._read_manifest(manifest_path)
        if manifest.pack_id == "classic":
            raise ValueError("built-in classic sound pack cannot be replaced")

        unique_paths: dict[str, str] = {}
        for sound_id, relative in manifest.files.items():
            expected = manifest.sha256[sound_id]
            previous = unique_paths.get(relative)
            if previous is not None and previous != expected:
                raise ValueError("one sound asset path has conflicting digests")
            unique_paths[relative] = expected
        if len(unique_paths) > self.max_files:
            raise ValueError("sound pack contains too many audio assets")

        allowed = {SOUND_PACK_MANIFEST_FILENAME, *unique_paths.keys()}
        total_bytes = manifest_path.stat().st_size
        if total_bytes > self.max_pack_bytes:
            raise ValueError("sound pack exceeds maximum size")

        for item in staging_dir.rglob("*"):
            if item.is_symlink():
                raise ValueError("sound pack must not contain symlinks")
            if item.is_dir():
                continue
            if not item.is_file():
                raise ValueError("sound pack contains a non-regular filesystem entry")
            relative = item.relative_to(staging_dir).as_posix()
            if relative not in allowed:
                raise ValueError(f"unexpected file in sound pack: {relative}")

        for relative, expected in unique_paths.items():
            asset = staging_dir / Path(relative)
            if not asset.is_file() or asset.is_symlink():
                raise FileNotFoundError(f"sound pack asset missing: {relative}")
            size = asset.stat().st_size
            if size <= 0:
                raise ValueError(f"sound pack asset is empty: {relative}")
            if size > self.max_asset_bytes:
                raise ValueError(f"sound pack asset exceeds size limit: {relative}")
            total_bytes += size
            if total_bytes > self.max_pack_bytes:
                raise ValueError("sound pack exceeds maximum size")
            actual = _digest_file(asset)
            if actual != expected:
                raise ValueError(f"sound pack asset digest mismatch: {relative}")

        return manifest

    def install_from_staging(self, staging_dir: str | Path) -> SoundPackManifest:
        staging = Path(staging_dir)
        manifest = self._validate_staging(staging)
        self.root.mkdir(parents=True, exist_ok=True)

        final = self._pack_dir(manifest.pack_id)
        transaction = self.root / f".{manifest.pack_id}.install-{uuid.uuid4().hex}"
        backup = self.root / f".{manifest.pack_id}.backup-{uuid.uuid4().hex}"
        if transaction.exists() or backup.exists():
            raise RuntimeError("sound pack transaction path collision")

        try:
            transaction.mkdir()
            for relative in sorted(set(manifest.files.values())):
                source = staging / Path(relative)
                destination = transaction / Path(relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                _sync_file(destination)

            manifest_payload = json.dumps(
                manifest.to_mapping(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n"
            published_manifest = transaction / SOUND_PACK_MANIFEST_FILENAME
            with published_manifest.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(manifest_payload)
                handle.flush()
                os.fsync(handle.fileno())

            # Re-validate the exact bytes about to be published, not only the caller's
            # staging tree.
            self._validate_staging(transaction)

            had_previous = final.exists()
            if had_previous:
                if not final.is_dir() or final.is_symlink():
                    raise ValueError("existing sound pack target is not a safe directory")
                os.replace(final, backup)
            try:
                os.replace(transaction, final)
            except Exception:
                if had_previous and backup.exists() and not final.exists():
                    os.replace(backup, final)
                raise
            if backup.exists():
                shutil.rmtree(backup)
            return manifest
        finally:
            if transaction.exists():
                shutil.rmtree(transaction, ignore_errors=True)
            if backup.exists() and final.exists():
                shutil.rmtree(backup, ignore_errors=True)

    def resolve(self, pack_id: str, sound_id: str) -> Path:
        manifest = self.load_manifest(pack_id)
        relative = manifest.sound_path(sound_id)
        expected = manifest.sound_sha256(sound_id)
        root = self._pack_dir(pack_id).resolve()
        path = (root / Path(relative)).resolve()
        if root not in path.parents:
            raise ValueError("sound asset escapes installed pack root")
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"sound pack asset missing: {pack_id}/{relative}")
        if path.stat().st_size > self.max_asset_bytes:
            raise ValueError("installed sound asset exceeds size limit")
        if _digest_file(path) != expected:
            raise ValueError("installed sound asset digest mismatch")
        return path

    def verify_installed(self, pack_id: str) -> SoundPackManifest:
        """Verify the complete installed pack, including every published asset."""

        manifest = self.load_manifest(pack_id)
        for sound_id in manifest.files:
            self.resolve(manifest.pack_id, sound_id)
        return manifest

    def uninstall(
        self,
        pack_id: str,
        *,
        profile_store: SoundProfileStore | None = None,
    ) -> bool:
        key = self._pack_id(pack_id)
        if key == "classic":
            raise ValueError("built-in classic sound pack cannot be uninstalled")
        final = self._pack_dir(key)
        if not final.exists():
            return False
        if not final.is_dir() or final.is_symlink():
            raise ValueError("installed sound pack target is not a safe directory")

        if profile_store is not None:
            if not isinstance(profile_store, SoundProfileStore):
                raise TypeError("profile_store must be SoundProfileStore")
            profile = profile_store.load()
            if profile.pack_id == key:
                # Publish a safe profile before removing the bytes it references.
                profile_store.save(profile.with_pack("classic", clear_sound_ids=True))

        tombstone = self.root / f".{key}.remove-{uuid.uuid4().hex}"
        os.replace(final, tombstone)
        try:
            shutil.rmtree(tombstone)
        except Exception:
            # The pack is already unreachable by its canonical name.  Surface cleanup
            # failure rather than silently claiming a complete uninstall.
            raise
        return True

    def installed(self) -> tuple[InstalledSoundPack, ...]:
        if not self.root.is_dir():
            return ()
        records: list[InstalledSoundPack] = []
        for child in sorted(self.root.iterdir(), key=lambda item: item.name.casefold()):
            if child.name.startswith(".") or not child.is_dir():
                continue
            try:
                manifest = self.verify_installed(child.name)
            except Exception as exc:
                records.append(
                    InstalledSoundPack(
                        pack_id=child.name,
                        valid=False,
                        error=str(exc).strip() or type(exc).__name__,
                    )
                )
            else:
                records.append(
                    InstalledSoundPack(
                        pack_id=manifest.pack_id,
                        valid=True,
                        version=manifest.version,
                        title=manifest.title,
                        license_id=manifest.license_id,
                        author=manifest.author,
                        provenance=manifest.provenance,
                    )
                )
        return tuple(records)

    def catalog_state(
        self,
        entry: SoundPackCatalogEntry,
        *,
        product_sound_api: int = PRODUCT_SOUND_API_VERSION,
    ) -> SoundPackCatalogState:
        if not isinstance(entry, SoundPackCatalogEntry):
            raise TypeError("entry must be SoundPackCatalogEntry")
        if isinstance(product_sound_api, bool) or not isinstance(product_sound_api, int):
            raise TypeError("product_sound_api must be an integer")
        compatible = (
            entry.min_product_sound_api
            <= product_sound_api
            <= entry.max_product_sound_api
        )
        try:
            manifest = self.verify_installed(entry.pack_id)
        except FileNotFoundError:
            return SoundPackCatalogState(
                pack_id=entry.pack_id,
                installed=False,
                update_available=False,
                compatible=compatible,
                installed_version=None,
                catalog_version=entry.version,
                reason="" if compatible else "incompatible_product_sound_api",
            )
        except Exception as exc:
            return SoundPackCatalogState(
                pack_id=entry.pack_id,
                installed=True,
                update_available=compatible,
                compatible=compatible,
                installed_version=None,
                catalog_version=entry.version,
                reason=f"invalid_installed_pack:{type(exc).__name__}",
            )

        update = compatible and manifest.version != entry.version
        return SoundPackCatalogState(
            pack_id=entry.pack_id,
            installed=True,
            update_available=update,
            compatible=compatible,
            installed_version=manifest.version,
            catalog_version=entry.version,
            reason="" if compatible else "incompatible_product_sound_api",
        )


class SoundPackInstallService:
    """Compose an optional acquisition provider with the strict local publisher."""

    def __init__(
        self,
        store: SoundPackStore,
        acquisition: SoundPackAcquisitionPort,
        *,
        staging_parent: str | Path,
    ) -> None:
        if not isinstance(store, SoundPackStore):
            raise TypeError("store must be SoundPackStore")
        if isinstance(acquisition, type) or not callable(
            getattr(acquisition, "acquire", None)
        ):
            raise TypeError("acquisition must expose acquire")
        self.store = store
        self.acquisition = acquisition
        self.staging_parent = Path(staging_parent)

    def install(self, entry: SoundPackCatalogEntry) -> SoundPackManifest:
        if not isinstance(entry, SoundPackCatalogEntry):
            raise TypeError("entry must be SoundPackCatalogEntry")
        state = self.store.catalog_state(entry)
        if not state.compatible:
            raise ValueError("sound pack is incompatible with this product sound API")
        self.staging_parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            self.acquisition.acquire(entry, staging_parent=self.staging_parent)
        )
        try:
            candidate = self.store._validate_staging(staging)
            if candidate.pack_id != entry.pack_id or candidate.version != entry.version:
                raise ValueError(
                    "acquired sound pack identity does not match catalogue entry"
                )
            manifest = self.store.install_from_staging(staging)
        finally:
            # Acquired staging is private scratch owned by this service.
            try:
                if (
                    staging.is_dir()
                    and self.staging_parent.resolve() in staging.resolve().parents
                ):
                    shutil.rmtree(staging)
            except Exception:
                pass
        return manifest
