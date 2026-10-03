from __future__ import annotations

import hashlib
import os
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import wave

from acs.sound_pack_catalog import (
    DownloadedSoundPack,
    SoundAssetDigest,
    SoundPackRightsEvidence,
)
from acs.sound_pack_store import FilesystemSoundPackStore, SoundPackStoreError
from acs.sound_profiles import CORE_SOUND_EVENTS, SoundPackManifest


def _wav(seed: bytes) -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(8000)
        frame = (seed[:1] or b"x")[0]
        writer.writeframes(bytes((frame, 0)) * 8)
    return stream.getvalue()


def _manifest(
    *,
    pack_id: str = "soft.wood",
    version: str = "1.0.0",
    title: str = "Soft Wood",
) -> SoundPackManifest:
    return SoundPackManifest(
        pack_id=pack_id,
        version=version,
        title=title,
        license_id="CC0-1.0",
        files={
            event: f"audio/{event}.wav"
            for event in CORE_SOUND_EVENTS
        },
        author="Accessible Chess",
        provenance="Project-authored deterministic test sounds.",
    )


def _payloads(manifest: SoundPackManifest, *, seed: bytes = b"a") -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for index, path in enumerate(sorted(set(manifest.files.values()))):
        result[path] = _wav(seed + bytes((index % 251,)))
    return result


def _staged_download(
    root: Path,
    manifest: SoundPackManifest,
    *,
    seed: bytes = b"a",
) -> tuple[DownloadedSoundPack, dict[str, bytes]]:
    payloads = _payloads(manifest, seed=seed)
    stage = root / f"stage-{manifest.pack_id}-{manifest.version}-{seed.hex()}"
    for relative, data in payloads.items():
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    assets = {
        path: SoundAssetDigest(
            path=path,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        for path, data in payloads.items()
    }
    return (
        DownloadedSoundPack(
            manifest=manifest,
            assets=assets,
            total_bytes=sum(len(data) for data in payloads.values()),
            payload_ref=stage,
        ),
        payloads,
    )


def _with_rights(
    downloaded: DownloadedSoundPack,
    *,
    source_suffix: str = "primary",
) -> DownloadedSoundPack:
    manifest = downloaded.manifest
    return DownloadedSoundPack(
        manifest=manifest,
        assets=downloaded.assets,
        total_bytes=downloaded.total_bytes,
        payload_ref=downloaded.payload_ref,
        rights_evidence=SoundPackRightsEvidence(
            license_id=manifest.license_id,
            source_uri=(
                f"https://example.invalid/source/{manifest.pack_id}/"
                f"{manifest.version}/{source_suffix}"
            ),
            license_uri="https://creativecommons.org/publicdomain/zero/1.0/",
        ),
    )


class FilesystemSoundPackStoreTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "ordinary Windows runners cannot reliably create symlinks")
    def test_nested_asset_staging_rejects_redirected_parent_before_escape_creation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source.wav"
            payload = _wav(b"x")
            source.write_bytes(payload)
            digest = SoundAssetDigest(
                "audio/nested/move.wav",
                len(payload),
                hashlib.sha256(payload).hexdigest(),
            )
            staging = root / "staging"
            staging.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (staging / "audio").symlink_to(outside, target_is_directory=True)
            escaped_parent = outside / "nested"

            with self.assertRaisesRegex(SoundPackStoreError, "redirected"):
                FilesystemSoundPackStore._copy_verified(
                    source,
                    staging / digest.path,
                    digest,
                )

            self.assertFalse(
                escaped_parent.exists(),
                "redirect validation must precede mkdir for nested staged assets",
            )

    @unittest.skipIf(os.name == "nt", "ordinary Windows runners cannot reliably create symlinks")
    def test_metadata_writer_rejects_redirected_parent_before_escape_creation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            staging = root / "staging"
            staging.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (staging / "metadata").symlink_to(outside, target_is_directory=True)
            escaped_parent = outside / "nested"

            with self.assertRaisesRegex(SoundPackStoreError, "redirected"):
                FilesystemSoundPackStore._write_new(
                    staging / "metadata" / "nested" / "proof.json",
                    b"{}\n",
                )

            self.assertFalse(
                escaped_parent.exists(),
                "redirect validation must precede mkdir for nested metadata",
            )

    @unittest.skipIf(os.name == "nt", "ordinary Windows runners cannot reliably create symlinks")
    def test_redirected_store_ancestor_is_rejected_for_reads_and_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            outside = root / "outside"
            outside.mkdir()
            redirected = root / "redirected"
            redirected.symlink_to(outside, target_is_directory=True)
            store = FilesystemSoundPackStore(redirected / "packs")
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)

            with self.assertRaisesRegex(SoundPackStoreError, "redirected"):
                store.install_atomically(downloaded)

            (outside / "packs").mkdir()
            with self.assertRaisesRegex(SoundPackStoreError, "redirected"):
                store.installed()
            self.assertEqual([], list((outside / "packs").iterdir()))

    @unittest.skipIf(os.name == "nt", "ordinary Windows runners cannot reliably create symlinks")
    def test_redirected_download_staging_ancestor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            outside = root / "outside"
            outside.mkdir()
            manifest = _manifest()
            staged, _ = _staged_download(outside, manifest)
            redirected = root / "redirected"
            redirected.symlink_to(outside, target_is_directory=True)
            redirected_download = DownloadedSoundPack(
                manifest=staged.manifest,
                assets=staged.assets,
                total_bytes=staged.total_bytes,
                payload_ref=redirected / Path(staged.payload_ref).name,
            )
            store = FilesystemSoundPackStore(root / "packs")

            with self.assertRaisesRegex(SoundPackStoreError, "redirected"):
                store.install_atomically(redirected_download)

            self.assertFalse((root / "packs").exists())


    def test_download_asset_swap_after_lstat_is_rejected_before_copy(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, payloads = _staged_download(root, manifest)
            target = Path(downloaded.payload_ref) / manifest.files["move"]
            replacement = target.with_name("replacement.wav")
            replacement.write_bytes(payloads[manifest.files["move"]])
            store = FilesystemSoundPackStore(root / "packs")
            real_open = os.open
            swapped = False

            def swap_before_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal swapped
                if Path(path) == target and not swapped:
                    swapped = True
                    os.replace(replacement, target)
                if dir_fd is None:
                    return real_open(path, flags, mode)
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch(
                "acs.sound_pack_store.os.open",
                side_effect=swap_before_open,
            ), self.assertRaisesRegex(
                SoundPackStoreError,
                "changed before secure copy",
            ):
                store.install_atomically(downloaded)

            self.assertTrue(swapped)
            self.assertIsNone(store.active_version(manifest.pack_id))

    def test_manifest_swap_after_lstat_is_rejected_before_metadata_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            store = FilesystemSoundPackStore(root / "packs")
            store.install_atomically(downloaded)
            version_dir = (
                store.root
                / manifest.pack_id
                / "versions"
                / manifest.version
            )
            target = version_dir / "manifest.json"
            replacement = version_dir / ".replacement-manifest.json"
            replacement.write_bytes(target.read_bytes())
            real_open = os.open
            swapped = False

            def swap_before_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal swapped
                if Path(path) == target and not swapped:
                    swapped = True
                    os.replace(replacement, target)
                if dir_fd is None:
                    return real_open(path, flags, mode)
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch(
                "acs.sound_pack_store.os.open",
                side_effect=swap_before_open,
            ), self.assertRaisesRegex(
                SoundPackStoreError,
                "changed before secure read",
            ):
                store._read_manifest(version_dir)

            self.assertTrue(swapped)

    def test_rights_evidence_is_version_bound_and_survives_store_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store_root = root / "packs"
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            downloaded = _with_rights(downloaded)

            store = FilesystemSoundPackStore(store_root)
            store.install_atomically(downloaded)

            self.assertEqual(downloaded.rights_evidence, store.rights_evidence(manifest.pack_id))
            reopened = FilesystemSoundPackStore(store_root)
            self.assertEqual(manifest, reopened.installed()[manifest.pack_id])
            self.assertEqual(
                downloaded.rights_evidence,
                reopened.rights_evidence(manifest.pack_id),
            )

    def test_same_version_cannot_equivocate_durable_rights_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            first = _with_rights(downloaded, source_suffix="first")
            conflicting = _with_rights(downloaded, source_suffix="conflicting")
            store.install_atomically(first)

            with self.assertRaisesRegex(
                SoundPackStoreError,
                "already exists with different content",
            ):
                store.install_atomically(conflicting)

            self.assertEqual(first.rights_evidence, store.rights_evidence(manifest.pack_id))

    def test_tampered_rights_evidence_invalidates_installed_pack_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            downloaded = _with_rights(downloaded)
            store.install_atomically(downloaded)

            rights_path = (
                store.root
                / manifest.pack_id
                / "versions"
                / manifest.version
                / "rights.json"
            )
            rights_path.write_text(
                '{"schema_version":1,"license_id":"CC0-1.0",'
                '"license_uri":"https://creativecommons.org/publicdomain/zero/1.0/",'
                '"source_uri":"https://example.invalid/tampered-source"}\n',
                encoding="utf-8",
            )

            self.assertNotIn(manifest.pack_id, store.installed())
            self.assertIsNone(store.rights_evidence(manifest.pack_id))

    def test_v2_integrity_rejects_injected_unbound_rights_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            store.install_atomically(downloaded)

            version_dir = (
                store.root
                / manifest.pack_id
                / "versions"
                / manifest.version
            )
            injected = SoundPackRightsEvidence(
                license_id=manifest.license_id,
                source_uri="https://example.invalid/injected-source",
                license_uri="https://creativecommons.org/publicdomain/zero/1.0/",
            )
            (version_dir / "rights.json").write_text(
                json.dumps(
                    injected.to_mapping(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertNotIn(manifest.pack_id, store.installed())
            self.assertIsNone(store.rights_evidence(manifest.pack_id))

    def test_legacy_unbound_rights_remain_playable_but_are_not_audited(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            downloaded = _with_rights(downloaded)
            store.install_atomically(downloaded)

            version_dir = (
                store.root
                / manifest.pack_id
                / "versions"
                / manifest.version
            )
            legacy_integrity = {
                "schema_version": 1,
                "assets": {
                    path: {
                        "size_bytes": digest.size_bytes,
                        "sha256": digest.sha256,
                    }
                    for path, digest in sorted(downloaded.assets.items())
                },
            }
            (version_dir / "integrity.json").write_text(
                json.dumps(
                    legacy_integrity,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )

            reopened = FilesystemSoundPackStore(store.root)
            self.assertEqual(manifest, reopened.installed()[manifest.pack_id])
            self.assertIsNone(reopened.rights_evidence(manifest.pack_id))
            self.assertIsNotNone(reopened.resolve_asset(manifest.pack_id, "move"))

    def test_new_pack_directory_chain_is_durably_linked_parent_first(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store_root = root / "data" / "sound-packs"
            store_root.parent.mkdir(parents=True)
            store = FilesystemSoundPackStore(store_root)
            calls = []

            with mock.patch(
                "acs.sound_pack_store._fsync_directory",
                side_effect=lambda path: calls.append(Path(path)),
            ):
                pack_dir, versions = store._ensure_pack_parent("soft.wood")

            self.assertEqual(
                [store_root.parent, store_root, pack_dir],
                calls,
            )
            self.assertEqual(pack_dir / "versions", versions)

    def test_uninstall_flushes_sound_pack_root_after_top_level_removal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            store = FilesystemSoundPackStore(root / "packs")
            store.install_atomically(downloaded)

            with mock.patch(
                "acs.sound_pack_store._fsync_directory"
            ) as sync_directory:
                store.uninstall(manifest.pack_id)

            sync_directory.assert_called_once_with(store.root)
            self.assertNotIn(manifest.pack_id, store.installed())

    def test_install_rehashes_staged_bytes_and_publishes_active_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, payloads = _staged_download(root, manifest)
            store = FilesystemSoundPackStore(root / "packs")

            store.install_atomically(downloaded)

            self.assertEqual(store.installed()[manifest.pack_id], manifest)
            self.assertEqual(store.active_version(manifest.pack_id), "1.0.0")
            self.assertEqual(store.versions(manifest.pack_id), ("1.0.0",))
            resolved = store.resolve_asset(manifest.pack_id, "move")
            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertEqual(resolved.read_bytes(), payloads[manifest.files["move"]])
            self.assertTrue(
                (root / "packs" / manifest.pack_id / "active.json").is_file()
            )

    @unittest.skipIf(
        os.name == "nt",
        "ordinary Windows runners cannot reliably create symlinks",
    )
    def test_failed_install_cleanup_unlinks_redirected_staging_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            store = FilesystemSoundPackStore(root / "packs")
            outside = root / "outside"
            outside.mkdir()
            sentinel = outside / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")
            staged_root = None

            def redirect_staging_then_fail(source, destination, digest):
                nonlocal staged_root
                staged_root = destination.parents[1]
                staged_root.rmdir()
                staged_root.symlink_to(outside, target_is_directory=True)
                raise SoundPackStoreError("forced copy failure")

            with mock.patch.object(
                store,
                "_copy_verified",
                side_effect=redirect_staging_then_fail,
            ), self.assertRaisesRegex(
                SoundPackStoreError,
                "forced copy failure",
            ):
                store.install_atomically(downloaded)

            self.assertIsNotNone(staged_root)
            assert staged_root is not None
            self.assertFalse(os.path.lexists(staged_root))
            self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))

    def test_staging_directory_tree_is_flushed_before_version_publication(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            store = FilesystemSoundPackStore(root / "packs")
            order = []
            real_replace = os.replace

            def record_replace(source, destination):
                order.append(("replace", Path(source), Path(destination)))
                return real_replace(source, destination)

            with mock.patch(
                "acs.sound_pack_store._fsync_directory",
                side_effect=lambda path: order.append(("sync", Path(path))),
            ), mock.patch(
                "acs.sound_pack_store.os.replace",
                side_effect=record_replace,
            ):
                store.install_atomically(downloaded)

            version_replace_index = next(
                index
                for index, item in enumerate(order)
                if item[0] == "replace"
                and item[2].name == manifest.version
            )
            staging_syncs = [
                item[1]
                for item in order[:version_replace_index]
                if item[0] == "sync"
                and item[1].name.startswith(
                    f".{manifest.pack_id}-{manifest.version}-"
                )
            ]
            self.assertTrue(
                staging_syncs,
                "staging root must be synchronized before version rename",
            )
            self.assertTrue(
                any(path.name == "audio" for path in (
                    item[1]
                    for item in order[:version_replace_index]
                    if item[0] == "sync"
                )),
                "nested asset directory must be synchronized before publication",
            )

    def test_final_version_tamper_after_rename_never_advances_active_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            first = _manifest(version="1.0.0")
            first_download, _ = _staged_download(root, first, seed=b"a")
            store.install_atomically(first_download)

            second = _manifest(version="1.1.0")
            second_download, _ = _staged_download(root, second, seed=b"b")
            real_replace = os.replace
            tampered = False

            def tamper_after_version_publish(source, destination):
                nonlocal tampered
                result = real_replace(source, destination)
                destination = Path(destination)
                if destination.name == second.version and not tampered:
                    tampered = True
                    target = destination / second.files["move"]
                    target.write_bytes(b"tampered-after-rename")
                return result

            with mock.patch(
                "acs.sound_pack_store.os.replace",
                side_effect=tamper_after_version_publish,
            ), self.assertRaisesRegex(
                SoundPackStoreError,
                "checksum|size mismatch",
            ):
                store.install_atomically(second_download)

            self.assertTrue(tampered)
            self.assertEqual("1.0.0", store.active_version(first.pack_id))
            self.assertEqual(("1.0.0",), store.versions(first.pack_id))
            self.assertFalse(
                os.path.lexists(
                    store.root
                    / second.pack_id
                    / "versions"
                    / second.version
                )
            )

    def test_version_directory_is_flushed_before_active_pointer_publication(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            store = FilesystemSoundPackStore(root / "packs")
            order = []

            with mock.patch(
                "acs.sound_pack_store._fsync_directory",
                side_effect=lambda path: order.append(("sync", Path(path))),
            ), mock.patch.object(
                store,
                "_publish_active",
                side_effect=lambda pack_dir, pack_id, version: order.append(
                    ("active", Path(pack_dir))
                ),
            ):
                store.install_atomically(downloaded)

            versions_dir = root / "packs" / manifest.pack_id / "versions"
            version_sync_index = order.index(("sync", versions_dir))
            active_index = order.index(("active", versions_dir.parent))
            self.assertLess(
                version_sync_index,
                active_index,
                "version directory must be durable before active pointer publication",
            )

    def test_directory_sync_failure_never_advances_active_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            first = _manifest(version="1.0.0")
            first_download, _ = _staged_download(root, first, seed=b"a")
            store.install_atomically(first_download)
            second = _manifest(version="1.1.0")
            second_download, _ = _staged_download(root, second, seed=b"b")

            with mock.patch(
                "acs.sound_pack_store._fsync_directory",
                side_effect=SoundPackStoreError("directory sync failed"),
            ), self.assertRaisesRegex(SoundPackStoreError, "directory sync failed"):
                store.install_atomically(second_download)

            self.assertEqual("1.0.0", store.active_version(first.pack_id))
            self.assertEqual(first, store.installed()[first.pack_id])

    def test_inventory_asset_swap_after_lstat_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, payloads = _staged_download(root, manifest)
            store = FilesystemSoundPackStore(root / "packs")
            store.install_atomically(downloaded)
            target = (
                store.root
                / manifest.pack_id
                / "versions"
                / manifest.version
                / manifest.files["move"]
            )
            replacement = target.with_name("replacement.wav")
            replacement.write_bytes(payloads[manifest.files["move"]])
            real_open = os.open
            swapped = False

            def swap_before_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal swapped
                if Path(path) == target and not swapped:
                    swapped = True
                    os.replace(replacement, target)
                if dir_fd is None:
                    return real_open(path, flags, mode)
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch(
                "acs.sound_pack_store.os.open",
                side_effect=swap_before_open,
            ):
                inventory = store.installed()

            self.assertTrue(swapped)
            self.assertNotIn(manifest.pack_id, inventory)

    def test_verified_asset_snapshot_returns_digest_bound_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, payloads = _staged_download(root, manifest)
            store = FilesystemSoundPackStore(root / "packs")
            store.install_atomically(downloaded)

            snapshot = store.read_asset_snapshot(manifest.pack_id, "move")

            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(manifest.version, snapshot.version)
            self.assertEqual(manifest.files["move"], snapshot.relative_path)
            self.assertEqual(payloads[manifest.files["move"]], snapshot.content)

    def test_asset_replacement_after_manifest_verification_never_escapes_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest, seed=b"a")
            store = FilesystemSoundPackStore(root / "packs")
            store.install_atomically(downloaded)
            installed = store._installed_disk_pack(manifest.pack_id)
            target = installed.version_dir / manifest.files["move"]
            real_installed = store._installed_disk_pack

            def verify_then_replace(pack_id):
                result = real_installed(pack_id)
                target.write_bytes(b"RIFF" + (4).to_bytes(4, "little") + b"WAVE")
                return result

            with mock.patch.object(
                store,
                "_installed_disk_pack",
                side_effect=verify_then_replace,
            ):
                snapshot = store.read_asset_snapshot(manifest.pack_id, "move")

            self.assertIsNone(
                snapshot,
                "bytes changed after verification must never cross the playback boundary",
            )

    def test_absent_pack_uninstall_serializes_with_concurrent_first_install(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store_root = root / "packs"
            installer_store = FilesystemSoundPackStore(store_root)
            remover_store = FilesystemSoundPackStore(store_root)
            manifest = _manifest(version="1.0.0")
            downloaded, _ = _staged_download(root, manifest, seed=b"a")

            install_entered = threading.Event()
            release_install = threading.Event()
            uninstall_started = threading.Event()
            uninstall_done = threading.Event()
            errors: list[BaseException] = []
            original_locked = FilesystemSoundPackStore._install_atomically_locked

            def blocking_install(self, candidate, digests, source):
                install_entered.set()
                if not release_install.wait(5):
                    raise AssertionError("timed out waiting to release first install")
                return original_locked(self, candidate, digests, source)

            def install_worker():
                try:
                    installer_store.install_atomically(downloaded)
                except BaseException as exc:
                    errors.append(exc)

            def uninstall_worker():
                uninstall_started.set()
                try:
                    remover_store.uninstall(manifest.pack_id)
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    uninstall_done.set()

            with mock.patch.object(
                FilesystemSoundPackStore,
                "_install_atomically_locked",
                autospec=True,
                side_effect=blocking_install,
            ):
                installer = threading.Thread(target=install_worker)
                installer.start()
                self.assertTrue(install_entered.wait(5))
                self.assertFalse(
                    os.path.lexists(store_root / manifest.pack_id),
                    "first install must still be pre-publication",
                )

                uninstaller = threading.Thread(target=uninstall_worker)
                uninstaller.start()
                self.assertTrue(uninstall_started.wait(5))
                self.assertFalse(
                    uninstall_done.wait(0.2),
                    "uninstall must wait for the first install even while pack path is absent",
                )

                release_install.set()
                installer.join(5)
                uninstaller.join(5)

            self.assertFalse(installer.is_alive())
            self.assertFalse(uninstaller.is_alive())
            self.assertEqual([], errors)
            self.assertNotIn(manifest.pack_id, remover_store.installed())

    def test_install_and_uninstall_are_serialized_across_store_instances(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store_root = root / "packs"
            first_store = FilesystemSoundPackStore(store_root)
            second_store = FilesystemSoundPackStore(store_root)
            first = _manifest(version="1.0.0")
            first_download, _ = _staged_download(root, first, seed=b"a")
            first_store.install_atomically(first_download)
            second = _manifest(version="2.0.0")
            second_download, _ = _staged_download(root, second, seed=b"b")

            publication_entered = threading.Event()
            release_publication = threading.Event()
            uninstall_started = threading.Event()
            uninstall_done = threading.Event()
            errors: list[BaseException] = []
            original_publish = FilesystemSoundPackStore._publish_active

            def blocking_publish(pack_dir, pack_id, version):
                if version == "2.0.0":
                    publication_entered.set()
                    if not release_publication.wait(5):
                        raise AssertionError("timed out waiting to release publication")
                return original_publish(pack_dir, pack_id, version)

            def install_worker():
                try:
                    first_store.install_atomically(second_download)
                except BaseException as exc:
                    errors.append(exc)

            def uninstall_worker():
                uninstall_started.set()
                try:
                    second_store.uninstall(second.pack_id)
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    uninstall_done.set()

            with mock.patch.object(
                FilesystemSoundPackStore,
                "_publish_active",
                side_effect=blocking_publish,
            ):
                installer = threading.Thread(target=install_worker)
                installer.start()
                self.assertTrue(publication_entered.wait(5))

                uninstaller = threading.Thread(target=uninstall_worker)
                uninstaller.start()
                self.assertTrue(uninstall_started.wait(5))
                self.assertFalse(
                    uninstall_done.wait(0.2),
                    "uninstall must not enter destructive mutation while update owns the store lock",
                )

                release_publication.set()
                installer.join(5)
                uninstaller.join(5)

            self.assertFalse(installer.is_alive())
            self.assertFalse(uninstaller.is_alive())
            self.assertEqual([], errors)
            self.assertNotIn(second.pack_id, second_store.installed())

    @unittest.skipIf(
        os.name == "nt",
        "ordinary Windows runners cannot reliably create symlinks",
    )
    def test_store_ancestor_redirect_after_lock_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            container = root / "container"
            store = FilesystemSoundPackStore(container / "packs")
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            outside = root / "outside"
            outside.mkdir()
            locked_container = root / "locked-container"
            real_lock = store._lock_descriptor
            redirected = False

            def redirect_after_lock(descriptor):
                nonlocal redirected
                real_lock(descriptor)
                container.rename(locked_container)
                container.symlink_to(outside, target_is_directory=True)
                redirected = True

            with mock.patch.object(
                store,
                "_lock_descriptor",
                side_effect=redirect_after_lock,
            ), self.assertRaisesRegex(
                SoundPackStoreError,
                "redirected",
            ):
                store.install_atomically(downloaded)

            self.assertTrue(redirected)
            self.assertEqual([], list(outside.iterdir()))

    def test_mutation_lock_swap_after_lstat_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            lock_path = store._mutation_lock_path
            lock_path.write_bytes(b"\0")
            replacement = root / "replacement.lock"
            replacement.write_bytes(b"\0")
            real_open = os.open
            swapped = False

            def swap_before_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal swapped
                if Path(path) == lock_path and not swapped:
                    swapped = True
                    os.replace(replacement, lock_path)
                if dir_fd is None:
                    return real_open(path, flags, mode)
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch(
                "acs.sound_pack_store.os.open",
                side_effect=swap_before_open,
            ), self.assertRaisesRegex(
                SoundPackStoreError,
                "lock changed before secure open",
            ):
                with store._exclusive_mutation():
                    self.fail("mutation lock identity swap must fail closed")

            self.assertTrue(swapped)

    @unittest.skipIf(
        os.name == "nt",
        "ordinary Windows runners cannot reliably create symlinks",
    )
    def test_uninstall_removes_dangling_pack_symlink_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            store.root.mkdir()
            pack_dir = store.root / "broken.pack"
            missing_target = root / "missing-target"
            pack_dir.symlink_to(missing_target, target_is_directory=True)

            self.assertTrue(os.path.lexists(pack_dir))
            self.assertFalse(pack_dir.exists())

            store.uninstall("broken.pack")

            self.assertFalse(os.path.lexists(pack_dir))
            self.assertFalse(missing_target.exists())

    @unittest.skipIf(
        __import__("os").name == "nt",
        "ordinary Windows test runners cannot create symlinks reliably",
    )
    def test_mutation_lock_symlink_is_rejected_without_pack_publication(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            outside = root / "outside.lock"
            outside.write_bytes(b"x")
            store._mutation_lock_path.symlink_to(outside)

            with self.assertRaisesRegex(
                SoundPackStoreError,
                "mutation lock.*regular",
            ):
                store.install_atomically(downloaded)

            self.assertFalse(store.root.exists())
            self.assertEqual(b"x", outside.read_bytes())

    def test_atomic_store_rejects_direct_version_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            newer = _manifest(version="2.0.0")
            newer_download, _ = _staged_download(root, newer, seed=b"n")
            store.install_atomically(newer_download)

            older = _manifest(version="1.9.9")
            older_download, _ = _staged_download(root, older, seed=b"o")
            with self.assertRaisesRegex(SoundPackStoreError, "roll back"):
                store.install_atomically(older_download)

            self.assertEqual("2.0.0", store.active_version(newer.pack_id))
            self.assertEqual(( "2.0.0",), store.versions(newer.pack_id))

    def test_atomic_store_semver_prerelease_cannot_replace_final_release(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            final = _manifest(version="2.0.0")
            final_download, _ = _staged_download(root, final, seed=b"f")
            store.install_atomically(final_download)

            prerelease = _manifest(version="2.0.0-rc.9")
            prerelease_download, _ = _staged_download(root, prerelease, seed=b"r")
            with self.assertRaisesRegex(SoundPackStoreError, "roll back"):
                store.install_atomically(prerelease_download)

            self.assertEqual("2.0.0", store.active_version(final.pack_id))

    def test_update_keeps_old_version_and_switches_active_only_after_new_publish(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            first = _manifest(version="1.0.0")
            first_download, _ = _staged_download(root, first, seed=b"a")
            store.install_atomically(first_download)

            second = _manifest(version="1.1.0")
            second_download, _ = _staged_download(root, second, seed=b"b")
            store.install_atomically(second_download)

            self.assertEqual(store.active_version(second.pack_id), "1.1.0")
            self.assertEqual(store.versions(second.pack_id), ("1.0.0", "1.1.0"))
            self.assertTrue(
                (
                    root
                    / "packs"
                    / second.pack_id
                    / "versions"
                    / "1.0.0"
                    / "manifest.json"
                ).is_file()
            )
            self.assertEqual(store.installed()[second.pack_id], second)

    def test_active_pointer_directory_is_flushed_and_read_back(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            store = FilesystemSoundPackStore(root / "packs")
            synced = []

            original_sync = __import__(
                "acs.sound_pack_store",
                fromlist=["_fsync_directory"],
            )._fsync_directory

            def record_sync(path):
                synced.append(Path(path))
                return original_sync(path)

            with mock.patch(
                "acs.sound_pack_store._fsync_directory",
                side_effect=record_sync,
            ):
                store.install_atomically(downloaded)

            versions_dir = root / "packs" / manifest.pack_id / "versions"
            pack_dir = versions_dir.parent
            self.assertIn(versions_dir, synced)
            self.assertIn(pack_dir, synced)
            version_sync_index = synced.index(versions_dir)
            active_parent_sync_index = max(
                index for index, path in enumerate(synced) if path == pack_dir
            )
            self.assertLess(version_sync_index, active_parent_sync_index)
            self.assertEqual("1.0.0", store.active_version(manifest.pack_id))

    def test_post_active_directory_sync_failure_is_an_uncertain_visible_commit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            first = _manifest(version="1.0.0")
            first_download, _ = _staged_download(root, first, seed=b"a")
            store.install_atomically(first_download)
            second = _manifest(version="1.1.0")
            second_download, _ = _staged_download(root, second, seed=b"b")
            pack_dir = root / "packs" / second.pack_id
            real_sync = __import__(
                "acs.sound_pack_store",
                fromlist=["_fsync_directory"],
            )._fsync_directory

            def fail_only_active_parent(path):
                candidate = Path(path)
                if candidate == pack_dir:
                    raise SoundPackStoreError("active pointer directory sync failed")
                return real_sync(candidate)

            with mock.patch(
                "acs.sound_pack_store._fsync_directory",
                side_effect=fail_only_active_parent,
            ), self.assertRaisesRegex(
                SoundPackStoreError,
                "active pointer directory sync failed",
            ):
                store.install_atomically(second_download)

            self.assertEqual(
                "1.1.0",
                store.active_version(second.pack_id),
                "post-replace failure is an uncertain commit and must be re-read",
            )
            self.assertEqual(second, store.installed()[second.pack_id])

    def test_failed_update_cannot_replace_previous_active_pack(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            first = _manifest(version="1.0.0")
            first_download, _ = _staged_download(root, first, seed=b"a")
            store.install_atomically(first_download)

            second = _manifest(version="1.1.0")
            second_download, _ = _staged_download(root, second, seed=b"b")
            stage = Path(second_download.payload_ref)
            (stage / second.files["move"]).write_bytes(b"tampered-after-digest")

            with self.assertRaisesRegex(SoundPackStoreError, "size mismatch|checksum"):
                store.install_atomically(second_download)

            self.assertEqual(store.active_version(first.pack_id), "1.0.0")
            self.assertEqual(store.installed()[first.pack_id], first)
            self.assertEqual(store.versions(first.pack_id), ("1.0.0",))

    def test_downloaded_metadata_rejects_duplicate_normalized_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            assets = dict(downloaded.assets)
            move_path = manifest.files["move"]
            assets[move_path.replace("/", chr(92))] = assets[move_path]
            ambiguous = DownloadedSoundPack(
                manifest=manifest,
                assets=assets,
                total_bytes=sum(item.size_bytes for item in assets.values()),
                payload_ref=downloaded.payload_ref,
            )
            store = FilesystemSoundPackStore(root / "packs")

            with self.assertRaisesRegex(ValueError, "duplicate normalized"):
                store.install_atomically(ambiguous)

            self.assertFalse(store.root.exists())

    def test_invalid_download_and_uninstall_id_do_not_materialize_mutation_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            stage = Path(downloaded.payload_ref)
            (stage / "undeclared.wav").write_bytes(_wav(b"z"))

            with self.assertRaisesRegex(SoundPackStoreError, "topology"):
                store.install_atomically(downloaded)

            self.assertFalse(store._mutation_lock_path.exists())
            self.assertFalse(store.root.exists())

            with self.assertRaises(ValueError):
                store.uninstall("../../escape")

            self.assertFalse(store._mutation_lock_path.exists())
            self.assertFalse(store.root.exists())

    def test_undeclared_staged_payload_is_rejected_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            stage = Path(downloaded.payload_ref)
            (stage / "payload.exe").write_bytes(b"MZ")
            store = FilesystemSoundPackStore(root / "packs")

            with self.assertRaisesRegex(SoundPackStoreError, "topology"):
                store.install_atomically(downloaded)

            self.assertFalse(store.root.exists())

    def test_extension_spoofed_executable_bytes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            stage = Path(downloaded.payload_ref)
            target = stage / manifest.files["move"]
            fake = b"MZ" + b"not-a-wave"
            target.write_bytes(fake)
            assets = dict(downloaded.assets)
            assets[manifest.files["move"]] = SoundAssetDigest(
                manifest.files["move"],
                len(fake),
                hashlib.sha256(fake).hexdigest(),
            )
            poisoned = DownloadedSoundPack(
                manifest=manifest,
                assets=assets,
                total_bytes=sum(item.size_bytes for item in assets.values()),
                payload_ref=stage,
            )
            store = FilesystemSoundPackStore(root / "packs")

            with self.assertRaisesRegex(SoundPackStoreError, "WAV.*signature"):
                store.install_atomically(poisoned)

            self.assertNotIn(manifest.pack_id, store.installed())

    def test_versions_follow_semver_prerelease_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            versions = (
                "1.0.0-beta.10",
                "1.0.0",
                "1.0.0-alpha",
                "1.0.0-beta.2",
                "1.0.0-beta.1",
                "1.0.0-alpha.1",
            )
            for index, version in enumerate(versions):
                manifest = _manifest(version=version)
                downloaded, _ = _staged_download(
                    root,
                    manifest,
                    seed=bytes((97 + index,)),
                )
                store.install_atomically(downloaded)

            self.assertEqual(
                (
                    "1.0.0-alpha",
                    "1.0.0-alpha.1",
                    "1.0.0-beta.1",
                    "1.0.0-beta.2",
                    "1.0.0-beta.10",
                    "1.0.0",
                ),
                store.versions("soft.wood"),
            )

    def test_same_version_with_different_content_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = FilesystemSoundPackStore(root / "packs")
            manifest = _manifest()
            first, _ = _staged_download(root, manifest, seed=b"a")
            store.install_atomically(first)
            second, _ = _staged_download(root, manifest, seed=b"b")

            with self.assertRaisesRegex(SoundPackStoreError, "different content"):
                store.install_atomically(second)

            self.assertEqual(store.active_version(manifest.pack_id), "1.0.0")

    def test_tampered_installed_asset_is_not_reported_usable_and_can_be_removed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            store = FilesystemSoundPackStore(root / "packs")
            store.install_atomically(downloaded)

            asset = store.resolve_asset(manifest.pack_id, "capture")
            self.assertIsNotNone(asset)
            assert asset is not None
            asset.write_bytes(b"tampered")

            self.assertNotIn(manifest.pack_id, store.installed())
            self.assertIsNone(store.active_version(manifest.pack_id))
            self.assertIsNone(store.resolve_asset(manifest.pack_id, "move"))

            store.uninstall(manifest.pack_id)
            self.assertFalse((root / "packs" / manifest.pack_id).exists())

    def test_duplicate_key_or_corrupt_active_pointer_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            store = FilesystemSoundPackStore(root / "packs")
            store.install_atomically(downloaded)

            pointer = root / "packs" / manifest.pack_id / "active.json"
            pointer.write_text(
                '{"schema_version":1,"schema_version":1,'
                '"pack_id":"soft.wood","version":"1.0.0"}\n',
                encoding="utf-8",
            )

            self.assertNotIn(manifest.pack_id, store.installed())
            self.assertIsNone(store.active_version(manifest.pack_id))

    def test_builtin_pack_ids_cannot_collide_after_canonicalization(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            classic = _manifest(pack_id="classic", title="Classic")
            with self.assertRaisesRegex(ValueError, "duplicate built-in"):
                FilesystemSoundPackStore(
                    Path(raw) / "packs",
                    built_in={"classic": classic, " Classic ": classic},
                )

    def test_builtin_pack_is_visible_but_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            classic = _manifest(pack_id="classic", title="Classic")
            store = FilesystemSoundPackStore(
                root / "packs",
                built_in={"classic": classic},
            )

            self.assertEqual(store.installed()["classic"], classic)
            self.assertEqual(store.active_version("classic"), "1.0.0")
            with self.assertRaisesRegex(SoundPackStoreError, "immutable"):
                store.uninstall("classic")

            downloaded, _ = _staged_download(root, classic)
            with self.assertRaisesRegex(SoundPackStoreError, "immutable"):
                store.install_atomically(downloaded)

    def test_local_size_limit_is_independent_of_catalog_or_downloader(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = _manifest()
            downloaded, _ = _staged_download(root, manifest)
            store = FilesystemSoundPackStore(
                root / "packs",
                max_bytes=downloaded.total_bytes - 1,
            )

            with self.assertRaisesRegex(SoundPackStoreError, "size limit"):
                store.install_atomically(downloaded)
            self.assertFalse(store.root.exists())


if __name__ == "__main__":
    unittest.main()
