from __future__ import annotations

import hashlib
import unittest

from acs.sound_pack_catalog import (
    DownloadedSoundPack,
    SoundAssetDigest,
    SoundPackCatalogEntry,
    SoundPackManager,
)
from acs.sound_pack_profile import SoundPackProfileCoordinator
from acs.sound_profile_store import SoundProfileManager, SoundProfileWriteBlockedError
from acs.sound_profiles import CORE_SOUND_EVENTS, SoundPackManifest
from acs.sound_runtime import ProfiledSoundRuntime, SoundAssetRequest
from acs.sound_settings_application import SoundSettingsApplication


class _ProfileStorage:
    def __init__(self, initial=None):
        self.payload = initial
        self.writes = []

    def read_profile(self):
        return self.payload

    def write_profile_atomically(self, payload):
        self.payload = dict(payload)
        self.writes.append(dict(payload))


class _AssetPlayback:
    def __init__(self):
        self.requests: list[SoundAssetRequest] = []

    def play_sound(self, request: SoundAssetRequest) -> None:
        self.requests.append(request)


class _PackStorage:
    def __init__(self, manifests):
        self.manifests = {manifest.pack_id: manifest for manifest in manifests}
        self.installed_payloads = []
        self.uninstalled = []

    def installed(self):
        return dict(self.manifests)

    def install_atomically(self, downloaded: DownloadedSoundPack) -> None:
        self.manifests[downloaded.manifest.pack_id] = downloaded.manifest
        self.installed_payloads.append(downloaded.payload_ref)

    def uninstall(self, pack_id: str) -> None:
        self.uninstalled.append(pack_id)
        self.manifests.pop(pack_id, None)


class _Downloader:
    def __init__(self):
        self.entries = []

    def download(self, entry: SoundPackCatalogEntry, *, max_bytes: int):
        self.entries.append((entry.manifest.pack_id, max_bytes))
        return DownloadedSoundPack(
            manifest=entry.manifest,
            assets=entry.assets,
            total_bytes=entry.total_bytes,
            payload_ref={"private": "opaque-staged-payload"},
        )


def _manifest(pack_id: str, version: str = "1.0.0") -> SoundPackManifest:
    return SoundPackManifest(
        pack_id=pack_id,
        version=version,
        title=f"{pack_id} title",
        license_id="CC0-1.0",
        author="Accessible Chess test author",
        provenance="tests-only generated wave identities",
        files={event: f"audio/{event}.wav" for event in CORE_SOUND_EVENTS},
    )


def _entry(manifest: SoundPackManifest, *, compatible: bool = True) -> SoundPackCatalogEntry:
    assets = {}
    for path in manifest.files.values():
        payload = path.encode("utf-8")
        assets[path] = SoundAssetDigest(
            path=path,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )
    return SoundPackCatalogEntry(
        manifest=manifest,
        assets=assets,
        total_bytes=sum(asset.size_bytes for asset in assets.values()),
        compatible=compatible,
    )


class SoundSettingsApplicationTests(unittest.TestCase):
    def _profile_runtime(self, *, initial=None, resolver=None):
        storage = _ProfileStorage(initial)
        manager = SoundProfileManager(storage, resolver or (lambda _pack: "classic"))
        manager.load()
        playback = _AssetPlayback()
        runtime = ProfiledSoundRuntime(playback, manager.profile_provider)
        return storage, manager, playback, runtime

    def test_snapshot_exposes_all_events_without_paths_or_payload_refs(self) -> None:
        _storage, manager, _playback, runtime = self._profile_runtime()
        app = SoundSettingsApplication(manager, runtime)

        snapshot = app.snapshot(language="en")

        self.assertEqual(CORE_SOUND_EVENTS, tuple(item["event_id"] for item in snapshot["events"]))
        self.assertEqual("classic", snapshot["active_pack_id"])
        rendered = repr(snapshot)
        self.assertNotIn("payload_ref", rendered)
        self.assertNotIn("local_path", rendered)
        self.assertNotIn("audio/", rendered)

    def test_master_and_per_event_edits_persist_through_single_profile_manager(self) -> None:
        storage, manager, _playback, runtime = self._profile_runtime()
        app = SoundSettingsApplication(manager, runtime)

        app.set_master(enabled=False, volume_percent=55, language="en")
        app.set_event("capture", enabled=True, volume_percent=35, sound_id="capture.alt", language="en")

        self.assertFalse(manager.current.master_enabled)
        self.assertEqual(55, manager.current.master_volume_percent)
        capture = manager.current.preference_for("capture")
        self.assertTrue(capture.enabled)
        self.assertEqual(35, capture.volume_percent)
        self.assertEqual("capture.alt", capture.sound_id)
        self.assertGreaterEqual(len(storage.writes), 3)  # initial canonical + two edits

    def test_preview_uses_profiled_runtime_and_respects_effective_volume(self) -> None:
        _storage, manager, playback, runtime = self._profile_runtime()
        app = SoundSettingsApplication(manager, runtime)
        app.set_master(volume_percent=50)
        app.set_event("check", volume_percent=40, sound_id="check.soft")

        result = app.preview("check", language="en")

        self.assertTrue(result.ok)
        self.assertEqual(1, len(playback.requests))
        request = playback.requests[0]
        self.assertTrue(request.preview)
        self.assertEqual("check", request.event_id)
        self.assertEqual("check.soft", request.sound_id)
        self.assertEqual(20, request.volume)

    def test_muted_preview_never_touches_playback(self) -> None:
        _storage, manager, playback, runtime = self._profile_runtime()
        app = SoundSettingsApplication(manager, runtime)
        app.set_event("move", enabled=False)

        result = app.preview("move", language="en")

        self.assertIn("muted", result.announcement.lower())
        self.assertEqual([], playback.requests)

    def test_unknown_browser_event_fails_closed(self) -> None:
        _storage, manager, _playback, runtime = self._profile_runtime()
        app = SoundSettingsApplication(manager, runtime)
        with self.assertRaisesRegex(ValueError, "unknown sound event"):
            app.set_event("browser.supplied.event", enabled=True)
        with self.assertRaisesRegex(ValueError, "unknown sound event"):
            app.preview("browser.supplied.event")

    def test_future_schema_blocks_ordinary_ui_mutation(self) -> None:
        initial = {"schema_version": 999, "pack_id": "classic"}
        storage = _ProfileStorage(initial)
        manager = SoundProfileManager(storage, lambda _pack: "classic")
        result = manager.load()
        self.assertTrue(result.writes_blocked)
        playback = _AssetPlayback()
        runtime = ProfiledSoundRuntime(playback, manager.profile_provider)
        app = SoundSettingsApplication(manager, runtime)

        snapshot = app.snapshot()
        self.assertTrue(snapshot["writes_blocked"])
        with self.assertRaises(SoundProfileWriteBlockedError):
            app.set_master(enabled=False)
        self.assertEqual(initial, storage.payload)

    def test_verified_local_installed_pack_is_discoverable_and_selectable_without_remote_catalog(self) -> None:
        base = _manifest("local.wood")
        files = dict(base.files)
        files["quiet.move"] = "audio/quiet-move.wav"
        files["classroom.join"] = "audio/classroom-join.wav"
        local = SoundPackManifest(
            pack_id=base.pack_id,
            version=base.version,
            title=base.title,
            license_id=base.license_id,
            files=files,
            author=base.author,
            provenance=base.provenance,
        )
        _storage, manager, _playback, runtime = self._profile_runtime(
            resolver=lambda requested: requested if requested in {"classic", "local.wood"} else "classic"
        )
        app = SoundSettingsApplication(
            manager,
            runtime,
            installed_pack_provider=lambda: {"local.wood": local},
        )

        snapshot = app.snapshot(language="en")
        self.assertFalse(snapshot["can_select_classic"])
        self.assertEqual(1, len(snapshot["packs"]))
        item = snapshot["packs"][0]
        self.assertEqual("local.wood", item["pack_id"])
        self.assertEqual("local_installed", item["state"])
        self.assertEqual("1.0.0", item["installed_version"])
        self.assertFalse(item["can_install"])
        self.assertFalse(item["can_uninstall"])

        result = app.select_pack("local.wood", language="en")
        self.assertTrue(result.ok)
        self.assertEqual("local.wood", manager.current.pack_id)
        self.assertTrue(result.snapshot["can_select_classic"])
        event_ids = {item["event_id"] for item in result.snapshot["events"]}
        self.assertIn("classroom.join", event_ids)
        move = next(item for item in result.snapshot["events"] if item["event_id"] == "move")
        self.assertIn("quiet.move", move["sound_choices"])

        changed = app.set_event("move", sound_id="quiet.move", language="en")
        self.assertEqual("quiet.move", manager.current.preference_for("move").sound_id)
        changed_move = next(
            item for item in changed.snapshot["events"] if item["event_id"] == "move"
        )
        self.assertEqual("quiet.move", changed_move["sound_id"])

        classroom = app.set_event(
            "classroom.join",
            enabled=False,
            volume_percent=35,
            language="en",
        )
        classroom_item = next(
            item for item in classroom.snapshot["events"]
            if item["event_id"] == "classroom.join"
        )
        self.assertFalse(classroom_item["enabled"])
        self.assertEqual(35, classroom_item["volume_percent"])

        with self.assertRaisesRegex(ValueError, "not available"):
            app.set_event("move", sound_id="missing.sound")
        with self.assertRaisesRegex(ValueError, "unknown sound event"):
            app.set_event("classroom.leave", enabled=False)

        classic = app.select_pack("classic", language="en")
        self.assertTrue(classic.ok)
        self.assertEqual("classic", manager.current.pack_id)
        self.assertFalse(classic.snapshot["can_select_classic"])

        with self.assertRaisesRegex(ValueError, "unknown sound pack"):
            app.select_pack("missing.pack")

    def test_classic_provider_rejects_arbitrary_sound_remap(self) -> None:
        _storage, manager, _playback, runtime = self._profile_runtime()
        app = SoundSettingsApplication(
            manager,
            runtime,
            installed_pack_provider=lambda: {},
        )
        with self.assertRaisesRegex(ValueError, "not available"):
            app.set_event("move", sound_id="quiet.move")

    def test_installed_pack_provider_rejects_unverified_shapes(self) -> None:
        _storage, manager, _playback, runtime = self._profile_runtime()
        app = SoundSettingsApplication(
            manager,
            runtime,
            installed_pack_provider=lambda: {"bad": object()},
        )
        with self.assertRaisesRegex(TypeError, "invalid mapping"):
            app.snapshot()

    def test_catalog_projection_and_install_use_closed_world_entry(self) -> None:
        classic = _manifest("classic")
        soft = _manifest("soft")
        entry = _entry(soft)
        pack_storage = _PackStorage([classic])
        downloader = _Downloader()
        pack_manager = SoundPackManager(downloader, pack_storage)
        profile_storage = _ProfileStorage()
        profile_manager = SoundProfileManager(profile_storage, pack_manager)
        profile_manager.load()
        playback = _AssetPlayback()
        runtime = ProfiledSoundRuntime(playback, profile_manager.profile_provider)
        coordinator = SoundPackProfileCoordinator(pack_manager, profile_manager)
        app = SoundSettingsApplication(
            profile_manager,
            runtime,
            pack_coordinator=coordinator,
            catalog={"soft": entry},
        )

        before = app.snapshot(language="en")["packs"][0]
        self.assertEqual("not_installed", before["state"])
        self.assertTrue(before["can_install"])
        self.assertNotIn("files", before)
        self.assertNotIn("provenance", before)

        app.install_pack("soft", activate=True, language="en")
        after = app.snapshot(language="en")["packs"][0]
        self.assertEqual("current", after["state"])
        self.assertTrue(after["active"])
        self.assertEqual("soft", profile_manager.current.pack_id)
        self.assertEqual(["soft"], [pack for pack, _limit in downloader.entries])

    def test_unknown_pack_id_cannot_supply_manifest_or_path(self) -> None:
        classic = _manifest("classic")
        storage = _PackStorage([classic])
        manager = SoundPackManager(_Downloader(), storage)
        profile_storage = _ProfileStorage()
        profiles = SoundProfileManager(profile_storage, manager)
        profiles.load()
        runtime = ProfiledSoundRuntime(_AssetPlayback(), profiles.profile_provider)
        coordinator = SoundPackProfileCoordinator(manager, profiles)
        app = SoundSettingsApplication(profiles, runtime, pack_coordinator=coordinator, catalog={})

        with self.assertRaisesRegex(ValueError, "unknown sound pack"):
            app.install_pack("../../evil")
        with self.assertRaisesRegex(ValueError, "unknown sound pack"):
            app.select_pack("file.c:/secret")

    def test_uninstall_active_pack_persists_fallback_before_storage_delete(self) -> None:
        classic = _manifest("classic")
        soft = _manifest("soft")
        entry = _entry(soft)
        pack_storage = _PackStorage([classic, soft])
        manager = SoundPackManager(_Downloader(), pack_storage)
        profile_storage = _ProfileStorage(
            {
                "schema_version": 1,
                "pack_id": "soft",
                "master_enabled": True,
                "master_volume_percent": 80,
                "events": {},
            }
        )
        profiles = SoundProfileManager(profile_storage, manager)
        profiles.load()
        runtime = ProfiledSoundRuntime(_AssetPlayback(), profiles.profile_provider)
        coordinator = SoundPackProfileCoordinator(manager, profiles)
        app = SoundSettingsApplication(
            profiles, runtime, pack_coordinator=coordinator, catalog={"soft": entry}
        )

        app.uninstall_pack("soft", language="en")

        self.assertEqual("classic", profiles.current.pack_id)
        self.assertEqual("classic", profile_storage.payload["pack_id"])
        self.assertEqual(["soft"], pack_storage.uninstalled)


if __name__ == "__main__":
    unittest.main()
