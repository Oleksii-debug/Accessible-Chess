from __future__ import annotations

import inspect
import unittest

from acs.sound_pack_catalog import (
    DownloadedSoundPack,
    SoundAssetDigest,
    SoundPackCatalogEntry,
    SoundPackInstallError,
    SoundPackManager,
    SoundPackState,
)
from acs.sound_profiles import CORE_SOUND_EVENTS, SoundEventPreference, SoundPackManifest, SoundProfile


class FakeDownloader:
    def __init__(self, downloaded: DownloadedSoundPack) -> None:
        self.downloaded = downloaded
        self.calls = []

    def download(self, entry, *, max_bytes):
        self.calls.append((entry, max_bytes))
        return self.downloaded


class FakeStorage:
    def __init__(self, installed):
        self.items = dict(installed)
        self.install_calls = []
        self.uninstall_calls = []

    def installed(self):
        return dict(self.items)

    def install_atomically(self, downloaded):
        self.install_calls.append(downloaded)
        self.items[downloaded.manifest.pack_id] = downloaded.manifest

    def uninstall(self, pack_id):
        self.uninstall_calls.append(pack_id)
        self.items.pop(pack_id, None)


class FakeVerifier:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.calls = []

    def verify(self, entry, downloaded):
        self.calls.append((entry, downloaded))
        return self.result


def make_manifest(pack_id="soft.wood", version="1.0.0"):
    return SoundPackManifest(
        pack_id=pack_id,
        version=version,
        title=pack_id,
        license_id="CC0-1.0",
        files={event: f"audio/{event}.wav" for event in CORE_SOUND_EVENTS},
        author="Accessible Chess",
        provenance="https://example.invalid/pack",
    )


def make_entry(manifest=None, *, signature=None, compatible=True):
    manifest = manifest or make_manifest()
    assets = {}
    for index, path in enumerate(sorted(set(manifest.files.values())), start=1):
        assets[path] = SoundAssetDigest(path, index, f"{index:064x}")
    return SoundPackCatalogEntry(
        manifest=manifest,
        assets=assets,
        total_bytes=sum(item.size_bytes for item in assets.values()),
        signature=signature,
        compatible=compatible,
    )


def make_download(entry, **changes):
    values = {
        "manifest": entry.manifest,
        "assets": entry.assets,
        "total_bytes": entry.total_bytes,
        "payload_ref": object(),
    }
    values.update(changes)
    return DownloadedSoundPack(**values)


class SoundPackCatalogTests(unittest.TestCase):
    def test_valid_pack_is_verified_before_atomic_install(self):
        entry = make_entry()
        downloaded = make_download(entry)
        downloader = FakeDownloader(downloaded)
        storage = FakeStorage({"classic": make_manifest("classic")})
        manager = SoundPackManager(downloader, storage, max_bytes=1024)

        installed = manager.install(entry)

        self.assertEqual(installed, entry.manifest)
        self.assertEqual(storage.install_calls, [downloaded])
        self.assertEqual(downloader.calls[0][1], 1024)

    def test_oversized_catalog_entry_is_rejected_before_download(self):
        entry = make_entry()
        downloader = FakeDownloader(make_download(entry))
        storage = FakeStorage({"classic": make_manifest("classic")})
        manager = SoundPackManager(downloader, storage, max_bytes=entry.total_bytes - 1)

        with self.assertRaises(SoundPackInstallError):
            manager.install(entry)

        self.assertEqual(downloader.calls, [])
        self.assertEqual(storage.install_calls, [])

    def test_checksum_mismatch_never_reaches_storage(self):
        entry = make_entry()
        assets = dict(entry.assets)
        path = next(iter(assets))
        old = assets[path]
        replacement = "f" * 64 if old.sha256 != "f" * 64 else "e" * 64
        assets[path] = SoundAssetDigest(path, old.size_bytes, replacement)
        downloader = FakeDownloader(make_download(entry, assets=assets))
        storage = FakeStorage({"classic": make_manifest("classic")})

        with self.assertRaisesRegex(SoundPackInstallError, "checksum"):
            SoundPackManager(downloader, storage).install(entry)

        self.assertEqual(storage.install_calls, [])

    def test_missing_asset_never_reaches_storage(self):
        entry = make_entry()
        assets = dict(entry.assets)
        assets.pop(next(iter(assets)))
        downloaded = make_download(
            entry,
            assets=assets,
            total_bytes=sum(item.size_bytes for item in assets.values()),
        )
        storage = FakeStorage({"classic": make_manifest("classic")})

        with self.assertRaisesRegex(SoundPackInstallError, "asset set"):
            SoundPackManager(FakeDownloader(downloaded), storage).install(entry)

        self.assertEqual(storage.install_calls, [])

    def test_signed_pack_requires_and_uses_verifier(self):
        entry = make_entry(signature="catalog-signature")
        downloaded = make_download(entry)
        storage = FakeStorage({"classic": make_manifest("classic")})

        with self.assertRaisesRegex(SoundPackInstallError, "signature verifier"):
            SoundPackManager(FakeDownloader(downloaded), storage).install(entry)

        verifier = FakeVerifier(True)
        manager = SoundPackManager(
            FakeDownloader(downloaded), storage, signature_verifier=verifier
        )
        manager.install(entry)
        self.assertEqual(len(verifier.calls), 1)
        self.assertEqual(len(storage.install_calls), 1)

    def test_failed_signature_never_reaches_storage(self):
        entry = make_entry(signature="catalog-signature")
        storage = FakeStorage({"classic": make_manifest("classic")})
        manager = SoundPackManager(
            FakeDownloader(make_download(entry)),
            storage,
            signature_verifier=FakeVerifier(False),
        )

        with self.assertRaisesRegex(SoundPackInstallError, "signature verification failed"):
            manager.install(entry)

        self.assertEqual(storage.install_calls, [])

    def test_update_reuses_same_atomic_install_boundary(self):
        old = make_manifest(version="1.0.0")
        new = make_manifest(version="2.0.0")
        entry = make_entry(new)
        storage = FakeStorage({"classic": make_manifest("classic"), old.pack_id: old})
        manager = SoundPackManager(FakeDownloader(make_download(entry)), storage)

        self.assertEqual(manager.status(entry).state, SoundPackState.DIFFERENT_VERSION)
        manager.install(entry)
        self.assertEqual(storage.items[old.pack_id].version, "2.0.0")
        self.assertEqual(manager.status(entry).state, SoundPackState.CURRENT)

    def test_uninstall_active_pack_returns_profile_on_installed_fallback(self):
        classic = make_manifest("classic")
        active = make_manifest("soft.wood")
        storage = FakeStorage({"classic": classic, "soft.wood": active})
        manager = SoundPackManager(FakeDownloader(make_download(make_entry(active))), storage)
        profile = SoundProfile(
            pack_id="soft.wood",
            master_enabled=False,
            master_volume_percent=31,
            events={"move": SoundEventPreference(False, 44, "quiet.move")},
        )

        resolved = manager.uninstall("soft.wood", active_profile=profile)

        self.assertEqual(storage.uninstall_calls, ["soft.wood"])
        self.assertEqual(resolved.pack_id, "classic")
        self.assertEqual(resolved.master_enabled, profile.master_enabled)
        self.assertEqual(resolved.master_volume_percent, profile.master_volume_percent)
        self.assertEqual(resolved.events, profile.events)

    def test_fallback_pack_cannot_be_uninstalled(self):
        classic = make_manifest("classic")
        storage = FakeStorage({"classic": classic})
        manager = SoundPackManager(FakeDownloader(make_download(make_entry(classic))), storage)
        with self.assertRaisesRegex(SoundPackInstallError, "fallback"):
            manager.uninstall("classic", active_profile=SoundProfile())
        self.assertEqual(storage.uninstall_calls, [])

    def test_missing_configured_pack_recovers_to_fallback_without_touching_preferences(self):
        storage = FakeStorage({"classic": make_manifest("classic")})
        entry = make_entry()
        manager = SoundPackManager(FakeDownloader(make_download(entry)), storage)
        profile = SoundProfile(
            pack_id="missing.pack",
            master_volume_percent=17,
            events={"check": SoundEventPreference(False, 55, "quiet.check")},
        )
        resolved = manager.resolve_profile(profile)
        self.assertEqual(resolved.pack_id, "classic")
        self.assertEqual(resolved.master_volume_percent, 17)
        self.assertEqual(resolved.events, profile.events)

    def test_incompatible_entry_is_visible_but_cannot_install(self):
        entry = make_entry(compatible=False)
        storage = FakeStorage({"classic": make_manifest("classic")})
        downloader = FakeDownloader(make_download(entry))
        manager = SoundPackManager(downloader, storage)
        self.assertEqual(manager.status(entry).state, SoundPackState.INCOMPATIBLE)
        with self.assertRaisesRegex(SoundPackInstallError, "incompatible"):
            manager.install(entry)
        self.assertEqual(downloader.calls, [])

    def test_contract_remains_platform_and_transport_neutral(self):
        import acs.sound_pack_catalog as module

        source = inspect.getsource(module).lower()
        for forbidden in ("winsound", "webview", "sqlite", "subprocess", "requests", "urllib"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
