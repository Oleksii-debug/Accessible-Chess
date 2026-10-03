from __future__ import annotations

import inspect
import unittest

from acs.sound_pack_catalog import (
    DownloadedSoundPack,
    SoundAssetDigest,
    SoundPackCatalogEntry,
    SoundPackManager,
    SoundPackRightsEvidence,
)
from acs.sound_pack_profile import SoundPackProfileCoordinator
from acs.sound_profile_store import SoundProfileManager
from acs.sound_profiles import (
    CORE_SOUND_EVENTS,
    SoundEventPreference,
    SoundPackManifest,
    SoundProfile,
)


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
        self.fail_install = False
        self.commit_then_fail_install = False
        self.fail_uninstall = False
        self.commit_then_fail_uninstall = False

    def installed(self):
        return dict(self.items)

    def install_atomically(self, downloaded):
        self.operations.append(("pack.install", downloaded.manifest.pack_id))
        if self.fail_install:
            raise OSError("pack install failed")
        self.items[downloaded.manifest.pack_id] = downloaded.manifest
        if self.commit_then_fail_install:
            raise OSError("pack install failed after active publication")

    def uninstall(self, pack_id):
        self.operations.append(("pack.uninstall", pack_id))
        if self.fail_uninstall:
            raise OSError("pack uninstall failed")
        self.items.pop(pack_id, None)
        if self.commit_then_fail_uninstall:
            raise OSError("pack uninstall failed after removal")


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
        rights_evidence=SoundPackRightsEvidence(
            license_id=item.license_id,
            source_uri=f"https://example.invalid/source/{item.pack_id}/{item.version}",
            license_uri="https://creativecommons.org/publicdomain/zero/1.0/",
        ),
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

    def test_activate_different_pack_clears_even_same_spelled_asset_id(self):
        operations = []
        coordinator, pack_manager, pack_storage, profile_storage = make_stack(
            active_pack="soft.wood",
            operations=operations,
        )
        old_files = dict(pack_storage.items["soft.wood"].files)
        old_files["shared.soft"] = "audio/old-shared.wav"
        old_manifest = SoundPackManifest(
            pack_id="soft.wood",
            version="1.0.0",
            title="soft.wood",
            license_id="CC0-1.0",
            files=old_files,
            author="Accessible Chess",
            provenance="https://example.invalid/sound-pack",
        )
        pack_storage.items["soft.wood"] = old_manifest
        current = SoundProfile(
            pack_id="soft.wood",
            events={"move": SoundEventPreference(False, 44, "shared.soft")},
        )
        coordinator._profiles._current = current
        profile_storage.raw = current.to_mapping()

        target_base = manifest("other.pack")
        target_files = dict(target_base.files)
        target_files["shared.soft"] = "audio/new-shared.wav"
        target = SoundPackManifest(
            pack_id="other.pack",
            version="1.0.0",
            title="other.pack",
            license_id="CC0-1.0",
            files=target_files,
            author="Accessible Chess",
            provenance="https://example.invalid/sound-pack",
        )
        entry, downloaded = entry_for(target)
        pack_manager._downloader = Downloader(downloaded)

        result = coordinator.install(entry, activate=True)

        self.assertEqual("other.pack", result.profile.pack_id)
        self.assertEqual(
            SoundEventPreference(False, 44),
            result.profile.preference_for("move"),
        )

    def test_active_pack_update_sanitizes_removed_asset_before_storage_switch(self):
        operations = []
        coordinator, pack_manager, pack_storage, profile_storage = make_stack(
            active_pack="soft.wood",
            operations=operations,
        )
        current = SoundProfile(
            pack_id="soft.wood",
            events={"move": SoundEventPreference(False, 44, "quiet.move")},
        )
        coordinator._profiles._current = current
        profile_storage.raw = current.to_mapping()
        new_manifest = manifest("soft.wood", version="2.0.0")
        new_entry, downloaded = entry_for(new_manifest)
        pack_manager._downloader = Downloader(downloaded)

        result = coordinator.install(new_entry)

        self.assertFalse(result.activated)
        self.assertEqual("2.0.0", pack_storage.items["soft.wood"].version)
        self.assertEqual(
            SoundEventPreference(False, 44),
            result.profile.preference_for("move"),
        )
        self.assertEqual(
            operations[:2],
            [("profile.write", "soft.wood"), ("pack.install", "soft.wood")],
        )

    def test_active_pack_update_failure_restores_exact_previous_profile(self):
        operations = []
        coordinator, pack_manager, pack_storage, profile_storage = make_stack(
            active_pack="soft.wood",
            operations=operations,
        )
        old_base = pack_storage.items["soft.wood"]
        old_files = dict(old_base.files)
        old_files["quiet.move"] = "audio/quiet-move.wav"
        pack_storage.items["soft.wood"] = SoundPackManifest(
            pack_id=old_base.pack_id,
            version=old_base.version,
            title=old_base.title,
            license_id=old_base.license_id,
            files=old_files,
            author=old_base.author,
            provenance=old_base.provenance,
        )
        current = SoundProfile(
            pack_id="soft.wood",
            master_enabled=False,
            master_volume_percent=61,
            events={"move": SoundEventPreference(False, 44, "quiet.move")},
        )
        coordinator._profiles._current = current
        profile_storage.raw = current.to_mapping()
        new_manifest = manifest("soft.wood", version="2.0.0")
        new_entry, downloaded = entry_for(new_manifest)
        pack_manager._downloader = Downloader(downloaded)
        pack_storage.fail_install = True

        with self.assertRaisesRegex(OSError, "pack install failed"):
            coordinator.install(new_entry)

        self.assertEqual("1.0.0", pack_storage.items["soft.wood"].version)
        self.assertEqual(current, coordinator.current_profile)
        self.assertEqual(current.to_mapping(), profile_storage.raw)
        self.assertEqual(
            operations,
            [
                ("profile.write", "soft.wood"),
                ("pack.install", "soft.wood"),
                ("profile.write", "soft.wood"),
            ],
        )

    def test_active_update_recovery_write_failure_preserves_primary_pack_error(self):
        operations = []
        coordinator, pack_manager, pack_storage, profile_storage = make_stack(
            active_pack="soft.wood",
            operations=operations,
        )
        old_base = pack_storage.items["soft.wood"]
        old_files = dict(old_base.files)
        old_files["quiet.move"] = "audio/quiet-move.wav"
        pack_storage.items["soft.wood"] = SoundPackManifest(
            pack_id=old_base.pack_id,
            version=old_base.version,
            title=old_base.title,
            license_id=old_base.license_id,
            files=old_files,
            author=old_base.author,
            provenance=old_base.provenance,
        )
        current = SoundProfile(
            pack_id="soft.wood",
            events={"move": SoundEventPreference(False, 44, "quiet.move")},
        )
        coordinator._profiles._current = current
        profile_storage.raw = current.to_mapping()

        writes = 0
        real_write = profile_storage.write_profile_atomically

        def fail_only_recovery(payload):
            nonlocal writes
            writes += 1
            if writes == 2:
                profile_storage.operations.append(
                    ("profile.write", payload.get("pack_id"))
                )
                raise OSError("recovery profile write failed")
            return real_write(payload)

        profile_storage.write_profile_atomically = fail_only_recovery
        new_manifest = manifest("soft.wood", version="2.0.0")
        new_entry, downloaded = entry_for(new_manifest)
        pack_manager._downloader = Downloader(downloaded)
        pack_storage.fail_install = True

        with self.assertRaisesRegex(OSError, "^pack install failed$") as caught:
            coordinator.install(new_entry)

        self.assertIn(
            "sound profile recovery after pack-install failure also failed",
            getattr(caught.exception, "__notes__", ()),
        )
        self.assertEqual("1.0.0", pack_storage.items["soft.wood"].version)
        self.assertIsNone(
            coordinator.current_profile.preference_for("move").sound_id,
            "failed recovery must retain the pre-install default-safe mapping",
        )
        self.assertEqual(
            operations,
            [
                ("profile.write", "soft.wood"),
                ("pack.install", "soft.wood"),
                ("profile.write", "soft.wood"),
            ],
        )

    def test_active_update_uncertain_commit_keeps_profile_valid_for_published_version(self):
        operations = []
        coordinator, pack_manager, pack_storage, profile_storage = make_stack(
            active_pack="soft.wood",
            operations=operations,
        )
        old_base = pack_storage.items["soft.wood"]
        old_files = dict(old_base.files)
        old_files["quiet.move"] = "audio/quiet-move.wav"
        pack_storage.items["soft.wood"] = SoundPackManifest(
            pack_id=old_base.pack_id,
            version=old_base.version,
            title=old_base.title,
            license_id=old_base.license_id,
            files=old_files,
            author=old_base.author,
            provenance=old_base.provenance,
        )
        current = SoundProfile(
            pack_id="soft.wood",
            events={"move": SoundEventPreference(False, 44, "quiet.move")},
        )
        coordinator._profiles._current = current
        profile_storage.raw = current.to_mapping()

        new_manifest = manifest("soft.wood", version="2.0.0")
        new_entry, downloaded = entry_for(new_manifest)
        pack_manager._downloader = Downloader(downloaded)
        pack_storage.commit_then_fail_install = True

        with self.assertRaisesRegex(OSError, "after active publication"):
            coordinator.install(new_entry)

        self.assertEqual("2.0.0", pack_storage.items["soft.wood"].version)
        self.assertEqual("soft.wood", coordinator.current_profile.pack_id)
        self.assertEqual(
            SoundEventPreference(False, 44),
            coordinator.current_profile.preference_for("move"),
        )
        self.assertEqual(coordinator.current_profile.to_mapping(), profile_storage.raw)

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

    def test_uncertain_uninstall_commit_never_restores_profile_to_removed_pack(self):
        operations = []
        coordinator, _, pack_storage, profile_storage = make_stack(
            active_pack="soft.wood", operations=operations
        )
        pack_storage.commit_then_fail_uninstall = True

        with self.assertRaisesRegex(
            OSError,
            "pack uninstall failed after removal",
        ):
            coordinator.uninstall("soft.wood")

        self.assertEqual("classic", profile_storage.raw["pack_id"])
        self.assertEqual("classic", coordinator.current_profile.pack_id)
        self.assertNotIn("soft.wood", pack_storage.items)
        self.assertEqual(
            operations,
            [("profile.write", "classic"), ("pack.uninstall", "soft.wood")],
        )

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
