from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import wave
from unittest import mock

from acs.sound_pack_catalog import (
    MAX_SOUND_PACK_CATALOG_ENTRIES,
    DownloadedSoundPack,
    SoundAssetDigest,
    SoundPackCatalogEntry,
    SoundPackRightsEvidence,
)
from acs.sound_pack_store import FilesystemSoundPackStore
from acs.sound_profile_composition import (
    _InjectedClassicPlaybackBridge,
    _installed_pack_inventory,
    _local_pack_resolver,
    _playable_installed_packs,
    _windows_pack_is_playable,
    create_local_sound_composition,
)
from acs.sound_profile_store import SoundProfileWriteBlockedError
from acs.sound_profiles import CORE_SOUND_EVENTS, SoundPackManifest
from acs.sound_runtime import SoundAssetRequest


class _OversizedCatalog(Mapping):
    def __getitem__(self, key):
        raise KeyError(key)

    def __iter__(self):
        raise AssertionError("oversized catalog must be rejected before iteration")

    def __len__(self):
        return MAX_SOUND_PACK_CATALOG_ENTRIES + 1


def _pack_manifest(pack_id: str, suffix: str = ".wav") -> SoundPackManifest:
    return SoundPackManifest(
        pack_id=pack_id,
        version="1.0.0",
        title=pack_id,
        license_id="CC0-1.0",
        files={event: f"audio/{event}{suffix}" for event in CORE_SOUND_EVENTS},
        author="Accessible Chess tests",
        provenance="tests-only generated assets",
    )


def _write_wav(path: Path, samples: tuple[int, ...] = (1000, -1000, 500, -500)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(8000)
        writer.writeframes(struct.pack("<" + "h" * len(samples), *samples))


def _catalog_entry_from_manifest(
    root: Path,
    manifest: SoundPackManifest,
    *,
    staging_name: str = "provider-staging",
) -> tuple[SoundPackCatalogEntry, Path]:
    staging = root / staging_name
    assets: dict[str, SoundAssetDigest] = {}
    for relative in sorted(set(manifest.files.values())):
        target = staging / relative
        _write_wav(target)
        payload = target.read_bytes()
        assets[relative] = SoundAssetDigest(
            relative,
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        )
    return (
        SoundPackCatalogEntry(
            manifest=manifest,
            assets=assets,
            total_bytes=sum(item.size_bytes for item in assets.values()),
            rights_evidence=SoundPackRightsEvidence(
                license_id=manifest.license_id,
                source_uri=f"https://example.invalid/source/{manifest.pack_id}/{manifest.version}",
                license_uri="https://creativecommons.org/publicdomain/zero/1.0/",
            ),
        ),
        staging,
    )


def _catalog_entry(
    root: Path,
    pack_id: str = "remote.wood",
) -> tuple[SoundPackCatalogEntry, Path]:
    return _catalog_entry_from_manifest(root, _pack_manifest(pack_id))


class _StagedDownloader:
    def __init__(self, entry: SoundPackCatalogEntry, staging: Path) -> None:
        self.entry = entry
        self.staging = staging
        self.calls: list[tuple[str, int]] = []

    def download(self, entry: SoundPackCatalogEntry, *, max_bytes: int) -> DownloadedSoundPack:
        self.calls.append((entry.manifest.pack_id, max_bytes))
        if entry != self.entry:
            raise AssertionError("unexpected catalog entry")
        return DownloadedSoundPack(
            manifest=entry.manifest,
            assets=entry.assets,
            total_bytes=entry.total_bytes,
            payload_ref=self.staging,
        )


class _InstalledStore:
    def __init__(self, manifests):
        self._manifests = {item.pack_id: item for item in manifests}

    def installed(self):
        return dict(self._manifests)


class _Playback:
    def __init__(self) -> None:
        self.requests: list[SoundAssetRequest] = []

    def play_sound(self, request: SoundAssetRequest) -> None:
        self.requests.append(request)


class _LegacyPlayback:
    def __init__(self) -> None:
        self.calls = []

    def play(self, event, *, volume: int) -> None:
        self.calls.append((event, volume))


class LocalSoundCompositionTests(unittest.TestCase):
    def test_first_run_migrates_legacy_sound_toggle_and_volume_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-migrate-") as raw:
            root = Path(raw)
            playback = _Playback()
            first = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                legacy_settings={"sounds": False, "volume": 37},
                asset_playback=playback,
            )
            self.assertFalse(first.profile_manager.current.master_enabled)
            self.assertEqual(37, first.profile_manager.current.master_volume_percent)
            profile_path = root / "data" / "sound-profile.json"
            self.assertTrue(profile_path.is_file())

            # A later legacy-setting change cannot overwrite the new single authority.
            second = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                legacy_settings={"sounds": True, "volume": 99},
                asset_playback=_Playback(),
            )
            self.assertFalse(second.profile_manager.current.master_enabled)
            self.assertEqual(37, second.profile_manager.current.master_volume_percent)

    def test_malformed_first_run_legacy_settings_do_not_poison_migration_marker(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-migrate-malformed-") as raw:
            root = Path(raw)
            profile_path = root / "data" / "sound-profile.json"

            with self.assertRaises(TypeError):
                create_local_sound_composition(
                    application_dir=root / "app",
                    data_root=root / "data",
                    legacy_settings={"sounds": "false", "volume": 37},
                    asset_playback=_Playback(),
                )

            self.assertFalse(
                profile_path.exists(),
                "failed legacy parsing must not create a default migration marker",
            )

            recovered = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                legacy_settings={"sounds": False, "volume": 37},
                asset_playback=_Playback(),
            )
            self.assertFalse(recovered.profile_manager.current.master_enabled)
            self.assertEqual(37, recovered.profile_manager.current.master_volume_percent)

    def test_existing_profile_never_reparses_malformed_legacy_settings(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-existing-ignore-legacy-") as raw:
            root = Path(raw)
            first = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                legacy_settings={"sounds": False, "volume": 37},
                asset_playback=_Playback(),
            )
            self.assertFalse(first.profile_manager.current.master_enabled)

            second = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                legacy_settings={"sounds": "not-a-bool", "volume": object()},
                asset_playback=_Playback(),
            )
            self.assertFalse(second.profile_manager.current.master_enabled)
            self.assertEqual(37, second.profile_manager.current.master_volume_percent)

    def test_settings_mutation_persists_and_is_visible_after_restart(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-restart-") as raw:
            root = Path(raw)
            first = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=_Playback(),
            )
            first.settings.set_master(enabled=True, volume_percent=64)
            first.settings.set_event("check", volume_percent=45)

            second = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=_Playback(),
            )
            self.assertEqual(64, second.profile_manager.current.master_volume_percent)
            self.assertEqual(45, second.profile_manager.current.preference_for("check").volume_percent)
            self.assertIsNone(second.profile_manager.current.preference_for("check").sound_id)
            self.assertEqual("check", second.profile_manager.current.selected_sound_id("check"))

    def test_classroom_runtime_reuses_exact_profile_and_playback_authorities(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-classroom-") as raw:
            root = Path(raw)
            playback = _Playback()
            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=playback,
            )

            self.assertIs(
                composition.classroom_runtime._playback,
                composition.profiled_runtime._asset_playback,
            )
            composition.settings.set_master(enabled=False)
            result = composition.classroom_runtime.dispatch("classroom.join")
            self.assertTrue(result.ok)
            self.assertFalse(result.delivered)
            self.assertEqual([], playback.requests)

    def test_default_classic_composition_silences_optional_classroom_sound(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-classic-classroom-") as raw:
            root = Path(raw)
            playback = _Playback()
            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=playback,
            )

            result = composition.classroom_runtime.dispatch("classroom.join")

            self.assertTrue(result.ok)
            self.assertFalse(result.delivered)
            self.assertIsNone(result.request)
            self.assertEqual([], playback.requests)

    def test_preview_runs_through_composed_profiled_runtime(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-preview-") as raw:
            root = Path(raw)
            playback = _Playback()
            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=playback,
            )
            composition.settings.set_master(volume_percent=50)
            composition.settings.set_event("capture", volume_percent=60)
            composition.settings.preview("capture", language="en")

            self.assertEqual(1, len(playback.requests))
            request = playback.requests[0]
            self.assertEqual("classic", request.pack_id)
            self.assertEqual("capture", request.event_id)
            self.assertEqual("capture", request.sound_id)
            self.assertEqual(30, request.volume)
            self.assertTrue(request.preview)

    def test_retained_legacy_injection_is_adapted_without_second_profile_owner(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-legacy-port-") as raw:
            root = Path(raw)
            playback = _LegacyPlayback()
            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=playback,
            )
            composition.settings.set_master(volume_percent=55)
            composition.settings.preview("move", language="en")

            self.assertEqual(1, len(playback.calls))
            event, volume = playback.calls[0]
            self.assertEqual("move", event.value)
            self.assertEqual(55, volume)

    def test_legacy_injection_low_time_is_preview_only_and_maps_to_tick(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-legacy-low-time-") as raw:
            root = Path(raw)
            playback = _LegacyPlayback()
            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=playback,
            )
            composition.settings.preview("low_time")

            self.assertEqual(1, len(playback.calls))
            event, _volume = playback.calls[0]
            self.assertEqual("tick", event.value)

    def test_legacy_injection_uses_canonical_low_time_when_owner_event_exists(self) -> None:
        playback = _LegacyPlayback()
        bridge = _InjectedClassicPlaybackBridge(playback)

        class FutureSoundEvent:
            TICK = type("Tick", (), {"value": "tick"})()

            def __new__(cls, value):
                if value == "low_time":
                    return type("LowTime", (), {"value": "low_time"})()
                if value == "tick":
                    return cls.TICK
                raise ValueError(value)

        with mock.patch(
            "acs.sound_profile_composition.SoundEvent",
            FutureSoundEvent,
        ):
            bridge.play_sound(
                SoundAssetRequest(
                    pack_id="classic",
                    event_id="low_time",
                    sound_id="low_time",
                    volume=67,
                    preview=False,
                )
            )

        self.assertEqual(1, len(playback.calls))
        event, volume = playback.calls[0]
        self.assertEqual("low_time", event.value)
        self.assertEqual(67, volume)

    def test_missing_selected_custom_pack_recovers_to_classic_on_load(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-fallback-") as raw:
            root = Path(raw)
            data = root / "data"
            data.mkdir(parents=True)
            (data / "sound-profile.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "pack_id": "missing.pack",
                        "master_enabled": True,
                        "master_volume_percent": 80,
                        "events": {
                            "move": {
                                "enabled": False,
                                "volume_percent": 43,
                                "sound_id": "custom.move",
                            }
                        },
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=data,
                asset_playback=_Playback(),
            )
            self.assertEqual("classic", composition.profile_manager.current.pack_id)
            pref = composition.profile_manager.current.preference_for("move")
            self.assertFalse(pref.enabled)
            self.assertEqual(43, pref.volume_percent)
            self.assertIsNone(pref.sound_id)
            persisted = json.loads((data / "sound-profile.json").read_text(encoding="utf-8"))
            self.assertEqual("classic", persisted["pack_id"])
            self.assertIsNone(persisted["events"]["move"]["sound_id"])

    def test_restart_normalizes_stale_sound_id_against_installed_custom_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-choice-reconcile-") as raw:
            root = Path(raw)
            data = root / "data"
            data.mkdir(parents=True)
            path = data / "sound-profile.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "pack_id": "local.wood",
                        "master_enabled": True,
                        "master_volume_percent": 72,
                        "events": {
                            "move": {
                                "enabled": False,
                                "volume_percent": 31,
                                "sound_id": "removed.sound",
                            }
                        },
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            manifest = _pack_manifest("local.wood")

            with mock.patch.object(
                FilesystemSoundPackStore,
                "installed",
                return_value={"local.wood": manifest},
            ):
                composition = create_local_sound_composition(
                    application_dir=root / "app",
                    data_root=data,
                    asset_playback=_Playback(),
                )

            self.assertEqual("local.wood", composition.profile_manager.current.pack_id)
            pref = composition.profile_manager.current.preference_for("move")
            self.assertFalse(pref.enabled)
            self.assertEqual(31, pref.volume_percent)
            self.assertIsNone(pref.sound_id)
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsNone(persisted["events"]["move"]["sound_id"])

    def test_future_profile_schema_is_preserved_and_ui_writes_blocked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-future-") as raw:
            root = Path(raw)
            data = root / "data"
            data.mkdir(parents=True)
            future = {"schema_version": 999, "pack_id": "future.pack", "future": {"x": 1}}
            path = data / "sound-profile.json"
            path.write_text(json.dumps(future), encoding="utf-8")

            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=data,
                legacy_settings={"sounds": False, "volume": 1},
                asset_playback=_Playback(),
            )
            self.assertTrue(composition.profile_manager.writes_blocked)
            self.assertFalse(
                composition.profile_manager.current.master_enabled,
                "unknown future sound schema must fail closed for runtime playback",
            )
            preview = composition.settings.preview("move", language="en")
            self.assertTrue(preview.ok)
            self.assertIn("muted", preview.announcement.lower())
            self.assertEqual(
                [],
                composition.profiled_runtime._asset_playback.requests,
            )
            with self.assertRaises(SoundProfileWriteBlockedError):
                composition.settings.set_master(enabled=False)
            self.assertEqual(future, json.loads(path.read_text(encoding="utf-8")))

    def test_windows_incompatible_installed_pack_is_never_resolved_or_exposed(self) -> None:
        wav = _pack_manifest("local.wav")
        ogg = _pack_manifest("local.ogg", ".ogg")
        store = _InstalledStore([wav, ogg])

        self.assertTrue(_windows_pack_is_playable(wav))
        self.assertFalse(_windows_pack_is_playable(ogg))
        self.assertEqual("local.wav", _local_pack_resolver(store)("local.wav"))
        self.assertEqual("classic", _local_pack_resolver(store)("local.ogg"))
        self.assertEqual(
            {"local.wav": wav, "local.ogg": ogg},
            _installed_pack_inventory(store),
        )
        self.assertEqual({"local.wav": wav}, _playable_installed_packs(store))

    def test_optional_pack_inventory_failure_does_not_break_classic_startup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-pack-read-failure-") as raw:
            root = Path(raw)
            with mock.patch.object(
                FilesystemSoundPackStore,
                "installed_audit",
                side_effect=OSError("pack root unavailable"),
            ):
                composition = create_local_sound_composition(
                    application_dir=root / "app",
                    data_root=root / "data",
                    asset_playback=_Playback(),
                )

            self.assertEqual("classic", composition.profile_manager.current.pack_id)
            self.assertEqual((), composition.settings.snapshot(language="en")["packs"])

    def test_composition_binds_settings_to_one_coherent_installed_audit_provider(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-local-pack-provider-") as raw:
            root = Path(raw)
            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=_Playback(),
            )
            audit_provider = composition.settings._installed_audit_provider
            self.assertTrue(callable(audit_provider))
            self.assertIsNone(composition.settings._installed_pack_provider)
            self.assertIsNone(composition.settings._installed_rights_provider)
            self.assertEqual({}, audit_provider())

    def test_optional_provider_install_survives_restart_and_local_uninstall_without_provider(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-provider-") as raw:
            root = Path(raw)
            entry, staging = _catalog_entry(root)
            downloader = _StagedDownloader(entry, staging)
            first = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=_Playback(),
                catalog={entry.manifest.pack_id: entry},
                pack_downloader=downloader,
            )

            before = first.settings.snapshot(language="en")
            remote = next(
                item for item in before["packs"]
                if item["pack_id"] == entry.manifest.pack_id
            )
            self.assertEqual("not_installed", remote["state"])
            self.assertTrue(remote["can_install"])

            installed = first.settings.install_pack(
                entry.manifest.pack_id,
                activate=True,
                language="en",
            )

            self.assertTrue(installed.ok)
            self.assertEqual(entry.manifest.pack_id, first.profile_manager.current.pack_id)
            self.assertEqual(
                entry.manifest.version,
                first.pack_store.active_version(entry.manifest.pack_id),
            )
            self.assertEqual(1, len(downloader.calls))

            restarted = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=_Playback(),
            )
            self.assertEqual(
                entry.manifest.pack_id,
                restarted.profile_manager.current.pack_id,
            )
            local = next(
                item for item in restarted.settings.snapshot(language="en")["packs"]
                if item["pack_id"] == entry.manifest.pack_id
            )
            self.assertEqual("local_installed", local["state"])
            self.assertTrue(local["can_uninstall"])
            self.assertTrue(local["rights_auditable"])
            self.assertEqual(
                entry.rights_evidence.source_uri,
                local["rights_source_uri"],
            )
            self.assertEqual(
                entry.rights_evidence.license_uri,
                local["license_uri"],
            )
            self.assertEqual(
                entry.rights_evidence,
                restarted.pack_store.rights_evidence(entry.manifest.pack_id),
            )

            removed = restarted.settings.uninstall_pack(
                entry.manifest.pack_id,
                language="en",
            )

            self.assertTrue(removed.ok)
            self.assertEqual("classic", restarted.profile_manager.current.pack_id)
            self.assertNotIn(
                entry.manifest.pack_id,
                restarted.pack_store.installed(),
            )

    def test_provider_update_without_candidate_rights_never_reaches_downloader_or_replaces_v1(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-provider-rights-gap-") as raw:
            root = Path(raw)
            pack_id = "remote.wood"
            v1 = _pack_manifest(pack_id)
            entry1, staging1 = _catalog_entry_from_manifest(
                root,
                v1,
                staging_name="provider-v1-rights",
            )
            first = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=_Playback(),
                catalog={pack_id: entry1},
                pack_downloader=_StagedDownloader(entry1, staging1),
            )
            first.settings.install_pack(pack_id, activate=True, language="en")

            v2_base = _pack_manifest(pack_id)
            v2 = SoundPackManifest(
                pack_id=pack_id,
                version="2.0.0",
                title=v2_base.title,
                license_id=v2_base.license_id,
                files=dict(v2_base.files),
                author=v2_base.author,
                provenance=v2_base.provenance,
            )
            audited_entry2, staging2 = _catalog_entry_from_manifest(
                root,
                v2,
                staging_name="provider-v2-rights-gap",
            )
            unaudited_entry2 = SoundPackCatalogEntry(
                manifest=audited_entry2.manifest,
                assets=audited_entry2.assets,
                total_bytes=audited_entry2.total_bytes,
            )
            downloader2 = _StagedDownloader(unaudited_entry2, staging2)
            second = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=_Playback(),
                catalog={pack_id: unaudited_entry2},
                pack_downloader=downloader2,
            )

            before = second.settings.snapshot(language="en")["packs"][0]
            self.assertEqual("different_version", before["state"])
            self.assertTrue(before["rights_auditable"])
            self.assertEqual(
                entry1.rights_evidence.source_uri,
                before["rights_source_uri"],
            )
            self.assertFalse(before["catalog_rights_auditable"])
            self.assertFalse(before["can_install"])

            with self.assertRaisesRegex(
                ValueError,
                "auditable license/provenance evidence",
            ):
                second.settings.install_pack(pack_id, activate=True, language="en")

            self.assertEqual([], downloader2.calls)
            self.assertEqual("1.0.0", second.pack_store.active_version(pack_id))
            self.assertEqual(("1.0.0",), second.pack_store.versions(pack_id))
            self.assertEqual(
                entry1.rights_evidence,
                second.pack_store.rights_evidence(pack_id),
            )

    def test_provider_update_normalizes_removed_sound_choice_and_preserves_event_controls(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-provider-update-") as raw:
            root = Path(raw)
            pack_id = "remote.wood"
            v1_base = _pack_manifest(pack_id)
            v1_files = dict(v1_base.files)
            v1_files["quiet.move"] = "audio/quiet-move.wav"
            v1 = SoundPackManifest(
                pack_id=pack_id,
                version="1.0.0",
                title=v1_base.title,
                license_id=v1_base.license_id,
                files=v1_files,
                author=v1_base.author,
                provenance=v1_base.provenance,
            )
            entry1, staging1 = _catalog_entry_from_manifest(
                root,
                v1,
                staging_name="provider-v1",
            )
            first = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=_Playback(),
                catalog={pack_id: entry1},
                pack_downloader=_StagedDownloader(entry1, staging1),
            )
            first.settings.install_pack(pack_id, activate=True, language="en")
            first.settings.set_event(
                "move",
                enabled=False,
                volume_percent=37,
                sound_id="quiet.move",
                language="en",
            )

            v2_base = _pack_manifest(pack_id)
            v2 = SoundPackManifest(
                pack_id=pack_id,
                version="2.0.0",
                title=v2_base.title,
                license_id=v2_base.license_id,
                files=dict(v2_base.files),
                author=v2_base.author,
                provenance=v2_base.provenance,
            )
            entry2, staging2 = _catalog_entry_from_manifest(
                root,
                v2,
                staging_name="provider-v2",
            )
            second = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=_Playback(),
                catalog={pack_id: entry2},
                pack_downloader=_StagedDownloader(entry2, staging2),
            )
            before = second.settings.snapshot(language="en")["packs"][0]
            self.assertEqual("different_version", before["state"])
            self.assertTrue(before["rights_auditable"])
            self.assertEqual(
                entry1.rights_evidence.source_uri,
                before["rights_source_uri"],
            )
            self.assertTrue(before["catalog_rights_auditable"])
            self.assertEqual(
                entry2.rights_evidence.source_uri,
                before["catalog_rights_source_uri"],
            )
            self.assertTrue(before["can_install"])

            result = second.settings.install_pack(pack_id, activate=True, language="en")

            self.assertTrue(result.ok)
            updated_pack = result.snapshot["packs"][0]
            self.assertEqual("current", updated_pack["state"])
            self.assertEqual(
                entry2.rights_evidence.source_uri,
                updated_pack["rights_source_uri"],
            )
            self.assertEqual(
                entry2.rights_evidence,
                second.pack_store.rights_evidence(pack_id),
            )
            self.assertEqual(("1.0.0", "2.0.0"), second.pack_store.versions(pack_id))
            self.assertEqual("2.0.0", second.pack_store.active_version(pack_id))
            pref = second.profile_manager.current.preference_for("move")
            self.assertFalse(pref.enabled)
            self.assertEqual(37, pref.volume_percent)
            self.assertIsNone(pref.sound_id)
            move = next(
                item for item in result.snapshot["events"]
                if item["event_id"] == "move"
            )
            self.assertEqual("move", move["sound_id"])
            self.assertNotIn("quiet.move", move["sound_choices"])

    def test_corrupt_installed_provider_pack_is_projected_installable_and_repaired(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-provider-repair-") as raw:
            root = Path(raw)
            entry, staging = _catalog_entry(root)
            downloader = _StagedDownloader(entry, staging)
            first = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=_Playback(),
                catalog={entry.manifest.pack_id: entry},
                pack_downloader=downloader,
            )
            installed = first.settings.install_pack(
                entry.manifest.pack_id,
                activate=True,
                language="en",
            )
            self.assertTrue(installed.ok)

            version_dir = first.pack_store._version_dir(
                entry.manifest.pack_id,
                entry.manifest.version,
            )
            damaged = version_dir / entry.manifest.files["move"]
            damaged.write_bytes(b"tampered-installed-sound")
            self.assertNotIn(
                entry.manifest.pack_id,
                first.pack_store.installed(),
            )

            restarted = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=_Playback(),
                catalog={entry.manifest.pack_id: entry},
                pack_downloader=_StagedDownloader(entry, staging),
            )
            self.assertEqual(
                "classic",
                restarted.profile_manager.current.pack_id,
                "startup must fail safe while the installed pack is corrupt",
            )
            item = restarted.settings.snapshot(language="en")["packs"][0]
            self.assertEqual("not_installed", item["state"])
            self.assertTrue(item["can_install"])

            repaired = restarted.settings.install_pack(
                entry.manifest.pack_id,
                activate=True,
                language="en",
            )

            self.assertTrue(repaired.ok)
            self.assertEqual(
                entry.manifest.pack_id,
                restarted.profile_manager.current.pack_id,
            )
            self.assertEqual(
                entry.manifest,
                restarted.pack_store.installed()[entry.manifest.pack_id],
            )
            self.assertEqual(
                entry.manifest.version,
                restarted.pack_store.active_version(entry.manifest.pack_id),
            )

    def test_oversized_provider_catalog_is_rejected_before_iteration_or_filesystem_side_effects(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-provider-limit-") as raw:
            root = Path(raw)
            data = root / "data"

            with self.assertRaisesRegex(ValueError, "catalog exceeds"):
                create_local_sound_composition(
                    application_dir=root / "app",
                    data_root=data,
                    asset_playback=_Playback(),
                    catalog=_OversizedCatalog(),
                    pack_downloader=mock.Mock(download=mock.Mock()),
                )

            self.assertFalse(data.exists())

    def test_provider_catalog_requires_downloader_and_cannot_replace_classic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-provider-contract-") as raw:
            root = Path(raw)
            entry, staging = _catalog_entry(root)

            with self.assertRaisesRegex(ValueError, "requires a download provider"):
                create_local_sound_composition(
                    application_dir=root / "app",
                    data_root=root / "data-a",
                    asset_playback=_Playback(),
                    catalog={entry.manifest.pack_id: entry},
                )

            classic_entry, classic_staging = _catalog_entry(root / "classic", "classic")
            with self.assertRaisesRegex(ValueError, "cannot replace"):
                create_local_sound_composition(
                    application_dir=root / "app",
                    data_root=root / "data-b",
                    asset_playback=_Playback(),
                    catalog={"classic": classic_entry},
                    pack_downloader=_StagedDownloader(classic_entry, classic_staging),
                )

    def test_non_wav_provider_pack_is_visible_as_incompatible_not_installable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-provider-incompatible-") as raw:
            root = Path(raw)
            manifest = _pack_manifest("remote.ogg", ".ogg")
            assets = {
                relative: SoundAssetDigest(relative, 1, hashlib.sha256(b"x").hexdigest())
                for relative in sorted(set(manifest.files.values()))
            }
            entry = SoundPackCatalogEntry(
                manifest=manifest,
                assets=assets,
                total_bytes=sum(item.size_bytes for item in assets.values()),
            )

            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=_Playback(),
                catalog={manifest.pack_id: entry},
                pack_downloader=mock.Mock(download=mock.Mock()),
            )

            item = composition.settings.snapshot(language="en")["packs"][0]
            self.assertEqual("incompatible", item["state"])
            self.assertFalse(item["compatible"])
            self.assertFalse(item["can_install"])

    def test_composition_creates_dedicated_profile_pack_and_cache_roots(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-layout-") as raw:
            root = Path(raw)
            data = root / "data"
            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=data,
                asset_playback=_Playback(),
            )
            self.assertEqual(data / "sound-packs", composition.pack_store.root)
            self.assertEqual(data / "sound-profile.json", composition.profile_manager._storage.path)


if __name__ == "__main__":
    unittest.main()
