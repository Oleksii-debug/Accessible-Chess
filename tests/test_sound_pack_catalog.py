from __future__ import annotations

import inspect
import unittest

from acs.sound_pack_catalog import (
    DownloadedSoundPack,
    SoundAssetDigest,
    SoundPackCatalogEntry,
    SoundPackInstallError,
    SoundPackManager,
    SoundPackRightsEvidence,
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

    def uninstall(self, pack_id, *, expected_manifest=None):
        self.uninstall_calls.append(pack_id)
        current = self.items.get(pack_id)
        if (
            expected_manifest is not None
            and current is not None
            and current != expected_manifest
        ):
            raise SoundPackInstallError(
                "sound pack changed before conditional uninstall"
            )
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


def make_rights(manifest):
    return SoundPackRightsEvidence(
        license_id=manifest.license_id,
        source_uri=f"https://example.invalid/source/{manifest.pack_id}/{manifest.version}",
        license_uri="https://creativecommons.org/publicdomain/zero/1.0/",
    )


def make_entry(manifest=None, *, signature=None, compatible=True, rights=True):
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
        rights_evidence=make_rights(manifest) if rights else None,
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

    def test_manager_rejects_invalid_provider_ports_at_construction(self):
        entry = make_entry()
        downloader = FakeDownloader(make_download(entry))
        storage = FakeStorage({"classic": make_manifest("classic")})

        with self.assertRaisesRegex(TypeError, "downloader"):
            SoundPackManager(object(), storage)  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "storage"):
            SoundPackManager(downloader, object())  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "signature_verifier"):
            SoundPackManager(
                downloader,
                storage,
                signature_verifier=object(),  # type: ignore[arg-type]
            )

    def test_downloaded_asset_keys_are_normalized_and_cannot_alias(self):
        entry = make_entry()
        path, digest = next(iter(entry.assets.items()))
        windows_spelling = path.replace("/", chr(92))
        with self.assertRaisesRegex(ValueError, "duplicate normalized"):
            DownloadedSoundPack(
                manifest=entry.manifest,
                assets={path: digest, windows_spelling: digest},
                total_bytes=digest.size_bytes * 2,
                payload_ref=object(),
            )

        other_path = next(candidate for candidate in entry.assets if candidate != path)
        other_digest = entry.assets[other_path]
        with self.assertRaisesRegex(ValueError, "key must match"):
            DownloadedSoundPack(
                manifest=entry.manifest,
                assets={path: other_digest},
                total_bytes=other_digest.size_bytes,
                payload_ref=object(),
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

    def test_rights_evidence_requires_auditable_https_or_urn_references(self):
        manifest = make_manifest()
        for field, value in (
            ("source_uri", "C:/private/sounds"),
            ("source_uri", "http://example.invalid/source"),
            ("source_uri", "https://user:secret@example.invalid/source"),
            ("source_uri", "https://example.invalid/has space"),
            ("source_uri", " https://example.invalid/source"),
            ("source_uri", "https://:443/source"),
            ("source_uri", "https://example.invalid:notaport/source"),
            ("source_uri", "https://example.invalid/source?token=secret"),
            ("source_uri", "https://example.invalid/source#private-fragment"),
            ("license_uri", "urn:accessible-chess:test:license?token=secret"),
            ("license_uri", "urn:accessible-chess:test:license#fragment"),
            ("source_uri", "https://example.invalid/source\u202ereversed"),
            ("license_uri", "https://example.invalid/license\u200bhidden"),
            ("license_uri", "relative/license.txt"),
            ("license_uri", "javascript:alert(1)"),
        ):
            values = {
                "license_id": manifest.license_id,
                "source_uri": "urn:accessible-chess:test:source",
                "license_uri": "urn:accessible-chess:test:license",
            }
            values[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                SoundPackRightsEvidence(**values)

    def test_rights_license_id_rejects_unicode_format_control_spoofing(self):
        with self.assertRaisesRegex(ValueError, "control characters"):
            SoundPackRightsEvidence(
                license_id="CC0\u202e-1.0",
                source_uri="https://example.invalid/source",
                license_uri="https://example.invalid/license",
            )

    def test_rights_evidence_license_must_match_downloaded_manifest_authority(self):
        manifest = make_manifest()
        entry = make_entry(manifest)
        with self.assertRaisesRegex(ValueError, "must match manifest"):
            SoundPackCatalogEntry(
                manifest=manifest,
                assets=entry.assets,
                total_bytes=entry.total_bytes,
                rights_evidence=SoundPackRightsEvidence(
                    license_id="MIT",
                    source_uri="urn:accessible-chess:test:source",
                    license_uri="https://opensource.org/license/mit",
                ),
            )

    def test_install_without_auditable_rights_evidence_fails_before_download(self):
        entry = make_entry(rights=False)
        downloader = FakeDownloader(make_download(entry))
        storage = FakeStorage({"classic": make_manifest("classic")})

        with self.assertRaisesRegex(
            SoundPackInstallError,
            "auditable license/provenance evidence",
        ):
            SoundPackManager(downloader, storage).install(entry)

        self.assertEqual([], downloader.calls)
        self.assertEqual([], storage.install_calls)

    def test_download_port_cannot_replace_catalog_rights_authority(self):
        entry = make_entry()
        spoofed = SoundPackRightsEvidence(
            license_id=entry.manifest.license_id,
            source_uri="https://example.invalid/spoofed-source",
            license_uri="https://example.invalid/spoofed-license",
        )
        downloaded = make_download(entry, rights_evidence=spoofed)
        storage = FakeStorage({"classic": make_manifest("classic")})

        with self.assertRaisesRegex(
            SoundPackInstallError,
            "must not supply sound pack rights authority",
        ):
            SoundPackManager(FakeDownloader(downloaded), storage).install(entry)

        self.assertEqual([], storage.install_calls)

    def test_rights_evidence_round_trips_through_strict_mapping(self):
        rights = make_rights(make_manifest())
        self.assertEqual(
            rights,
            SoundPackRightsEvidence.from_mapping(rights.to_mapping()),
        )
        for malformed in (
            {},
            {**rights.to_mapping(), "extra": "x"},
            {**rights.to_mapping(), "schema_version": 99},
            {
                **rights.to_mapping(),
                "license_uri": 7,
            },
        ):
            with self.subTest(malformed=repr(malformed)), self.assertRaises(
                (TypeError, ValueError)
            ):
                SoundPackRightsEvidence.from_mapping(malformed)

    def test_catalog_signature_rejects_control_character_spoofing(self):
        for signature in (
            "signed\nextra",
            "signed\tshadow",
            "signed\u2028second-line",
            "signed\u202evisual-reversal",
            "signed\u200bhidden-separator",
            " signed",
            "signed ",
        ):
            with self.subTest(signature=repr(signature)), self.assertRaisesRegex(
                ValueError,
                "control characters",
            ):
                make_entry(signature=signature)

    def test_catalog_signature_is_resource_bounded(self):
        with self.assertRaisesRegex(ValueError, "signature exceeds"):
            make_entry(signature="s" * (16 * 1024 + 1))

    def test_preflight_rejects_ineligible_candidate_without_downloader_or_storage_side_effect(self):
        installed = make_manifest("soft.wood", "2.0.0")
        candidate = make_entry(make_manifest("soft.wood", "3.0.0"), rights=False)
        downloader = FakeDownloader(make_download(candidate))
        storage = FakeStorage({"classic": make_manifest("classic"), installed.pack_id: installed})
        manager = SoundPackManager(downloader, storage)

        with self.assertRaisesRegex(
            SoundPackInstallError,
            "auditable license/provenance evidence",
        ):
            manager.preflight_install(candidate)

        self.assertEqual([], downloader.calls)
        self.assertEqual([], storage.install_calls)
        self.assertEqual(installed, storage.items[installed.pack_id])

    def test_valid_pack_is_verified_before_atomic_install(self):
        entry = make_entry()
        downloaded = make_download(entry)
        downloader = FakeDownloader(downloaded)
        storage = FakeStorage({"classic": make_manifest("classic")})
        manager = SoundPackManager(downloader, storage, max_bytes=1024)

        installed = manager.install(entry)

        self.assertEqual(installed, entry.manifest)
        self.assertEqual(len(storage.install_calls), 1)
        committed = storage.install_calls[0]
        self.assertEqual(committed.manifest, downloaded.manifest)
        self.assertEqual(committed.assets, downloaded.assets)
        self.assertEqual(committed.total_bytes, downloaded.total_bytes)
        self.assertIs(committed.payload_ref, downloaded.payload_ref)
        self.assertEqual(committed.rights_evidence, entry.rights_evidence)
        self.assertIsNone(downloaded.rights_evidence)
        self.assertEqual(downloader.calls[0][1], 1024)

    def test_current_catalog_version_is_not_redownloaded_or_reinstalled(self):
        current = make_manifest(version="2.0.0")
        entry = make_entry(current)
        downloader = FakeDownloader(make_download(entry))
        storage = FakeStorage(
            {
                "classic": make_manifest("classic"),
                current.pack_id: current,
            }
        )
        manager = SoundPackManager(downloader, storage)

        with self.assertRaisesRegex(SoundPackInstallError, "already installed"):
            manager.install(entry)

        self.assertEqual([], downloader.calls)
        self.assertEqual([], storage.install_calls)
        self.assertEqual(current, storage.items[current.pack_id])

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

    def test_same_version_catalog_manifest_conflict_is_not_current_or_installable(self):
        installed = make_manifest(version="2.0.0")
        conflicting = SoundPackManifest(
            pack_id=installed.pack_id,
            version=installed.version,
            title="Conflicting title",
            license_id=installed.license_id,
            files=dict(installed.files),
            author=installed.author,
            provenance="https://example.invalid/conflicting-pack",
        )
        entry = make_entry(conflicting)
        storage = FakeStorage({"classic": make_manifest("classic"), installed.pack_id: installed})
        downloader = FakeDownloader(make_download(entry))
        manager = SoundPackManager(downloader, storage)

        self.assertEqual(manager.status(entry).state, SoundPackState.VERSION_CONFLICT)
        with self.assertRaisesRegex(SoundPackInstallError, "metadata conflicts"):
            manager.install(entry)

        self.assertEqual([], downloader.calls)
        self.assertEqual([], storage.install_calls)
        self.assertEqual(installed, storage.items[installed.pack_id])

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

    def test_conditional_uninstall_preserves_concurrent_replacement(self):
        classic = make_manifest("classic")
        planned = make_manifest("soft.wood", "1.0.0")
        replacement = make_manifest("soft.wood", "2.0.0")
        storage = FakeStorage({"classic": classic, "soft.wood": planned})
        manager = SoundPackManager(
            FakeDownloader(make_download(make_entry(planned))),
            storage,
        )
        profile = SoundProfile(pack_id="soft.wood")

        plan = manager.prepare_uninstall(
            "soft.wood",
            active_profile=profile,
        )
        self.assertEqual(planned, plan.expected_manifest)

        storage.items["soft.wood"] = replacement

        with self.assertRaisesRegex(
            SoundPackInstallError,
            "changed before conditional uninstall",
        ):
            manager.commit_uninstall(plan)

        self.assertEqual(replacement, storage.items["soft.wood"])

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

    def test_malformed_installed_inventory_fails_closed_before_actions(self):
        entry = make_entry()
        downloaded = make_download(entry)

        class MalformedStorage:
            def __init__(self, raw):
                self.raw = raw
                self.install_calls = []
                self.uninstall_calls = []

            def installed(self):
                return self.raw

            def install_atomically(self, value):
                self.install_calls.append(value)

            def uninstall(self, pack_id, *, expected_manifest=None):
                self.uninstall_calls.append(pack_id)

        cases = (
            ([], "inventory"),
            ({"soft.wood": object()}, "metadata"),
            ({"Soft.Wood": make_manifest("soft.wood")}, "identity"),
            ({"other.pack": make_manifest("soft.wood")}, "identity"),
        )
        for raw, message in cases:
            with self.subTest(raw=repr(raw)):
                storage = MalformedStorage(raw)
                downloader = FakeDownloader(downloaded)
                manager = SoundPackManager(downloader, storage)
                with self.assertRaisesRegex(SoundPackInstallError, message):
                    manager.resolve_usable_pack("soft.wood")
                with self.assertRaisesRegex(SoundPackInstallError, message):
                    manager.install(entry)
                self.assertEqual([], downloader.calls)
                self.assertEqual([], storage.install_calls)
                self.assertEqual([], storage.uninstall_calls)

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
