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
    def test_zero_byte_audio_digest_is_rejected_before_catalog_or_install(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            SoundAssetDigest(
                "audio/move.wav",
                0,
                "0" * 64,
            )

    def test_catalog_and_download_digest_mappings_are_defensive_snapshots(self):
        entry = make_entry()
        source_assets = dict(entry.assets)
        copied_entry = SoundPackCatalogEntry(
            manifest=entry.manifest,
            assets=source_assets,
            total_bytes=entry.total_bytes,
        )
        source_assets.clear()

        self.assertEqual(set(entry.assets), set(copied_entry.assets))
        with self.assertRaises(TypeError):
            copied_entry.assets["x.wav"] = next(iter(entry.assets.values()))  # type: ignore[index]

        download_assets = dict(entry.assets)
        downloaded = DownloadedSoundPack(
            manifest=entry.manifest,
            assets=download_assets,
            total_bytes=entry.total_bytes,
            payload_ref=object(),
        )
        download_assets.clear()

        self.assertEqual(set(entry.assets), set(downloaded.assets))
        with self.assertRaises(TypeError):
            downloaded.assets["x.wav"] = next(iter(entry.assets.values()))  # type: ignore[index]

    def test_downloaded_pack_constructor_rejects_invalid_scalar_and_digest_shapes(self):
        entry = make_entry()
        with self.assertRaisesRegex(TypeError, "manifest"):
            DownloadedSoundPack(
                manifest=object(),  # type: ignore[arg-type]
                assets=entry.assets,
                total_bytes=entry.total_bytes,
                payload_ref=object(),
            )
        for value in (True, "10"):
            with self.subTest(total_bytes=value), self.assertRaisesRegex(
                TypeError,
                "total_bytes",
            ):
                DownloadedSoundPack(
                    manifest=entry.manifest,
                    assets=entry.assets,
                    total_bytes=value,  # type: ignore[arg-type]
                    payload_ref=object(),
                )
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            DownloadedSoundPack(
                manifest=entry.manifest,
                assets=entry.assets,
                total_bytes=-1,
                payload_ref=object(),
            )
        with self.assertRaisesRegex(TypeError, "SoundAssetDigest"):
            DownloadedSoundPack(
                manifest=entry.manifest,
                assets={"audio/move.wav": object()},  # type: ignore[dict-item]
                total_bytes=1,
                payload_ref=object(),
            )

    def test_catalog_signature_is_resource_bounded(self):
        with self.assertRaisesRegex(ValueError, "signature exceeds"):
            make_entry(signature="s" * (16 * 1024 + 1))

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

    def test_catalog_rejects_duplicate_paths_after_separator_normalization(self):
        manifest = make_manifest()
        assets = dict(make_entry(manifest).assets)
        move_path = manifest.files["move"]
        move_digest = assets[move_path]
        assets[move_path.replace("/", chr(92))] = move_digest

        with self.assertRaisesRegex(ValueError, "duplicate normalized"):
            SoundPackCatalogEntry(
                manifest=manifest,
                assets=assets,
                total_bytes=sum(item.size_bytes for item in assets.values()),
            )

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

    def test_signature_verifier_must_return_exact_boolean(self):
        entry = make_entry(signature="catalog-signature")
        downloaded = make_download(entry)
        storage = FakeStorage({"classic": make_manifest("classic")})
        verifier = FakeVerifier("false")  # type: ignore[arg-type]
        manager = SoundPackManager(
            FakeDownloader(downloaded),
            storage,
            signature_verifier=verifier,
        )

        with self.assertRaisesRegex(SoundPackInstallError, "invalid result"):
            manager.install(entry)

        self.assertEqual(storage.install_calls, [])

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

    def test_stale_catalog_cannot_downgrade_newer_installed_pack(self):
        installed = make_manifest(version="2.0.0")
        stale = make_manifest(version="1.5.0")
        entry = make_entry(stale)
        storage = FakeStorage({"classic": make_manifest("classic"), installed.pack_id: installed})
        downloader = FakeDownloader(make_download(entry))
        manager = SoundPackManager(downloader, storage)

        self.assertEqual(manager.status(entry).state, SoundPackState.CATALOG_OLDER)
        with self.assertRaisesRegex(SoundPackInstallError, "older than the installed"):
            manager.install(entry)

        self.assertEqual(downloader.calls, [])
        self.assertEqual(storage.install_calls, [])
        self.assertEqual(installed, storage.items[installed.pack_id])

    def test_prerelease_semver_rollback_is_rejected_by_precedence(self):
        installed = make_manifest(version="2.0.0")
        stale = make_manifest(version="2.0.0-rc.9")
        entry = make_entry(stale)
        storage = FakeStorage({"classic": make_manifest("classic"), installed.pack_id: installed})
        manager = SoundPackManager(FakeDownloader(make_download(entry)), storage)

        self.assertEqual(manager.status(entry).state, SoundPackState.CATALOG_OLDER)

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
        self.assertEqual(
            resolved.preference_for("move"),
            SoundEventPreference(False, 44),
        )

    def test_external_fallback_allows_provider_storage_without_classic_manifest(self):
        active = make_manifest("soft.wood")
        storage = FakeStorage({"soft.wood": active})
        manager = SoundPackManager(
            FakeDownloader(make_download(make_entry(active))),
            storage,
            external_fallback_available=True,
        )
        profile = SoundProfile(
            pack_id="soft.wood",
            master_enabled=False,
            master_volume_percent=31,
            events={"move": SoundEventPreference(False, 44, "quiet.move")},
        )

        self.assertEqual(manager.resolve_usable_pack("classic"), "classic")
        self.assertEqual(manager.resolve_usable_pack("missing.pack"), "classic")
        resolved = manager.uninstall("soft.wood", active_profile=profile)

        self.assertEqual(storage.uninstall_calls, ["soft.wood"])
        self.assertEqual(resolved.pack_id, "classic")
        self.assertEqual(resolved.master_enabled, profile.master_enabled)
        self.assertEqual(resolved.master_volume_percent, profile.master_volume_percent)
        self.assertEqual(
            resolved.preference_for("move"),
            SoundEventPreference(False, 44),
        )

    def test_external_fallback_flag_requires_exact_boolean(self):
        with self.assertRaisesRegex(TypeError, "external_fallback_available"):
            SoundPackManager(
                FakeDownloader(make_download(make_entry())),
                FakeStorage({}),
                external_fallback_available=1,  # type: ignore[arg-type]
            )

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
        self.assertEqual(
            resolved.preference_for("check"),
            SoundEventPreference(False, 55),
        )

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
