from __future__ import annotations

import inspect
import unittest

from acs.sound_pack_catalog import (
    DownloadedSoundPack,
    SoundAssetDigest,
    SoundPackCatalogEntry,
    SoundPackManager,
)
from acs.sound_pack_profile import SoundPackProfileCoordinator
from acs.sound_profile_store import SoundProfileManager
from acs.sound_profiles import CORE_SOUND_EVENTS, SoundPackManifest, SoundProfile


class ProfileStorage:
    def __init__(self, raw=None, *, operations=None):
        self.raw = raw
        self.operations = operations if operations is not None else []
        self.fail_writes = False

    def read_profile(self):
        return self.raw

    def write_profile_atomically(self, payload):
        self.operations.append(("profile.write", payload.get("pack_id")))
        if self.fail_writes:
            raise OSError("profile write failed")
        self.raw = dict(payload)


class PackStorage:
    def __init__(self, installed, *, operations=None):
        self.items = dict(installed)
        self.operations = operations if operations is not None else []
        self.fail_uninstall = False

    def installed(self):
        return dict(self.items)

    def install_atomically(self, downloaded):
        self.operations.append(("pack.install", downloaded.manifest.pack_id))
        self.items[downloaded.manifest.pack_id] = downloaded.manifest

    def uninstall(self, pack_id):
        self.operations.append(("pack.uninstall", pack_id))
        if self.fail_uninstall:
            raise OSError("pack uninstall failed")
        self.items.pop(pack_id, None)


class Downloader:
    def __init__(self, downloaded):
        self.downloaded = downloaded

    def download(self, entry, *, max_bytes):
        return self.downloaded


def manifest(pack_id="classic", version="1.0.0"):
    return SoundPackManifest(
        pack_id=pack_id,
        version=version,
        title=pack_id,
        license_id="CC0-1.0",
        files={event: f"audio/{event}.wav" for event in CORE_SOUND_EVENTS},
        author="Accessible Chess",
        provenance="https://example.invalid/sound-pack",
    )


def entry_for(item):
    assets = {
        path: SoundAssetDigest(path, index, f"{index:064x}")
        for index, path in enumerate(sorted(set(item.files.values())), start=1)
    }
    entry = SoundPackCatalogEntry(
        manifest=item,
        assets=assets,
        total_bytes=sum(asset.size_bytes for asset in assets.values()),
    )
    return entry, DownloadedSoundPack(
        manifest=item,
        assets=assets,
        total_bytes=entry.total_bytes,
        payload_ref=object(),
    )


def make_stack(*, active_pack="classic", include_active=True, operations=None):
    operations = operations if operations is not None else []
    classic = manifest("classic")
    installed = {"classic": classic}
    if include_active and active_pack != "classic":
        installed[active_pack] = manifest(active_pack)
    placeholder_entry, placeholder_download = entry_for(manifest("placeholder"))
    del placeholder_entry
    pack_storage = PackStorage(installed, operations=operations)
    pack_manager = SoundPackManager(Downloader(placeholder_download), pack_storage)
    profile = SoundProfile(pack_id=active_pack)
    profile_storage = ProfileStorage(profile.to_mapping(), operations=operations)
    profile_manager = SoundProfileManager(profile_storage, pack_manager)
    coordinator = SoundPackProfileCoordinator(pack_manager, profile_manager)
    coordinator.current_profile
    operations.clear()
    return coordinator, pack_manager, pack_storage, profile_storage


class SoundPackProfileCoordinatorTests(unittest.TestCase):
    def test_pack_manager_directly_satisfies_profile_resolver_contract(self):
        coordinator, pack_manager, _, _ = make_stack(active_pack="missing", include_active=False)
        self.assertEqual(pack_manager.resolve_usable_pack("missing"), "classic")
        self.assertEqual(coordinator.current_profile.pack_id, "classic")

    def test_install_and_activate_installs_before_profile_selection(self):
        operations = []
        coordinator, pack_manager, pack_storage, profile_storage = make_stack(operations=operations)
        new_manifest = manifest("soft.wood")
        new_entry, downloaded = entry_for(new_manifest)
        pack_manager._downloader = Downloader(downloaded)

        result = coordinator.install(new_entry, activate=True)

        self.assertTrue(result.activated)
        self.assertEqual(result.profile.pack_id, "soft.wood")
        self.assertEqual(profile_storage.raw["pack_id"], "soft.wood")
        self.assertIn("soft.wood", pack_storage.items)
        self.assertEqual(operations[:2], [("pack.install", "soft.wood"), ("profile.write", "soft.wood")])

    def test_install_without_activation_does_not_rewrite_profile(self):
        operations = []
        coordinator, pack_manager, pack_storage, _ = make_stack(operations=operations)
        new_manifest = manifest("soft.wood")
        new_entry, downloaded = entry_for(new_manifest)
        pack_manager._downloader = Downloader(downloaded)

        result = coordinator.install(new_entry)

        self.assertFalse(result.activated)
        self.assertEqual(result.profile.pack_id, "classic")
        self.assertEqual(operations, [("pack.install", "soft.wood")])
        self.assertIn("soft.wood", pack_storage.items)

    def test_active_uninstall_persists_fallback_before_deleting_assets(self):
        operations = []
        coordinator, _, pack_storage, profile_storage = make_stack(
            active_pack="soft.wood", operations=operations
        )

        result = coordinator.uninstall("soft.wood")

        self.assertTrue(result.removed)
        self.assertEqual(result.profile.pack_id, "classic")
        self.assertEqual(profile_storage.raw["pack_id"], "classic")
        self.assertNotIn("soft.wood", pack_storage.items)
        self.assertEqual(
            operations,
            [("profile.write", "classic"), ("pack.uninstall", "soft.wood")],
        )

    def test_profile_write_failure_prevents_active_pack_deletion(self):
        operations = []
        coordinator, _, pack_storage, profile_storage = make_stack(
            active_pack="soft.wood", operations=operations
        )
        profile_storage.fail_writes = True

        with self.assertRaisesRegex(OSError, "profile write failed"):
            coordinator.uninstall("soft.wood")

        self.assertIn("soft.wood", pack_storage.items)
        self.assertEqual(operations, [("profile.write", "classic")])

    def test_pack_delete_failure_leaves_safe_persisted_fallback(self):
        operations = []
        coordinator, _, pack_storage, profile_storage = make_stack(
            active_pack="soft.wood", operations=operations
        )
        pack_storage.fail_uninstall = True

        with self.assertRaisesRegex(OSError, "pack uninstall failed"):
            coordinator.uninstall("soft.wood")

        self.assertEqual(profile_storage.raw["pack_id"], "classic")
        self.assertIn("soft.wood", pack_storage.items)
        self.assertEqual(coordinator.current_profile.pack_id, "classic")

    def test_inactive_uninstall_does_not_rewrite_current_profile(self):
        operations = []
        coordinator, _, pack_storage, _ = make_stack(operations=operations)
        pack_storage.items["soft.wood"] = manifest("soft.wood")

        result = coordinator.uninstall("soft.wood")

        self.assertEqual(result.profile.pack_id, "classic")
        self.assertEqual(operations, [("pack.uninstall", "soft.wood")])

    def test_reconcile_persists_fallback_when_selected_pack_disappears(self):
        operations = []
        coordinator, _, _, profile_storage = make_stack(
            active_pack="missing", include_active=False, operations=operations
        )
        # Initial load already reconciles through SoundProfileManager. Re-introduce
        # a stale in-memory/persisted selection to exercise coordinator recovery.
        profile_storage.raw = SoundProfile(pack_id="missing").to_mapping()
        coordinator._profiles._current = SoundProfile(pack_id="missing")
        operations.clear()

        profile = coordinator.reconcile()

        self.assertEqual(profile.pack_id, "classic")
        self.assertEqual(profile_storage.raw["pack_id"], "classic")
        self.assertEqual(operations, [("profile.write", "classic")])

    def test_coordinator_is_platform_transport_and_playback_neutral(self):
        import acs.sound_pack_profile as module

        source = inspect.getsource(module).lower()
        for forbidden in ("winsound", "webview", "sqlite", "subprocess", "requests", "urllib", "soundruntime"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
