from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import wave

from acs.sound_pack_store import FilesystemSoundPackStore
from acs.sound_profile_composition import create_local_sound_composition
from acs.sound_profile_windows import ProfiledWindowsSoundPlaybackAdapter
from acs.sound_profiles import CORE_SOUND_EVENTS, SoundPackManifest
from acs.sound_runtime import SoundAssetRequest


class _Playback:
    def __init__(self) -> None:
        self.requests: list[SoundAssetRequest] = []

    def play_sound(self, request: SoundAssetRequest) -> None:
        self.requests.append(request)


def _manifest(pack_id: str, *, incompatible_event: str | None = None) -> SoundPackManifest:
    files = {event: f"audio/{event}.wav" for event in CORE_SOUND_EVENTS}
    if incompatible_event is not None:
        files[incompatible_event] = f"audio/{incompatible_event}.ogg"
    return SoundPackManifest(
        pack_id=pack_id,
        version="1.0.0",
        title="Test pack",
        license_id="CC0-1.0",
        files=files,
        author="Accessible Chess",
        provenance="https://example.invalid/test-pack",
    )


def _write_profile(path: Path, pack_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pack_id": pack_id,
                "master_enabled": True,
                "master_volume_percent": 80,
                "events": {},
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = (1000, -1000, 500, -500)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(8000)
        writer.writeframes(struct.pack("<" + "h" * len(samples), *samples))


def _cache_adapter(cache_dir: Path, logger) -> ProfiledWindowsSoundPlaybackAdapter:
    adapter = object.__new__(ProfiledWindowsSoundPlaybackAdapter)
    adapter._cache_dir = cache_dir
    adapter._logger = logger
    return adapter


class WindowsSoundPackCompatibilityTests(unittest.TestCase):
    def test_selected_pack_with_any_non_wav_asset_recovers_to_classic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-windows-pack-fallback-") as raw:
            root = Path(raw)
            data = root / "data"
            profile_path = data / "sound-profile.json"
            _write_profile(profile_path, "soft.pack")
            mixed_pack = _manifest("soft.pack", incompatible_event="move")

            with mock.patch.object(
                FilesystemSoundPackStore,
                "installed",
                return_value={"soft.pack": mixed_pack},
            ):
                composition = create_local_sound_composition(
                    application_dir=root / "app",
                    data_root=data,
                    asset_playback=_Playback(),
                )

            self.assertEqual("classic", composition.profile_manager.current.pack_id)
            persisted = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual("classic", persisted["pack_id"])

    def test_selected_all_wav_pack_remains_selected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-windows-pack-wav-") as raw:
            root = Path(raw)
            data = root / "data"
            profile_path = data / "sound-profile.json"
            _write_profile(profile_path, "soft.pack")
            wav_pack = _manifest("soft.pack")

            with mock.patch.object(
                FilesystemSoundPackStore,
                "installed",
                return_value={"soft.pack": wav_pack},
            ):
                composition = create_local_sound_composition(
                    application_dir=root / "app",
                    data_root=data,
                    asset_playback=_Playback(),
                )

            self.assertEqual("soft.pack", composition.profile_manager.current.pack_id)
            persisted = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual("soft.pack", persisted["pack_id"])


class SoundCachePathSafetyTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "ordinary Windows runners cannot reliably create symlinks")
    def test_cache_directory_symlink_is_rejected_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-cache-symlink-") as raw:
            root = Path(raw)
            outside = root / "outside"
            outside.mkdir()
            sentinel = outside / "custom-redaction-v50.wav"
            sentinel.write_bytes(b"keep")
            cache = root / "cache"
            cache.symlink_to(outside, target_is_directory=True)
            source = root / "source.wav"
            _write_wav(source)
            adapter = _cache_adapter(cache, mock.Mock())

            with self.assertRaisesRegex(ValueError, "real directory"):
                adapter._scaled_copy(source, "custom-redaction", 50)

            self.assertEqual(b"keep", sentinel.read_bytes())
            self.assertEqual([sentinel], list(outside.iterdir()))


    @unittest.skipIf(os.name == "nt", "ordinary Windows runners cannot reliably create symlinks")
    def test_cache_symlinked_ancestor_is_rejected_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-cache-ancestor-symlink-") as raw:
            root = Path(raw)
            outside = root / "outside"
            outside.mkdir()
            redirected = root / "redirected"
            redirected.symlink_to(outside, target_is_directory=True)
            cache = redirected / "nested" / "cache"
            source = root / "source.wav"
            _write_wav(source)
            adapter = _cache_adapter(cache, mock.Mock())

            with self.assertRaisesRegex(ValueError, "real directory"):
                adapter._scaled_copy(source, "custom-redaction", 50)

            self.assertFalse((outside / "nested").exists())
            self.assertEqual([], list(outside.iterdir()))


class SoundCachePlaybackLockTests(unittest.TestCase):
    def test_adapters_for_same_cache_share_in_process_lock(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-cache-shared-lock-") as raw:
            cache = Path(raw) / "cache"
            first = _cache_adapter(cache, mock.Mock())
            second = _cache_adapter(cache, mock.Mock())
            first._play_lock = __import__(
                "acs.sound_profile_windows",
                fromlist=["_cache_process_lock"],
            )._cache_process_lock(cache)
            second._play_lock = __import__(
                "acs.sound_profile_windows",
                fromlist=["_cache_process_lock"],
            )._cache_process_lock(cache)
            self.assertIs(first._play_lock, second._play_lock)

    def test_cache_lock_swap_after_lstat_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-cache-lock-swap-") as raw:
            root = Path(raw)
            cache = root / "cache"
            cache.mkdir()
            lock_path = cache / ".playback.lock"
            lock_path.write_bytes(b"\0")
            replacement = root / "replacement.lock"
            replacement.write_bytes(b"\0")
            adapter = _cache_adapter(cache, mock.Mock())
            adapter._play_lock = __import__(
                "acs.sound_profile_windows",
                fromlist=["_cache_process_lock"],
            )._cache_process_lock(cache)
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
                "acs.sound_profile_windows.os.open",
                side_effect=swap_before_open,
            ), self.assertRaisesRegex(
                RuntimeError,
                "lock changed before secure open",
            ):
                with adapter._exclusive_playback():
                    self.fail("cache lock identity swap must fail closed")

            self.assertTrue(swapped)

    @unittest.skipIf(os.name == "nt", "ordinary Windows runners cannot reliably create symlinks")
    def test_cache_lock_symlink_is_rejected_without_following(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-cache-lock-symlink-") as raw:
            root = Path(raw)
            cache = root / "cache"
            cache.mkdir()
            outside = root / "outside.lock"
            outside.write_bytes(b"sentinel")
            (cache / ".playback.lock").symlink_to(outside)
            adapter = _cache_adapter(cache, mock.Mock())
            adapter._play_lock = __import__(
                "acs.sound_profile_windows",
                fromlist=["_cache_process_lock"],
            )._cache_process_lock(cache)

            with self.assertRaisesRegex(RuntimeError, "not a regular file"):
                with adapter._exclusive_playback():
                    self.fail("redirected lock must never be acquired")

            self.assertEqual(b"sentinel", outside.read_bytes())


class SoundCacheWarningRedactionTests(unittest.TestCase):
    def test_temporary_cleanup_warning_does_not_expose_private_path_or_exception(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-cache-warning-") as raw:
            root = Path(raw)
            source = root / "source.wav"
            _write_wav(source)
            logger = mock.Mock()
            adapter = _cache_adapter(root / "cache", logger)
            private = r"C:\Users\private\AppData\AccessibleChess\sound-cache\secret.wav"

            with mock.patch(
                "acs.sound_profile_windows.os.replace",
                side_effect=OSError("publish failed"),
            ), mock.patch.object(
                Path,
                "unlink",
                side_effect=OSError(private),
            ), self.assertRaisesRegex(OSError, "publish failed"):
                adapter._scaled_copy(source, "custom-redaction", 50)

            logger.warning.assert_called_once()
            rendered = repr(logger.warning.call_args)
            self.assertIn("OSError", rendered)
            self.assertNotIn("C:\\Users\\private", rendered)
            self.assertNotIn("secret.wav", rendered)
            self.assertNotIn("exc_info", rendered)

    def test_prune_warning_does_not_expose_candidate_path_or_exception(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-cache-prune-warning-") as raw:
            cache = Path(raw) / "private-user" / "cache"
            cache.mkdir(parents=True)
            legacy = cache / "custom-redaction-v50.wav"
            legacy.write_bytes(b"stale")
            logger = mock.Mock()
            adapter = _cache_adapter(cache, logger)
            destination = cache / "custom-redaction-v50-s1-current.wav"
            private = r"C:\Users\private\AppData\AccessibleChess\sound-cache\stale.wav"

            with mock.patch.object(
                Path,
                "unlink",
                side_effect=OSError(private),
            ):
                adapter._prune_scaled_variants(destination, "custom-redaction", 50)

            logger.warning.assert_called_once()
            rendered = repr(logger.warning.call_args)
            self.assertIn("OSError", rendered)
            self.assertNotIn("C:\\Users\\private", rendered)
            self.assertNotIn("private-user", rendered)
            self.assertNotIn("stale.wav", rendered)
            self.assertNotIn("exc_info", rendered)


if __name__ == "__main__":
    unittest.main()
