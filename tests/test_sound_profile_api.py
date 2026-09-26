from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from acs.sound_pack_store import SoundPackStore
from acs.sound_profiles import (
    CORE_SOUND_EVENTS,
    SoundEventPreference,
    SoundPackManifest,
    SoundPreviewService,
    SoundProfile,
    SoundProfileController,
    SoundProfileStore,
)
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_installable_pack(root: Path, pack_id="quiet.wood", version="1.0.0"):
    files = {}
    hashes = {}
    sound_ids = list(CORE_SOUND_EVENTS) + ["alternate.move"]
    for sound_id in sound_ids:
        relative = f"audio/{sound_id}.wav"
        payload = b"RIFF" + sound_id.encode("ascii")
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        files[sound_id] = relative
        hashes[sound_id] = _digest(payload)
    manifest = SoundPackManifest(
        pack_id=pack_id,
        version=version,
        title="Quiet Wood",
        author="Accessible Chess",
        license_id="CC0-1.0",
        provenance="https://example.invalid/quiet-wood",
        files=files,
        sha256=hashes,
    )
    (root / "manifest.json").write_text(
        json.dumps(manifest.to_mapping()),
        encoding="utf-8",
    )
    return manifest


class _Playback:
    def __init__(self):
        self.calls = []

    def play_sound(self, **kwargs):
        self.calls.append(kwargs)


class Version2SoundProfileApiTests(unittest.TestCase):
    def _api(self, root: Path):
        profile_store = SoundProfileStore(root / "sound-profile.json")
        controller = SoundProfileController(
            profile_store,
            legacy_settings={"sounds": True, "volume": 80},
        )
        packs = SoundPackStore(root / "sound-packs")
        playback = _Playback()
        preview = SoundPreviewService(controller.current, playback)
        api = Version2ReleaseAccessibleChessAPI(
            keymap_path=root / "keymap.json",
            sound_profile_controller=controller,
            sound_preview_service=preview,
            sound_pack_store=packs,
        )
        return api, controller, packs, playback, profile_store

    def test_v2_profile_settings_are_persistent_and_expose_per_event_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api, controller, _packs, _playback, profile_store = self._api(root)

            state = api.get_sound_settings()
            self.assertTrue(state["ok"])
            self.assertTrue(state["enabled"])
            self.assertEqual(state["volume"], 80)
            self.assertEqual(state["pack_id"], "classic")
            self.assertIn("low_time", state["event_preferences"])

            changed = api.set_sound_event_volume("capture", 35)
            self.assertTrue(changed["ok"])
            self.assertEqual(
                changed["event_preferences"]["capture"]["volume_percent"],
                35,
            )

            clone = SoundProfileStore(profile_store.path).load()
            self.assertEqual(clone.preference_for("capture").volume_percent, 35)
            self.assertEqual(controller.current(), clone)

    def test_save_failure_does_not_publish_in_memory_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api, controller, _packs, _playback, profile_store = self._api(root)
            before = controller.current()
            original = profile_store.save

            def fail(_profile):
                raise OSError("disk full")

            profile_store.save = fail
            try:
                result = api.set_sound_volume(20)
            finally:
                profile_store.save = original

            self.assertFalse(result["ok"])
            self.assertEqual(controller.current(), before)

    def test_installed_pack_is_selectable_and_alternate_sound_is_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api, controller, packs, _playback, _profile_store = self._api(root)
            staging = root / "staging"
            staging.mkdir()
            _write_installable_pack(staging)
            packs.install_from_staging(staging)

            state = api.get_sound_settings()
            self.assertIn(
                "quiet.wood",
                [item["pack_id"] for item in state["packs"] if item["valid"]],
            )

            selected = api.set_sound_pack("quiet.wood")
            self.assertTrue(selected["ok"])
            self.assertEqual(selected["effective_pack_id"], "quiet.wood")
            self.assertIn("alternate.move", selected["available_sound_ids"])

            alternate = api.set_sound_event_sound("move", "alternate.move")
            self.assertTrue(alternate["ok"])
            self.assertEqual(
                controller.current().preference_for("move").sound_id,
                "alternate.move",
            )

            missing = api.set_sound_event_sound("move", "missing.sound")
            self.assertFalse(missing["ok"])
            self.assertEqual(
                controller.current().preference_for("move").sound_id,
                "alternate.move",
            )

    def test_classic_pack_rejects_false_alternate_sound_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            api, controller, _packs, _playback, _store = self._api(Path(tmp))
            result = api.set_sound_event_sound("move", "capture")
            self.assertFalse(result["ok"])
            self.assertIsNone(controller.current().preference_for("move").sound_id)

    def test_preview_uses_profiled_event_selection_and_effective_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api, controller, packs, playback, _store = self._api(root)
            staging = root / "staging"
            staging.mkdir()
            _write_installable_pack(staging)
            packs.install_from_staging(staging)
            self.assertTrue(api.set_sound_pack("quiet.wood")["ok"])
            self.assertTrue(api.set_sound_event_sound("move", "alternate.move")["ok"])
            self.assertTrue(api.set_sound_event_volume("move", 50)["ok"])
            self.assertTrue(api.set_sound_volume(60)["ok"])

            result = api.preview_sound("move")

            self.assertTrue(result["ok"])
            self.assertEqual(
                playback.calls[-1],
                {
                    "pack_id": "quiet.wood",
                    "sound_id": "alternate.move",
                    "volume": 30,
                    "fallback_event": __import__(
                        "acs.sound_events", fromlist=["SoundEvent"]
                    ).SoundEvent.MOVE,
                },
            )

    def test_uninstall_active_pack_falls_back_profile_before_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api, controller, packs, _playback, _store = self._api(root)
            staging = root / "staging"
            staging.mkdir()
            _write_installable_pack(staging)
            packs.install_from_staging(staging)
            api.set_sound_pack("quiet.wood")
            api.set_sound_event_sound("move", "alternate.move")

            result = api.uninstall_sound_pack("quiet.wood")

            self.assertTrue(result["ok"])
            self.assertEqual(controller.current().pack_id, "classic")
            self.assertIsNone(controller.current().preference_for("move").sound_id)
            self.assertFalse((packs.root / "quiet.wood").exists())

    def test_missing_active_pack_is_reported_but_effective_pack_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api, controller, _packs, _playback, _store = self._api(root)
            controller.replace(SoundProfile(pack_id="gone.pack"))

            state = api.get_sound_settings()

            self.assertEqual(state["pack_id"], "gone.pack")
            self.assertEqual(state["effective_pack_id"], "classic")
            self.assertTrue(state["pack_warning"])


if __name__ == "__main__":
    unittest.main()
