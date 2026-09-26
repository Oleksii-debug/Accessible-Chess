from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from acs.sound_pack_store import (
    PRODUCT_SOUND_API_VERSION,
    SoundPackInstallService,
    SoundPackStore,
)
from acs.sound_profiles import (
    CORE_SOUND_EVENTS,
    SoundPackCatalogEntry,
    SoundPackManifest,
    SoundProfile,
    SoundProfileStore,
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_pack(
    root: Path,
    *,
    pack_id: str = "soft.wood",
    version: str = "1.0.0",
    payload_prefix: bytes = b"v1:",
) -> SoundPackManifest:
    files = {}
    hashes = {}
    for event in CORE_SOUND_EVENTS:
        relative = f"audio/{event}.wav"
        data = payload_prefix + event.encode("ascii")
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        files[event] = relative
        hashes[event] = _digest(data)

    manifest = SoundPackManifest(
        pack_id=pack_id,
        version=version,
        title="Soft Wood",
        author="Accessible Chess",
        license_id="CC0-1.0",
        provenance="https://example.invalid/source",
        files=files,
        sha256=hashes,
    )
    (root / "manifest.json").write_text(
        json.dumps(manifest.to_mapping()),
        encoding="utf-8",
    )
    return manifest


def _catalog(pack_id="soft.wood", version="1.0.0", **kwargs):
    values = {
        "pack_id": pack_id,
        "version": version,
        "title": "Soft Wood",
        "author": "Accessible Chess",
        "license_id": "CC0-1.0",
        "provenance": "https://example.invalid/source",
        "download_url": "https://cdn.example.invalid/soft-wood.zip",
        "archive_sha256": _digest(b"archive"),
        "archive_size_bytes": 1000,
        "min_product_sound_api": PRODUCT_SOUND_API_VERSION,
        "max_product_sound_api": PRODUCT_SOUND_API_VERSION,
    }
    values.update(kwargs)
    return SoundPackCatalogEntry(**values)


class SoundPackStoreTests(unittest.TestCase):
    def test_install_resolve_and_inventory_verify_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "staging"
            staging.mkdir()
            manifest = _write_pack(staging)
            store = SoundPackStore(root / "installed")

            installed = store.install_from_staging(staging)

            self.assertEqual(installed, manifest)
            path = store.resolve("soft.wood", "move")
            self.assertEqual(path.read_bytes(), b"v1:move")
            records = store.installed()
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0].valid)
            self.assertEqual(records[0].version, "1.0.0")
            self.assertEqual(records[0].license_id, "CC0-1.0")

    def test_digest_mismatch_fails_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "staging"
            staging.mkdir()
            _write_pack(staging)
            (staging / "audio" / "move.wav").write_bytes(b"tampered")
            store = SoundPackStore(root / "installed")

            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                store.install_from_staging(staging)

            self.assertFalse((root / "installed" / "soft.wood").exists())

    def test_unexpected_file_and_symlink_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "staging"
            staging.mkdir()
            _write_pack(staging)
            (staging / "payload.exe").write_bytes(b"MZ")
            store = SoundPackStore(root / "installed")
            with self.assertRaisesRegex(ValueError, "unexpected file"):
                store.install_from_staging(staging)

        if hasattr(os, "symlink"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                staging = root / "staging"
                staging.mkdir()
                _write_pack(staging)
                target = root / "outside.wav"
                target.write_bytes(b"x")
                link = staging / "linked.wav"
                try:
                    os.symlink(target, link)
                except (OSError, NotImplementedError):
                    self.skipTest("symlink creation unavailable")
                store = SoundPackStore(root / "installed")
                with self.assertRaisesRegex(ValueError, "symlink"):
                    store.install_from_staging(staging)

    def test_update_replaces_complete_pack_and_old_bytes_do_not_survive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SoundPackStore(root / "installed")
            one = root / "one"
            one.mkdir()
            _write_pack(one, version="1.0.0", payload_prefix=b"old:")
            store.install_from_staging(one)

            two = root / "two"
            two.mkdir()
            _write_pack(two, version="2.0.0", payload_prefix=b"new:")
            store.install_from_staging(two)

            self.assertEqual(store.load_manifest("soft.wood").version, "2.0.0")
            self.assertEqual(store.resolve("soft.wood", "move").read_bytes(), b"new:move")
            self.assertFalse(any(p.name.startswith(".soft.wood.") for p in store.root.iterdir()))

    def test_installed_tamper_fails_closed_at_resolution_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "staging"
            staging.mkdir()
            _write_pack(staging)
            store = SoundPackStore(root / "installed")
            store.install_from_staging(staging)
            installed_asset = store.root / "soft.wood" / "audio" / "move.wav"
            installed_asset.write_bytes(b"tampered")

            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                store.resolve("soft.wood", "move")

    def test_inventory_and_catalog_mark_tampered_install_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "staging"
            staging.mkdir()
            _write_pack(staging)
            store = SoundPackStore(root / "installed")
            store.install_from_staging(staging)
            (store.root / "soft.wood" / "audio" / "move.wav").write_bytes(b"tampered")

            records = store.installed()
            self.assertEqual(len(records), 1)
            self.assertFalse(records[0].valid)
            self.assertIn("digest mismatch", records[0].error)

            state = store.catalog_state(_catalog(version="2.0.0"))
            self.assertTrue(state.installed)
            self.assertTrue(state.update_available)
            self.assertIn("invalid_installed_pack", state.reason)

    def test_uninstall_active_pack_publishes_safe_classic_profile_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "staging"
            staging.mkdir()
            _write_pack(staging)
            store = SoundPackStore(root / "installed")
            store.install_from_staging(staging)

            profile_store = SoundProfileStore(root / "sound-profile.json")
            profile_store.save(
                SoundProfile.from_mapping(
                    {
                        "schema_version": 1,
                        "pack_id": "soft.wood",
                        "master_enabled": True,
                        "master_volume_percent": 80,
                        "events": {
                            "move": {
                                "enabled": True,
                                "volume_percent": 100,
                                "sound_id": "move.alt",
                            }
                        },
                    }
                )
            )

            self.assertTrue(
                store.uninstall("soft.wood", profile_store=profile_store)
            )
            profile = profile_store.load()
            self.assertEqual(profile.pack_id, "classic")
            self.assertEqual(profile.selected_sound_id("move"), "move")
            self.assertFalse((store.root / "soft.wood").exists())

    def test_catalog_state_exposes_install_update_and_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SoundPackStore(root / "installed")
            entry = _catalog(version="2.0.0")
            missing = store.catalog_state(entry)
            self.assertFalse(missing.installed)
            self.assertTrue(missing.compatible)
            self.assertFalse(missing.update_available)

            staging = root / "staging"
            staging.mkdir()
            _write_pack(staging, version="1.0.0")
            store.install_from_staging(staging)
            current = store.catalog_state(entry)
            self.assertTrue(current.installed)
            self.assertTrue(current.update_available)
            self.assertEqual(current.installed_version, "1.0.0")

            incompatible = _catalog(
                version="2.0.0",
                min_product_sound_api=PRODUCT_SOUND_API_VERSION + 1,
                max_product_sound_api=PRODUCT_SOUND_API_VERSION + 2,
            )
            state = store.catalog_state(incompatible)
            self.assertFalse(state.compatible)
            self.assertFalse(state.update_available)
            self.assertEqual(state.reason, "incompatible_product_sound_api")

    def test_classic_pack_cannot_be_installed_or_uninstalled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "staging"
            staging.mkdir()
            _write_pack(staging, pack_id="classic")
            store = SoundPackStore(root / "installed")
            with self.assertRaisesRegex(ValueError, "classic"):
                store.install_from_staging(staging)
            with self.assertRaisesRegex(ValueError, "classic"):
                store.uninstall("classic")


class _Acquisition:
    def __init__(self, staging: Path):
        self.staging = staging
        self.calls = []

    def acquire(self, entry, *, staging_parent):
        self.calls.append((entry, staging_parent))
        return self.staging


class SoundPackInstallServiceTests(unittest.TestCase):
    def test_acquisition_identity_is_checked_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging_parent = root / "scratch"
            staging = staging_parent / "downloaded"
            staging.mkdir(parents=True)
            _write_pack(staging, pack_id="wrong.pack")
            store = SoundPackStore(root / "installed")
            service = SoundPackInstallService(
                store,
                _Acquisition(staging),
                staging_parent=staging_parent,
            )

            with self.assertRaisesRegex(ValueError, "identity"):
                service.install(_catalog(pack_id="soft.wood"))

            self.assertFalse((store.root / "wrong.pack").exists())
            self.assertFalse((store.root / "soft.wood").exists())

    def test_incompatible_catalog_entry_never_invokes_acquisition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "unused"
            acquisition = _Acquisition(staging)
            service = SoundPackInstallService(
                SoundPackStore(root / "installed"),
                acquisition,
                staging_parent=root / "scratch",
            )
            entry = _catalog(
                min_product_sound_api=PRODUCT_SOUND_API_VERSION + 1,
                max_product_sound_api=PRODUCT_SOUND_API_VERSION + 1,
            )
            with self.assertRaisesRegex(ValueError, "incompatible"):
                service.install(entry)
            self.assertEqual(acquisition.calls, [])


if __name__ == "__main__":
    unittest.main()
