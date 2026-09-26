from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from acs.sound_events import SoundEvent
from acs.sound_profiles import (
    CORE_SOUND_EVENTS,
    SOUND_PACK_MANIFEST_SCHEMA_VERSION,
    SOUND_PROFILE_SCHEMA_VERSION,
    SoundEventPreference,
    SoundPackCatalogEntry,
    SoundPackManifest,
    SoundPreviewService,
    SoundProfile,
    SoundProfileStore,
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SoundProfileTests(unittest.TestCase):
    def test_per_event_enable_volume_and_sound_selection_are_independent(self) -> None:
        profile = SoundProfile(
            master_volume_percent=80,
            events={
                "capture": SoundEventPreference(True, 50, "wood.capture"),
                "check": SoundEventPreference(False, 100),
            },
        )
        self.assertEqual(profile.effective_volume("capture"), 40)
        self.assertEqual(profile.selected_sound_id("capture"), "wood.capture")
        self.assertEqual(profile.effective_volume("check"), 0)
        self.assertEqual(profile.selected_sound_id("move"), "move")

    def test_master_disable_silences_chess_and_classroom_events(self) -> None:
        profile = SoundProfile(master_enabled=False)
        self.assertEqual(profile.effective_volume("move"), 0)
        self.assertEqual(profile.effective_volume("classroom.join"), 0)

    def test_profile_round_trip_is_versioned_and_deterministic(self) -> None:
        profile = SoundProfile(
            pack_id="soft.wood",
            master_enabled=True,
            master_volume_percent=63,
            events={
                "move": SoundEventPreference(True, 70, "quiet.move"),
                "classroom.join": SoundEventPreference(False, 25, "room.join"),
            },
        )
        payload = profile.to_mapping()
        self.assertEqual(payload["schema_version"], SOUND_PROFILE_SCHEMA_VERSION)
        self.assertEqual(SoundProfile.from_mapping(payload), profile)
        self.assertEqual(list(payload["events"]), ["classroom.join", "move"])

    def test_legacy_flat_settings_migrate_into_profile(self) -> None:
        profile = SoundProfile.from_mapping({"sounds": False, "volume": 37})
        self.assertEqual(profile.pack_id, "classic")
        self.assertFalse(profile.master_enabled)
        self.assertEqual(profile.master_volume_percent, 37)

    def test_unknown_future_profile_schema_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            SoundProfile.from_mapping({"schema_version": 999})

    def test_boolean_volume_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            SoundEventPreference(volume_percent=True)

    def test_switching_to_builtin_can_clear_custom_sound_ids(self) -> None:
        profile = SoundProfile(
            pack_id="custom",
            events={"move": SoundEventPreference(sound_id="custom.move")},
        )
        fallback = profile.with_pack("classic", clear_sound_ids=True)
        self.assertEqual(fallback.pack_id, "classic")
        self.assertEqual(fallback.selected_sound_id("move"), "move")


class SoundPackManifestTests(unittest.TestCase):
    def _pack(self, **overrides) -> SoundPackManifest:
        files = {event: f"audio/{event}.wav" for event in CORE_SOUND_EVENTS}
        hashes = {event: _digest(event.encode("ascii")) for event in CORE_SOUND_EVENTS}
        data = {
            "pack_id": "soft.wood",
            "version": "1.0.0",
            "title": "Soft Wood",
            "license_id": "CC0-1.0",
            "files": files,
            "sha256": hashes,
            "author": "Accessible Chess",
            "provenance": "https://example.invalid/soft-wood",
        }
        data.update(overrides)
        return SoundPackManifest(**data)

    def test_complete_core_pack_is_valid_and_round_trips(self) -> None:
        pack = self._pack()
        self.assertIn("low_time", pack.files)
        self.assertEqual(pack.schema_version, SOUND_PACK_MANIFEST_SCHEMA_VERSION)
        self.assertEqual(pack.sound_path("move"), "audio/move.wav")
        self.assertEqual(
            SoundPackManifest.from_mapping(pack.to_mapping()),
            pack,
        )

    def test_every_file_requires_a_pinned_digest(self) -> None:
        files = {event: f"{event}.wav" for event in CORE_SOUND_EVENTS}
        hashes = {event: _digest(b"x") for event in CORE_SOUND_EVENTS[:-1]}
        with self.assertRaises(ValueError):
            self._pack(files=files, sha256=hashes)

    def test_path_traversal_and_executable_payloads_are_rejected(self) -> None:
        files = {event: f"{event}.wav" for event in CORE_SOUND_EVENTS}
        hashes = {event: _digest(event.encode()) for event in CORE_SOUND_EVENTS}
        files["move"] = "../move.wav"
        with self.assertRaises(ValueError):
            self._pack(files=files, sha256=hashes)

        files["move"] = "move.exe"
        with self.assertRaises(ValueError):
            self._pack(files=files, sha256=hashes)

    def test_non_hex_digest_is_rejected(self) -> None:
        hashes = {event: _digest(event.encode()) for event in CORE_SOUND_EVENTS}
        hashes["move"] = "z" * 64
        with self.assertRaises(ValueError):
            self._pack(sha256=hashes)


class SoundPackCatalogEntryTests(unittest.TestCase):
    def _entry(self, **overrides) -> SoundPackCatalogEntry:
        values = {
            "pack_id": "soft.wood",
            "version": "2.0.0",
            "title": "Soft Wood",
            "author": "Accessible Chess",
            "license_id": "CC0-1.0",
            "provenance": "https://example.invalid/source",
            "download_url": "https://cdn.example.invalid/soft-wood.zip",
            "archive_sha256": _digest(b"archive"),
            "archive_size_bytes": 1234,
            "min_product_sound_api": 1,
            "max_product_sound_api": 2,
        }
        values.update(overrides)
        return SoundPackCatalogEntry(**values)

    def test_https_credential_free_catalog_entry_is_valid(self) -> None:
        entry = self._entry()
        self.assertEqual(entry.min_product_sound_api, 1)
        self.assertEqual(entry.max_product_sound_api, 2)

    def test_insecure_or_credentialed_urls_are_rejected(self) -> None:
        for url in (
            "http://example.invalid/pack.zip",
            "https://user:pass@example.invalid/pack.zip",
            "https://example.invalid/pack.zip#fragment",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self._entry(download_url=url)

    def test_inverted_compatibility_range_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._entry(min_product_sound_api=3, max_product_sound_api=2)


class SoundProfileStoreTests(unittest.TestCase):
    def test_missing_store_migrates_legacy_settings_once_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sound-profile.json"
            store = SoundProfileStore(path)
            profile = store.load_or_migrate({"sounds": False, "volume": 45})
            self.assertFalse(profile.master_enabled)
            self.assertEqual(profile.master_volume_percent, 45)
            self.assertTrue(path.is_file())
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["schema_version"], SOUND_PROFILE_SCHEMA_VERSION)

            # A later legacy mapping cannot overwrite the established authority.
            second = store.load_or_migrate({"sounds": True, "volume": 99})
            self.assertEqual(second, profile)

    def test_corrupt_store_recovers_without_overwriting_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sound-profile.json"
            path.write_text("{broken", encoding="utf-8")
            before = path.read_bytes()

            store = SoundProfileStore(path)
            profile = store.load()

            self.assertEqual(profile, SoundProfile())
            self.assertIn("sound profile recovery", store.warning or "")
            self.assertEqual(path.read_bytes(), before)

    def test_save_replaces_atomically_shaped_file_and_leaves_no_temp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sound-profile.json"
            store = SoundProfileStore(path)
            store.save(SoundProfile(master_volume_percent=22))
            self.assertEqual(
                SoundProfile.from_mapping(json.loads(path.read_text(encoding="utf-8"))),
                SoundProfile(master_volume_percent=22),
            )
            self.assertFalse(path.with_name(path.name + ".tmp").exists())


class _PreviewPlayback:
    def __init__(self) -> None:
        self.calls = []

    def play_sound(self, **kwargs) -> None:
        self.calls.append(kwargs)


class SoundPreviewTests(unittest.TestCase):
    def test_preview_routes_profile_pack_sound_and_effective_volume(self) -> None:
        playback = _PreviewPlayback()
        profile = SoundProfile(
            pack_id="soft.wood",
            master_volume_percent=80,
            events={"move": SoundEventPreference(True, 50, "quiet.move")},
        )
        result = SoundPreviewService(lambda: profile, playback).preview("move")
        self.assertTrue(result.played)
        self.assertEqual(
            playback.calls,
            [{
                "pack_id": "soft.wood",
                "sound_id": "quiet.move",
                "volume": 40,
                "fallback_event": SoundEvent.MOVE,
            }],
        )

    def test_silenced_preview_never_touches_playback(self) -> None:
        playback = _PreviewPlayback()
        profile = SoundProfile(
            events={"classroom.join": SoundEventPreference(enabled=False)}
        )
        result = SoundPreviewService(lambda: profile, playback).preview(
            "classroom.join"
        )
        self.assertFalse(result.played)
        self.assertEqual(result.reason, "silenced")
        self.assertEqual(playback.calls, [])


if __name__ == "__main__":
    unittest.main()
