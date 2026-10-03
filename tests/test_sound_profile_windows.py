from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import wave

from acs.sound_events import SoundEvent
from acs.sound_pack_store import FilesystemSoundPackStore, SoundPackAssetSnapshot
from acs.sound_profile_windows import ProfiledWindowsSoundPlaybackAdapter
from acs.sound_runtime import SoundAssetRequest
from acs.sound_windows import PackagedSoundAssetResolver


def _write_wav(path: Path, samples: tuple[int, ...] = (1000, -1000, 500, -500)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(8000)
        writer.writeframes(struct.pack("<" + "h" * len(samples), *samples))


def _write_pcm_wav(
    path: Path,
    sample_width: int,
    samples: tuple[int, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if sample_width == 1:
        frames = bytes(samples)
    else:
        frames = b"".join(
            int(sample).to_bytes(sample_width, "little", signed=True)
            for sample in samples
        )
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(sample_width)
        writer.setframerate(8000)
        writer.writeframes(frames)


def _read_pcm_samples(path: Path) -> tuple[int, tuple[int, ...]]:
    with wave.open(str(path), "rb") as reader:
        sample_width = reader.getsampwidth()
        frames = reader.readframes(reader.getnframes())
    if sample_width == 1:
        samples = tuple(frames)
    else:
        samples = tuple(
            int.from_bytes(
                frames[offset : offset + sample_width],
                "little",
                signed=True,
            )
            for offset in range(0, len(frames), sample_width)
        )
    return sample_width, samples


def _asset_snapshot(
    source: Path,
    *,
    pack_id: str = "soft.pack",
    sound_id: str = "soft.move",
    version: str = "1.0.0",
) -> SoundPackAssetSnapshot:
    return SoundPackAssetSnapshot(
        pack_id=pack_id,
        version=version,
        sound_id=sound_id,
        relative_path=f"audio/{sound_id}.wav",
        content=source.read_bytes(),
    )


def _packaged_root(root: Path) -> PackagedSoundAssetResolver:
    sound_root = root / "assets" / "sounds"
    files = {}
    for event in SoundEvent:
        name = f"{event.value}.wav"
        _write_wav(sound_root / name)
        files[event.value] = name
    (sound_root / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "files": files}), encoding="utf-8"
    )
    return PackagedSoundAssetResolver(root)


class _WinSound:
    SND_FILENAME = 1
    SND_NODEFAULT = 2

    def __init__(self) -> None:
        self.calls = []

    def PlaySound(self, path, flags) -> None:
        self.calls.append((str(path), flags))


class ProfiledWindowsSoundPlaybackAdapterTests(unittest.TestCase):
    def _adapter(self, root: Path):
        resolver = _packaged_root(root / "app")
        store = FilesystemSoundPackStore(root / "packs")
        adapter = ProfiledWindowsSoundPlaybackAdapter(
            resolver,
            store,
            cache_dir=root / "cache",
        )
        return resolver, store, adapter

    def _play(self, adapter, request):
        fake = _WinSound()
        with mock.patch.object(sys, "platform", "win32"), mock.patch.dict(
            sys.modules, {"winsound": fake}
        ):
            adapter.play_sound(request)
        return fake

    def test_classic_event_plays_from_content_addressed_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profiled-win-classic-") as raw:
            root = Path(raw)
            resolver, _store, adapter = self._adapter(root)
            source = resolver.resolve(SoundEvent.MOVE)
            fake = self._play(
                adapter,
                SoundAssetRequest(
                    pack_id="classic",
                    event_id="move",
                    sound_id="move",
                    volume=100,
                    preview=False,
                ),
            )
            played = Path(fake.calls[0][0])
            self.assertNotEqual(source, played)
            self.assertEqual(root / "cache", played.parent)
            self.assertTrue(played.is_file())
            self.assertIn("classic-move-v100-s1-", played.name)
            self.assertEqual(
                _WinSound.SND_FILENAME | _WinSound.SND_NODEFAULT, fake.calls[0][1]
            )

    def test_classic_low_time_preview_uses_tick_snapshot_without_adding_runtime_event(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profiled-win-low-time-") as raw:
            root = Path(raw)
            resolver, _store, adapter = self._adapter(root)
            source = resolver.resolve(SoundEvent.TICK)
            fake = self._play(
                adapter,
                SoundAssetRequest(
                    pack_id="classic",
                    event_id="low_time",
                    sound_id="low_time",
                    volume=100,
                    preview=True,
                ),
            )
            played = Path(fake.calls[0][0])
            self.assertNotEqual(source, played)
            self.assertEqual(root / "cache", played.parent)
            self.assertIn("classic-tick-v100-s1-", played.name)
            self.assertNotIn("low_time", {event.value for event in SoundEvent})

    def test_classic_source_swap_after_lstat_fails_before_cache_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profiled-win-classic-swap-") as raw:
            root = Path(raw)
            resolver, _store, adapter = self._adapter(root)
            source = resolver.resolve(SoundEvent.MOVE)
            replacement = source.with_name("replacement.wav")
            replacement.write_bytes(source.read_bytes())
            real_open = os.open
            swapped = False

            def swap_before_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal swapped
                if Path(path) == source and not swapped:
                    swapped = True
                    os.replace(replacement, source)
                if dir_fd is None:
                    return real_open(path, flags, mode)
                return real_open(path, flags, mode, dir_fd=dir_fd)

            request = SoundAssetRequest(
                pack_id="classic",
                event_id="move",
                sound_id="move",
                volume=100,
                preview=False,
            )
            with mock.patch(
                "acs.sound_profile_windows.os.open",
                side_effect=swap_before_open,
            ), mock.patch.object(
                sys, "platform", "win32"
            ), self.assertRaisesRegex(
                ValueError,
                "changed before secure read",
            ):
                adapter.play_sound(request)

            self.assertTrue(swapped)
            self.assertEqual([], list((root / "cache").glob("classic-move-v100-*.wav")))

    def test_classic_low_time_dispatch_is_rejected_until_distinct_asset_exists(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profiled-win-low-time-dispatch-") as raw:
            _resolver, _store, adapter = self._adapter(Path(raw))
            request = SoundAssetRequest(
                pack_id="classic",
                event_id="low_time",
                sound_id="low_time",
                volume=100,
                preview=False,
            )
            with mock.patch.object(sys, "platform", "win32"), self.assertRaisesRegex(
                ValueError, "preview-only"
            ):
                adapter.play_sound(request)

    def test_classic_cannot_select_arbitrary_sound_id(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profiled-win-classic-id-") as raw:
            _resolver, _store, adapter = self._adapter(Path(raw))
            request = SoundAssetRequest(
                pack_id="classic",
                event_id="move",
                sound_id="capture",
                volume=100,
                preview=True,
            )
            with mock.patch.object(sys, "platform", "win32"), self.assertRaisesRegex(
                ValueError, "sound_id"
            ):
                adapter.play_sound(request)

    def test_custom_pack_uses_only_store_resolved_asset(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profiled-win-custom-") as raw:
            root = Path(raw)
            _resolver, store, adapter = self._adapter(root)
            custom = root / "verified-custom.wav"
            _write_wav(custom)
            request = SoundAssetRequest(
                pack_id="soft.pack",
                event_id="move",
                sound_id="soft.move",
                volume=100,
                preview=False,
            )
            with mock.patch.object(store, "read_asset_snapshot", return_value=_asset_snapshot(custom)) as resolve:
                fake = self._play(adapter, request)
            resolve.assert_called_once_with("soft.pack", "soft.move")
            played = Path(fake.calls[0][0])
            self.assertNotEqual(custom, played)
            self.assertEqual(root / "cache", played.parent)

    def test_custom_full_volume_plays_from_content_addressed_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profiled-win-custom-snapshot-") as raw:
            root = Path(raw)
            _resolver, store, adapter = self._adapter(root)
            custom = root / "verified-custom.wav"
            _write_wav(custom)
            request = SoundAssetRequest(
                pack_id="soft.pack",
                event_id="move",
                sound_id="soft.move",
                volume=100,
                preview=False,
            )

            with mock.patch.object(store, "read_asset_snapshot", return_value=_asset_snapshot(custom)):
                fake = self._play(adapter, request)

            played = Path(fake.calls[0][0])
            self.assertNotEqual(custom, played)
            self.assertEqual(root / "cache", played.parent)
            self.assertTrue(played.is_file())
            custom.unlink()
            self.assertTrue(
                played.is_file(),
                "playback snapshot must survive installed-pack removal",
            )

    def test_custom_full_volume_rejects_structurally_invalid_wav_before_winsound(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profiled-win-custom-invalid-wav-") as raw:
            root = Path(raw)
            _resolver, store, adapter = self._adapter(root)
            custom = root / "invalid.wav"
            custom.write_bytes(b"RIFF" + (4).to_bytes(4, "little") + b"WAVE")
            request = SoundAssetRequest(
                pack_id="soft.pack",
                event_id="move",
                sound_id="soft.move",
                volume=100,
                preview=False,
            )
            fake = _WinSound()
            with mock.patch.object(store, "read_asset_snapshot", return_value=_asset_snapshot(custom)), mock.patch.object(
                sys, "platform", "win32"
            ), mock.patch.dict(sys.modules, {"winsound": fake}), self.assertRaises(
                (EOFError, wave.Error)
            ):
                adapter.play_sound(request)

            self.assertEqual([], fake.calls)

    def test_missing_custom_asset_fails_without_system_default(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profiled-win-missing-") as raw:
            _resolver, store, adapter = self._adapter(Path(raw))
            request = SoundAssetRequest(
                pack_id="missing.pack",
                event_id="move",
                sound_id="move",
                volume=100,
                preview=False,
            )
            with mock.patch.object(store, "read_asset_snapshot", return_value=None), mock.patch.object(
                sys, "platform", "win32"
            ), self.assertRaises(FileNotFoundError):
                adapter.play_sound(request)

    def test_adapter_log_does_not_expose_private_asset_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profiled-win-log-redaction-") as raw:
            root = Path(raw)
            resolver = _packaged_root(root / "app")
            store = FilesystemSoundPackStore(root / "packs")
            logger = mock.Mock()
            adapter = ProfiledWindowsSoundPlaybackAdapter(
                resolver,
                store,
                cache_dir=root / "cache",
                logger=logger,
            )
            request = SoundAssetRequest(
                pack_id="soft.pack",
                event_id="move",
                sound_id="soft.move",
                volume=100,
                preview=False,
            )

            with mock.patch.object(
                store,
                "read_asset_snapshot",
                side_effect=FileNotFoundError(
                    "C:/Users/private/AppData/AccessibleChess/soft.move.wav"
                ),
            ), mock.patch.object(sys, "platform", "win32"), self.assertRaises(
                FileNotFoundError
            ):
                adapter.play_sound(request)

            logger.error.assert_called_once()
            rendered = repr(logger.error.call_args)
            self.assertIn("FileNotFoundError", rendered)
            self.assertNotIn("C:/Users/private", rendered)

    def test_partial_volume_creates_deterministic_scaled_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profiled-win-volume-") as raw:
            root = Path(raw)
            _resolver, _store, adapter = self._adapter(root)
            request = SoundAssetRequest(
                pack_id="classic",
                event_id="check",
                sound_id="check",
                volume=25,
                preview=True,
            )
            first = self._play(adapter, request)
            second = self._play(adapter, request)
            self.assertEqual(first.calls[0][0], second.calls[0][0])
            self.assertTrue(Path(first.calls[0][0]).is_file())
            self.assertIn("classic-check-v25-s1-", first.calls[0][0])

    def test_partial_volume_supports_common_pcm_sample_widths(self) -> None:
        cases = (
            (1, (128, 255, 0), (128, 191, 64)),
            (2, (1000, -1000, 500), (500, -500, 250)),
            (3, (1_000_000, -1_000_000, 123_456), (500_000, -500_000, 61_728)),
            (4, (100_000_000, -100_000_000, 1_234_568), (50_000_000, -50_000_000, 617_284)),
        )
        with tempfile.TemporaryDirectory(prefix="profiled-win-pcm-widths-") as raw:
            root = Path(raw)
            _resolver, store, adapter = self._adapter(root)
            request = SoundAssetRequest(
                pack_id="soft.pack",
                event_id="move",
                sound_id="soft.move",
                volume=50,
                preview=True,
            )

            for sample_width, samples, expected in cases:
                with self.subTest(sample_width=sample_width):
                    source = root / f"custom-{sample_width}.wav"
                    _write_pcm_wav(source, sample_width, samples)
                    with mock.patch.object(store, "read_asset_snapshot", return_value=_asset_snapshot(source)):
                        fake = self._play(adapter, request)
                    played = Path(fake.calls[0][0])
                    actual_width, actual_samples = _read_pcm_samples(played)
                    self.assertEqual(sample_width, actual_width)
                    self.assertEqual(expected, actual_samples)

    def test_scaled_cache_identity_follows_source_bytes_not_mtime(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profiled-win-cache-bytes-") as raw:
            root = Path(raw)
            _resolver, store, adapter = self._adapter(root)
            source = root / "custom.wav"
            _write_wav(source, (1000, -1000, 500, -500))
            request = SoundAssetRequest(
                pack_id="soft.pack",
                event_id="move",
                sound_id="soft.move",
                volume=50,
                preview=True,
            )
            original_mtime = source.stat().st_mtime_ns

            with mock.patch.object(
                store,
                "read_asset_snapshot",
                side_effect=lambda _pack, _sound: _asset_snapshot(source),
            ):
                first = self._play(adapter, request)
                first_cache = Path(first.calls[0][0])

                _write_wav(source, (2000, -2000, 750, -750))
                os.utime(source, ns=(original_mtime, original_mtime))
                second = self._play(adapter, request)

            second_cache = Path(second.calls[0][0])
            self.assertNotEqual(first_cache, second_cache)
            self.assertFalse(first_cache.exists())
            self.assertTrue(second_cache.is_file())

    def test_scaled_cache_repairs_corrupted_content_addressed_entry(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profiled-win-cache-repair-") as raw:
            root = Path(raw)
            _resolver, store, adapter = self._adapter(root)
            source = root / "custom.wav"
            _write_wav(source)
            request = SoundAssetRequest(
                pack_id="soft.pack",
                event_id="check",
                sound_id="soft.check",
                volume=40,
                preview=True,
            )

            with mock.patch.object(store, "read_asset_snapshot", return_value=_asset_snapshot(source)):
                first = self._play(adapter, request)
                cache_path = Path(first.calls[0][0])
                expected = cache_path.read_bytes()
                cache_path.write_bytes(expected[:-4])
                second = self._play(adapter, request)

            self.assertEqual(Path(second.calls[0][0]), cache_path)
            self.assertEqual(cache_path.read_bytes(), expected)

    def test_scaled_cache_publish_is_atomic_and_cleans_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profiled-win-cache-atomic-") as raw:
            root = Path(raw)
            _resolver, store, adapter = self._adapter(root)
            source = root / "custom.wav"
            _write_wav(source)
            request = SoundAssetRequest(
                pack_id="soft.pack",
                event_id="capture",
                sound_id="soft.capture",
                volume=50,
                preview=True,
            )

            with mock.patch.object(store, "read_asset_snapshot", return_value=_asset_snapshot(source)), mock.patch(
                "acs.sound_profile_windows.os.replace",
                side_effect=OSError("publish failed"),
            ), mock.patch.object(sys, "platform", "win32"), self.assertRaisesRegex(
                OSError, "publish failed"
            ):
                adapter.play_sound(request)

            cache = root / "cache"
            self.assertEqual(list(cache.glob("*.tmp")), [])
            self.assertEqual(list(cache.glob("custom-*-v50-*.wav")), [])

    def test_non_windows_fails_before_resolving_or_playing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="profiled-win-platform-") as raw:
            _resolver, _store, adapter = self._adapter(Path(raw))
            with mock.patch.object(sys, "platform", "linux"), self.assertRaisesRegex(
                RuntimeError, "requires win32"
            ):
                adapter.play_sound(
                    SoundAssetRequest(
                        pack_id="classic",
                        event_id="move",
                        sound_id="move",
                        volume=100,
                        preview=False,
                    )
                )


if __name__ == "__main__":
    unittest.main()
