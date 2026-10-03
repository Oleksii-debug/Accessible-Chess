from __future__ import annotations

import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import wave

from acs.sound_pack_catalog import DownloadedSoundPack, SoundAssetDigest
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


class FilesystemSoundPackStoreTests(unittest.TestCase):
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
            self.assertEqual(("sync", versions_dir), order[0])
            self.assertEqual(("active", versions_dir.parent), order[1])

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
            self.assertLess(synced.index(versions_dir), synced.index(pack_dir))
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
