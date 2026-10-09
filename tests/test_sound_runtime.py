import json
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from acs.sound_events import MoveSoundFacts, SoundEvent
from acs.sound_runtime import GameSoundRuntime, SoundRuntime, SoundRuntimeSettings
from acs.sound_windows import (
    PackagedSoundAssetResolver,
    REQUIRED_SOUND_EVENTS,
    WindowsSoundPlaybackAdapter,
)


class FakePlayback:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def play(self, event, *, volume):
        self.calls.append((event, volume))
        if event == self.fail_on:
            raise FileNotFoundError(f"missing {event.value}")


class SoundRuntimeTests(unittest.TestCase):
    def test_required_move_sequences_are_deterministic(self):
        cases = [
            (MoveSoundFacts(), [SoundEvent.MOVE]),
            (MoveSoundFacts(capture=True), [SoundEvent.CAPTURE]),
            (MoveSoundFacts(check=True), [SoundEvent.MOVE, SoundEvent.CHECK]),
            (MoveSoundFacts(castle=True), [SoundEvent.CASTLE]),
            (MoveSoundFacts(promotion=True), [SoundEvent.PROMOTION]),
        ]
        for facts, expected in cases:
            fake = FakePlayback()
            game = GameSoundRuntime(SoundRuntime(fake))
            game.move(facts)
            self.assertEqual([event for event, _ in fake.calls], expected)

    def test_illegal_start_end_and_tick_are_consumable(self):
        fake = FakePlayback()
        game = GameSoundRuntime(SoundRuntime(fake))
        game.start()
        game.illegal()
        game.tick()
        game.low_time()
        game.end()
        self.assertEqual(
            [event for event, _ in fake.calls],
            [
                SoundEvent.START,
                SoundEvent.ILLEGAL,
                SoundEvent.TICK,
                SoundEvent.LOW_TIME,
                SoundEvent.END,
            ],
        )

    def test_specific_terminal_outcomes_do_not_fall_through_to_generic_end(self):
        mate_playback = FakePlayback()
        mate_game = GameSoundRuntime(SoundRuntime(mate_playback))
        mate_game.start()
        mate_game.checkmate()
        mate_game.end()
        self.assertEqual(
            [event for event, _ in mate_playback.calls],
            [SoundEvent.START, SoundEvent.MATE],
        )

        draw_playback = FakePlayback()
        draw_game = GameSoundRuntime(SoundRuntime(draw_playback))
        draw_game.start()
        draw_game.draw()
        draw_game.end()
        self.assertEqual(
            [event for event, _ in draw_playback.calls],
            [SoundEvent.START, SoundEvent.DRAW],
        )

    def test_terminal_move_does_not_duplicate_game_end(self):
        fake = FakePlayback()
        game = GameSoundRuntime(SoundRuntime(fake))
        game.start()
        game.move(MoveSoundFacts(capture=True, check=True, game_ended=True))
        game.end()
        self.assertEqual(
            [event for event, _ in fake.calls],
            [SoundEvent.START, SoundEvent.CAPTURE, SoundEvent.CHECK, SoundEvent.END],
        )

    def test_takeback_rearms_game_end_without_replaying_start(self):
        fake = FakePlayback()
        game = GameSoundRuntime(SoundRuntime(fake))
        game.start()
        game.end()

        report = game.resume_after_takeback()
        game.end()

        self.assertEqual(report.requested, ())
        self.assertEqual(
            [event for event, _ in fake.calls],
            [SoundEvent.START, SoundEvent.END, SoundEvent.END],
        )

    def test_duplicate_event_ids_collapse_within_one_batch(self):
        fake = FakePlayback()
        runtime = SoundRuntime(fake)
        report = runtime.dispatch([SoundEvent.CHECK, SoundEvent.CHECK, SoundEvent.END])
        self.assertEqual(report.requested, (SoundEvent.CHECK, SoundEvent.END))
        self.assertEqual(len(fake.calls), 2)

    def test_master_disable_and_zero_volume_never_touch_adapter(self):
        for settings in (
            SoundRuntimeSettings(enabled=False, volume=80),
            SoundRuntimeSettings(enabled=True, volume=0),
        ):
            fake = FakePlayback()
            report = SoundRuntime(fake, settings=settings).dispatch([SoundEvent.MOVE])
            self.assertTrue(report.disabled)
            self.assertEqual(fake.calls, [])

    def test_volume_is_forwarded_to_adapter(self):
        fake = FakePlayback()
        SoundRuntime(fake, settings=SoundRuntimeSettings(volume=37)).dispatch([SoundEvent.MOVE])
        self.assertEqual(fake.calls, [(SoundEvent.MOVE, 37)])

    def test_adapter_failure_is_explicit_and_later_events_continue(self):
        failures = []
        fake = FakePlayback(fail_on=SoundEvent.CAPTURE)
        report = SoundRuntime(fake, error_sink=failures.append).dispatch(
            [SoundEvent.CAPTURE, SoundEvent.CHECK]
        )
        self.assertEqual(report.delivered, (SoundEvent.CHECK,))
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(report.failures[0].event, SoundEvent.CAPTURE)
        self.assertEqual(failures, list(report.failures))


class PackagedSoundResolverTests(unittest.TestCase):
    @staticmethod
    def _write_silent_wav(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(8000)
            writer.writeframes(b"\x00\x00" * 8)

    def test_exact_packaged_manifest_contract_resolves_every_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "assets" / "sounds"
            files = {}
            for event in REQUIRED_SOUND_EVENTS:
                name = f"{event.value}.wav"
                files[event.value] = name
                self._write_silent_wav(root / name)
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "files": files}), encoding="utf-8"
            )
            resolver = PackagedSoundAssetResolver(tmp)
            for event in REQUIRED_SOUND_EVENTS:
                self.assertEqual(resolver.resolve(event), (root / f"{event.value}.wav").resolve())

    def test_variant_catalog_defaults_to_variant_one_when_optional_catalog_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "assets" / "sounds"
            files = {}
            for event in REQUIRED_SOUND_EVENTS:
                name = f"{event.value}.wav"
                files[event.value] = name
                self._write_silent_wav(root / name)
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "files": files}), encoding="utf-8"
            )

            resolver = PackagedSoundAssetResolver(tmp)
            options = resolver.variants_for(SoundEvent.MOVE)

            self.assertEqual([item.variant_id for item in options], ["1"])
            self.assertEqual(options[0].path, (root / "move.wav").resolve())

    def test_variant_catalog_resolves_selected_user_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "assets" / "sounds"
            files = {}
            events = {}
            for event in REQUIRED_SOUND_EVENTS:
                name = f"{event.value}.wav"
                files[event.value] = name
                self._write_silent_wav(root / name)
                events[event.value] = [
                    {
                        "id": "1",
                        "file": name,
                        "label_uk": "Варіант 1",
                        "label_en": "Variant 1",
                    }
                ]
            alternate = root / "library" / "Board" / "MOVE2.WAV"
            self._write_silent_wav(alternate)
            events[SoundEvent.MOVE.value].append(
                {
                    "id": "2",
                    "file": "library/Board/MOVE2.WAV",
                    "label_uk": "Хід 2",
                    "label_en": "Move 2",
                }
            )
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "files": files}), encoding="utf-8"
            )
            (root / "variants.json").write_text(
                json.dumps({"schema_version": 1, "events": events}), encoding="utf-8"
            )

            resolver = PackagedSoundAssetResolver(tmp)

            self.assertEqual(
                resolver.resolve(SoundEvent.MOVE, variant_id="2"),
                alternate.resolve(),
            )
            self.assertEqual(
                [item.variant_id for item in resolver.variants_for(SoundEvent.MOVE)],
                ["1", "2"],
            )

    def test_layer_catalog_resolves_original_move_impact_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "assets" / "sounds"
            files = {}
            events = {}
            for event in REQUIRED_SOUND_EVENTS:
                name = f"{event.value}.wav"
                files[event.value] = name
                self._write_silent_wav(root / name)
                events[event.value] = [
                    {
                        "id": "1",
                        "file": name,
                        "label_uk": "Варіант 1",
                        "label_en": "Variant 1",
                    }
                ]
            impact = root / "library" / "Board" / "MOVEHIT1.WAV"
            self._write_silent_wav(impact)
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "files": files}), encoding="utf-8"
            )
            (root / "variants.json").write_text(
                json.dumps({"schema_version": 1, "events": events}), encoding="utf-8"
            )
            (root / "layers.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "events": {
                            "move": {
                                "1": ["move.wav", "library/Board/MOVEHIT1.WAV"]
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            resolver = PackagedSoundAssetResolver(tmp)

            self.assertEqual(
                resolver.resolve_sequence(SoundEvent.MOVE),
                ((root / "move.wav").resolve(), impact.resolve()),
            )
            self.assertEqual(
                resolver.resolve_sequence(SoundEvent.CHECK),
                ((root / "check.wav").resolve(),),
            )

    def test_layer_catalog_rejects_async_or_wrong_primary_sequences(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "assets" / "sounds"
            files = {}
            events = {}
            for event in REQUIRED_SOUND_EVENTS:
                name = f"{event.value}.wav"
                files[event.value] = name
                self._write_silent_wav(root / name)
                events[event.value] = [
                    {
                        "id": "1",
                        "file": name,
                        "label_uk": "Варіант 1",
                        "label_en": "Variant 1",
                    }
                ]
            extra = root / "extra.wav"
            self._write_silent_wav(extra)
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "files": files}), encoding="utf-8"
            )
            (root / "variants.json").write_text(
                json.dumps({"schema_version": 1, "events": events}), encoding="utf-8"
            )

            (root / "layers.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "events": {"start": {"1": ["start.wav", "extra.wav"]}},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "asynchronous sound event"):
                PackagedSoundAssetResolver(tmp).load_layer_catalog()

            (root / "layers.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "events": {"move": {"1": ["extra.wav", "move.wav"]}},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "must start with its selected variant"):
                PackagedSoundAssetResolver(tmp).load_layer_catalog()

    def test_variant_catalog_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "assets" / "sounds"
            files = {}
            events = {}
            for event in REQUIRED_SOUND_EVENTS:
                name = f"{event.value}.wav"
                files[event.value] = name
                self._write_silent_wav(root / name)
                events[event.value] = [
                    {
                        "id": "1",
                        "file": name,
                        "label_uk": "Варіант 1",
                        "label_en": "Variant 1",
                    }
                ]
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "files": files}), encoding="utf-8"
            )
            for unsafe in ("../move.wav", "..\\move.wav", "/move.wav", "C:\\move.wav"):
                with self.subTest(unsafe=unsafe):
                    changed = json.loads(json.dumps(events))
                    changed[SoundEvent.MOVE.value][0]["file"] = unsafe
                    (root / "variants.json").write_text(
                        json.dumps({"schema_version": 1, "events": changed}),
                        encoding="utf-8",
                    )
                    with self.assertRaises(ValueError):
                        PackagedSoundAssetResolver(tmp).load_variant_catalog()

    def test_missing_asset_is_explicit_error_not_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "assets" / "sounds"
            root.mkdir(parents=True)
            files = {event.value: f"{event.value}.wav" for event in REQUIRED_SOUND_EVENTS}
            for event in REQUIRED_SOUND_EVENTS:
                if event is not SoundEvent.CHECK:
                    self._write_silent_wav(root / files[event.value])
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "files": files}), encoding="utf-8"
            )
            with self.assertRaises(FileNotFoundError):
                PackagedSoundAssetResolver(tmp).resolve(SoundEvent.CHECK)

    def test_manifest_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "assets" / "sounds"
            root.mkdir(parents=True)
            files = {event.value: f"{event.value}.wav" for event in REQUIRED_SOUND_EVENTS}
            files[SoundEvent.MOVE.value] = "../move.wav"
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "files": files}), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                PackagedSoundAssetResolver(tmp).load_manifest()

    def test_scaled_copy_supports_unsigned_8bit_pcm(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "alert.wav"
            with wave.open(str(source), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(1)
                writer.setframerate(8000)
                writer.writeframes(bytes([0, 64, 128, 192, 255]))

            adapter = WindowsSoundPlaybackAdapter(
                PackagedSoundAssetResolver(tmp),
                cache_dir=Path(tmp) / "cache",
            )
            scaled = adapter._scaled_copy(source, SoundEvent.LOW_TIME, 50)

            with wave.open(str(scaled), "rb") as reader:
                self.assertEqual(reader.getsampwidth(), 1)
                self.assertEqual(reader.getcomptype(), "NONE")
                self.assertEqual(
                    list(reader.readframes(reader.getnframes())),
                    [64, 96, 128, 160, 192],
                )

    def test_scaled_cache_is_bound_to_source_bytes_not_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "move.wav"
            self._write_silent_wav(source)
            adapter = WindowsSoundPlaybackAdapter(
                PackagedSoundAssetResolver(tmp),
                cache_dir=Path(tmp) / "cache",
            )

            first_mtime = source.stat().st_mtime_ns
            first = adapter._scaled_copy(source, SoundEvent.MOVE, 50)

            with wave.open(str(source), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(8000)
                writer.writeframes(b"\x10\x00" * 8)
            source.touch()
            import os
            os.utime(source, ns=(first_mtime, first_mtime))

            second = adapter._scaled_copy(source, SoundEvent.MOVE, 50)
            self.assertNotEqual(first, second)
            self.assertFalse(first.exists())
            self.assertTrue(second.is_file())

    def test_scaled_cache_prunes_superseded_variant_for_same_event_and_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "move.wav"
            self._write_silent_wav(source)
            cache = Path(tmp) / "cache"
            adapter = WindowsSoundPlaybackAdapter(
                PackagedSoundAssetResolver(tmp),
                cache_dir=cache,
            )

            first = adapter._scaled_copy(source, SoundEvent.MOVE, 50)
            with wave.open(str(source), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(8000)
                writer.writeframes(b"\x20\x00" * 8)

            second = adapter._scaled_copy(source, SoundEvent.MOVE, 50)

            self.assertNotEqual(first, second)
            self.assertFalse(first.exists())
            self.assertTrue(second.is_file())
            self.assertEqual(list(cache.glob("move-v50-*.wav")), [second])

    def test_scaled_cache_keeps_sibling_layers_for_same_event_and_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_source = Path(tmp) / "move.wav"
            second_source = Path(tmp) / "movehit.wav"
            self._write_silent_wav(first_source)
            with wave.open(str(second_source), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(8000)
                writer.writeframes(b"\x20\x00" * 8)

            cache = Path(tmp) / "cache"
            adapter = WindowsSoundPlaybackAdapter(
                PackagedSoundAssetResolver(tmp),
                cache_dir=cache,
            )

            first_cache = adapter._scaled_copy(first_source, SoundEvent.MOVE, 50)
            second_cache = adapter._scaled_copy(second_source, SoundEvent.MOVE, 50)

            self.assertTrue(first_cache.is_file())
            self.assertTrue(second_cache.is_file())
            self.assertNotEqual(first_cache, second_cache)
            self.assertEqual(
                set(cache.glob("move-v50-*.wav")),
                {first_cache, second_cache},
            )

            with wave.open(str(first_source), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(8000)
                writer.writeframes(b"\x30\x00" * 8)
            replacement = adapter._scaled_copy(first_source, SoundEvent.MOVE, 50)

            self.assertFalse(first_cache.exists())
            self.assertTrue(replacement.is_file())
            self.assertTrue(second_cache.is_file())
            self.assertEqual(
                set(cache.glob("move-v50-*.wav")),
                {replacement, second_cache},
            )

    def test_scaled_cache_prunes_legacy_unversioned_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "move.wav"
            self._write_silent_wav(source)
            cache = Path(tmp) / "cache"
            cache.mkdir()
            legacy = cache / "move-v50.wav"
            legacy.write_bytes(b"stale pre-content-addressed cache")
            adapter = WindowsSoundPlaybackAdapter(
                PackagedSoundAssetResolver(tmp),
                cache_dir=cache,
            )

            current = adapter._scaled_copy(source, SoundEvent.MOVE, 50)

            self.assertNotEqual(current, legacy)
            self.assertIn("-s1-", current.name)
            self.assertFalse(legacy.exists())
            self.assertTrue(current.is_file())

    def test_scaled_cache_schema_change_invalidates_derived_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "move.wav"
            self._write_silent_wav(source)
            cache = Path(tmp) / "cache"
            adapter = WindowsSoundPlaybackAdapter(
                PackagedSoundAssetResolver(tmp),
                cache_dir=cache,
            )

            first = adapter._scaled_copy(source, SoundEvent.MOVE, 50)
            with patch("acs.sound_windows.SCALED_SOUND_CACHE_FORMAT_VERSION", 2):
                second = adapter._scaled_copy(source, SoundEvent.MOVE, 50)

            self.assertNotEqual(first, second)
            self.assertIn("-s2-", second.name)
            self.assertFalse(first.exists())
            self.assertTrue(second.is_file())

    def test_scaled_cache_rebuilds_truncated_content_addressed_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "move.wav"
            self._write_silent_wav(source)
            cache = Path(tmp) / "cache"
            adapter = WindowsSoundPlaybackAdapter(
                PackagedSoundAssetResolver(tmp),
                cache_dir=cache,
            )

            destination = adapter._scaled_copy(source, SoundEvent.MOVE, 50)
            expected = destination.read_bytes()
            destination.write_bytes(expected[:-4])

            rebuilt = adapter._scaled_copy(source, SoundEvent.MOVE, 50)

            self.assertEqual(rebuilt, destination)
            self.assertEqual(rebuilt.read_bytes(), expected)

    def test_scaled_cache_rebuilds_same_length_payload_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "move.wav"
            self._write_silent_wav(source)
            cache = Path(tmp) / "cache"
            adapter = WindowsSoundPlaybackAdapter(
                PackagedSoundAssetResolver(tmp),
                cache_dir=cache,
            )

            destination = adapter._scaled_copy(source, SoundEvent.MOVE, 50)
            expected = destination.read_bytes()
            corrupted = bytearray(expected)
            corrupted[-2:] = b"\xff\x7f"
            self.assertEqual(len(corrupted), len(expected))
            destination.write_bytes(corrupted)

            rebuilt = adapter._scaled_copy(source, SoundEvent.MOVE, 50)

            self.assertEqual(rebuilt, destination)
            self.assertEqual(rebuilt.read_bytes(), expected)

    def test_scaled_cache_rejects_truncated_source_without_publishing_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "move.wav"
            self._write_silent_wav(source)
            source.write_bytes(source.read_bytes()[:-4])
            cache = Path(tmp) / "cache"
            adapter = WindowsSoundPlaybackAdapter(
                PackagedSoundAssetResolver(tmp),
                cache_dir=cache,
            )

            with self.assertRaisesRegex(ValueError, "truncated PCM WAV asset"):
                adapter._scaled_copy(source, SoundEvent.MOVE, 50)

            self.assertEqual(list(cache.glob("move-v50-*.wav")), [])

    def test_scaled_cache_prune_failure_does_not_break_new_playable_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "move.wav"
            self._write_silent_wav(source)
            cache = Path(tmp) / "cache"
            adapter = WindowsSoundPlaybackAdapter(
                PackagedSoundAssetResolver(tmp),
                cache_dir=cache,
            )
            first = adapter._scaled_copy(source, SoundEvent.MOVE, 50)

            with wave.open(str(source), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(8000)
                writer.writeframes(b"\x30\x00" * 8)

            original_unlink = Path.unlink

            def fail_only_for_old_variant(path, *args, **kwargs):
                if path == first:
                    raise PermissionError("cache entry busy")
                return original_unlink(path, *args, **kwargs)

            with patch("acs.sound_windows.Path.unlink", autospec=True, side_effect=fail_only_for_old_variant):
                second = adapter._scaled_copy(source, SoundEvent.MOVE, 50)

            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())

    def test_scaled_cache_publish_failure_leaves_no_partial_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "move.wav"
            self._write_silent_wav(source)
            cache = Path(tmp) / "cache"
            adapter = WindowsSoundPlaybackAdapter(
                PackagedSoundAssetResolver(tmp),
                cache_dir=cache,
            )

            with patch("acs.sound_windows.os.replace", side_effect=OSError("publish failed")):
                with self.assertRaises(OSError):
                    adapter._scaled_copy(source, SoundEvent.MOVE, 50)

            self.assertEqual(list(cache.glob("move-v50-*.wav")), [])
            self.assertEqual(list(cache.glob("*.tmp")), [])

    def test_scaled_cache_cleanup_failure_does_not_mask_publish_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "move.wav"
            self._write_silent_wav(source)
            cache = Path(tmp) / "cache"
            adapter = WindowsSoundPlaybackAdapter(
                PackagedSoundAssetResolver(tmp),
                cache_dir=cache,
            )

            with patch(
                "acs.sound_windows.os.replace",
                side_effect=OSError("publish failed"),
            ), patch(
                "acs.sound_windows.Path.unlink",
                autospec=True,
                side_effect=PermissionError("temporary cache busy"),
            ):
                with self.assertRaisesRegex(OSError, "publish failed"):
                    adapter._scaled_copy(source, SoundEvent.MOVE, 50)

    def test_windows_stop_uses_play_sound_null_without_fallback(self):
        calls = []
        fake_winsound = types.SimpleNamespace(
            PlaySound=lambda sound, flags: calls.append((sound, flags)),
        )
        adapter = WindowsSoundPlaybackAdapter(
            PackagedSoundAssetResolver("."),
            cache_dir=Path("."),
        )

        with patch("acs.sound_windows.sys.platform", "win32"), patch.dict(
            sys.modules,
            {"winsound": fake_winsound},
        ):
            adapter.stop()

        self.assertEqual(calls, [(None, 0)])

    def test_windows_playback_resolves_persisted_variant_before_playing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "move2.wav"
            self._write_silent_wav(source)

            class VariantResolver:
                def __init__(self):
                    self.calls = []

                def resolve(self, event, *, variant_id=None):
                    self.calls.append((event, variant_id))
                    return source

            resolver = VariantResolver()
            calls = []
            fake_winsound = types.SimpleNamespace(
                SND_FILENAME=0x00020000,
                SND_NODEFAULT=0x00000002,
                PlaySound=lambda sound, flags: calls.append((sound, flags)),
            )
            adapter = WindowsSoundPlaybackAdapter(
                resolver,
                cache_dir=Path(tmp) / "cache",
                variant_provider=lambda event: "2",
            )

            with patch("acs.sound_windows.sys.platform", "win32"), patch.dict(
                sys.modules,
                {"winsound": fake_winsound},
            ):
                adapter.play(SoundEvent.MOVE, volume=100)

            self.assertEqual(resolver.calls, [(SoundEvent.MOVE, "2")])
            self.assertEqual(calls[0][0], str(source))

    def test_windows_playback_scales_selected_8bit_low_time_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "assets" / "sounds"
            root.mkdir(parents=True)
            files = {}
            variants = {}
            for event in REQUIRED_SOUND_EVENTS:
                name = f"{event.value}.wav"
                files[event.value] = name
                self._write_silent_wav(root / name)
                variants[event.value] = [
                    {
                        "id": "1",
                        "file": name,
                        "label_uk": "Варіант 1",
                        "label_en": "Variant 1",
                    }
                ]

            alert = root / "low-time-2.wav"
            with wave.open(str(alert), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(1)
                writer.setframerate(8000)
                writer.writeframes(bytes([0, 64, 128, 192, 255] * 4))
            variants[SoundEvent.LOW_TIME.value].append(
                {
                    "id": "2",
                    "file": alert.name,
                    "label_uk": "Сигнал 2",
                    "label_en": "Alert 2",
                }
            )
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "files": files}),
                encoding="utf-8",
            )
            (root / "variants.json").write_text(
                json.dumps({"schema_version": 1, "events": variants}),
                encoding="utf-8",
            )

            calls = []
            fake_winsound = types.SimpleNamespace(
                SND_FILENAME=0x00020000,
                SND_NODEFAULT=0x00000002,
                SND_ASYNC=0x00000001,
                PlaySound=lambda sound, flags: calls.append((sound, flags)),
            )
            adapter = WindowsSoundPlaybackAdapter(
                PackagedSoundAssetResolver(tmp),
                cache_dir=Path(tmp) / "cache",
                variant_provider=lambda event: "2" if event is SoundEvent.LOW_TIME else "1",
            )

            with patch("acs.sound_windows.sys.platform", "win32"), patch.dict(
                sys.modules,
                {"winsound": fake_winsound},
            ):
                adapter.play(SoundEvent.LOW_TIME, volume=35)

            self.assertEqual(len(calls), 1)
            played = Path(calls[0][0])
            self.assertNotEqual(played, alert)
            with wave.open(str(played), "rb") as reader:
                self.assertEqual(reader.getsampwidth(), 1)
                self.assertEqual(reader.getcomptype(), "NONE")
            self.assertTrue(
                calls[0][1] & fake_winsound.SND_ASYNC,
                calls[0],
            )

    def test_windows_playback_plays_declared_move_layers_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "move.wav"
            second = Path(tmp) / "movehit.wav"
            self._write_silent_wav(first)
            self._write_silent_wav(second)

            class LayerResolver:
                def resolve_sequence(self, event, *, variant_id=None):
                    self.call = (event, variant_id)
                    return (first, second)

            resolver = LayerResolver()
            calls = []
            fake_winsound = types.SimpleNamespace(
                SND_FILENAME=0x00020000,
                SND_NODEFAULT=0x00000002,
                PlaySound=lambda sound, flags: calls.append((sound, flags)),
            )
            adapter = WindowsSoundPlaybackAdapter(
                resolver,
                cache_dir=Path(tmp) / "cache",
                variant_provider=lambda event: "1",
            )

            with patch("acs.sound_windows.sys.platform", "win32"), patch.dict(
                sys.modules,
                {"winsound": fake_winsound},
            ):
                adapter.play(SoundEvent.MOVE, volume=100)

            expected_flags = fake_winsound.SND_FILENAME | fake_winsound.SND_NODEFAULT
            self.assertEqual(resolver.call, (SoundEvent.MOVE, "1"))
            self.assertEqual(
                calls,
                [(str(first), expected_flags), (str(second), expected_flags)],
            )

    def test_start_clock_and_low_time_assets_use_non_blocking_windows_playback(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "long.wav"
            self._write_silent_wav(source)

            class StaticResolver:
                def resolve(self, event):
                    return source

            calls = []
            fake_winsound = types.SimpleNamespace(
                SND_FILENAME=0x00020000,
                SND_NODEFAULT=0x00000002,
                SND_ASYNC=0x00000001,
                PlaySound=lambda sound, flags: calls.append((sound, flags)),
            )
            adapter = WindowsSoundPlaybackAdapter(
                StaticResolver(),
                cache_dir=Path(tmp) / "cache",
            )

            with patch("acs.sound_windows.sys.platform", "win32"), patch.dict(
                sys.modules,
                {"winsound": fake_winsound},
            ):
                adapter.play(SoundEvent.START, volume=100)
                adapter.play(SoundEvent.TICK, volume=100)
                adapter.play(SoundEvent.LOW_TIME, volume=100)

            expected = (
                fake_winsound.SND_FILENAME
                | fake_winsound.SND_NODEFAULT
                | fake_winsound.SND_ASYNC
            )
            self.assertEqual(
                [flags for _sound, flags in calls],
                [expected, expected, expected],
            )

    def test_windows_playback_uses_python312_compatible_synchronous_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "move.wav"
            self._write_silent_wav(source)

            class StaticResolver:
                def resolve(self, event):
                    self.event = event
                    return source

            calls = []
            fake_winsound = types.SimpleNamespace(
                SND_FILENAME=0x00020000,
                SND_NODEFAULT=0x00000002,
                PlaySound=lambda sound, flags: calls.append((sound, flags)),
            )
            adapter = WindowsSoundPlaybackAdapter(
                StaticResolver(),
                cache_dir=Path(tmp) / "cache",
            )

            with patch("acs.sound_windows.sys.platform", "win32"), patch.dict(
                sys.modules,
                {"winsound": fake_winsound},
            ):
                adapter.play(SoundEvent.MOVE, volume=100)

            self.assertFalse(hasattr(fake_winsound, "SND_SYNC"))
            self.assertEqual(
                calls,
                [
                    (
                        str(source),
                        fake_winsound.SND_FILENAME | fake_winsound.SND_NODEFAULT,
                    )
                ],
            )


if __name__ == "__main__":
    unittest.main()
