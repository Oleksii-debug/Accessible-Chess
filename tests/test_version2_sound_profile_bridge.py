from __future__ import annotations

import threading
import unittest
from unittest import mock

from acs.sound_profile_store import SoundProfileManager
from acs.sound_runtime import ProfiledSoundRuntime, SoundAssetRequest
from acs.sound_settings_application import SoundSettingsApplication, SoundSettingsResult
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


class _Storage:
    def __init__(self) -> None:
        self.raw = None

    def read_profile(self):
        return self.raw

    def write_profile_atomically(self, payload):
        self.raw = dict(payload)


class _Playback:
    def __init__(self) -> None:
        self.requests: list[SoundAssetRequest] = []

    def play_sound(self, request: SoundAssetRequest) -> None:
        self.requests.append(request)


def _api():
    storage = _Storage()
    manager = SoundProfileManager(storage, lambda _requested: "classic")
    manager.load()
    playback = _Playback()
    runtime = ProfiledSoundRuntime(playback, manager.profile_provider)
    settings = SoundSettingsApplication(manager, runtime)
    api = object.__new__(Version2ReleaseAccessibleChessAPI)
    api._ui_thread = threading.get_ident()
    api._ui_owner = None
    api._ui_action = None
    api._ui_closed = False
    api.lang = "en"
    api._sound_settings_application = None
    api.bind_sound_settings_application(settings)
    return api, manager, playback


class Version2SoundProfileBridgeTests(unittest.TestCase):
    def test_legacy_master_methods_use_durable_profile_authority(self) -> None:
        api, manager, _ = _api()

        initial = api.get_sound_settings()
        self.assertTrue(initial["ok"])
        self.assertTrue(initial["enabled"])
        self.assertEqual(80, initial["volume"])

        disabled = api.set_sound_enabled(False)
        self.assertTrue(disabled["ok"])
        self.assertFalse(manager.current.master_enabled)
        self.assertFalse(disabled["enabled"])

        volume = api.set_sound_volume(42)
        self.assertTrue(volume["ok"])
        self.assertEqual(42, manager.current.master_volume_percent)
        self.assertEqual(42, volume["volume"])

    def test_profile_command_mutates_event_and_returns_same_snapshot(self) -> None:
        api, manager, _ = _api()

        result = api.sound_settings_command(
            "set_event",
            {"event_id": "capture", "enabled": False, "volume_percent": 35},
        )

        self.assertTrue(result["ok"])
        preference = manager.current.preference_for("capture")
        self.assertFalse(preference.enabled)
        self.assertEqual(35, preference.volume_percent)
        snapshot = result["snapshot"]
        capture = next(item for item in snapshot["events"] if item["event_id"] == "capture")
        self.assertFalse(capture["enabled"])
        self.assertEqual(35, capture["volume_percent"])

    def test_profile_preview_uses_profiled_runtime_not_legacy_flat_settings(self) -> None:
        api, manager, playback = _api()
        manager.set_master(volume_percent=50)
        manager.set_event(
            "move",
            manager.current.preference_for("move"),
        )

        result = api.sound_settings_command("preview", {"event_id": "move"})

        self.assertTrue(result["ok"])
        self.assertEqual(1, len(playback.requests))
        request = playback.requests[0]
        self.assertEqual("classic", request.pack_id)
        self.assertEqual("move", request.event_id)
        self.assertEqual(50, request.volume)

    def test_failed_profile_write_preserves_confirmed_state_and_snapshot(self) -> None:
        api, manager, _ = _api()
        before = manager.current
        storage = manager._storage

        with mock.patch.object(
            storage,
            "write_profile_atomically",
            side_effect=OSError("disk full"),
        ):
            result = api.sound_settings_command(
                "set_event",
                {"event_id": "capture", "enabled": False, "volume_percent": 35},
            )

        self.assertFalse(result["ok"])
        self.assertEqual(before, manager.current)
        snapshot_result = api.sound_settings_snapshot()
        self.assertTrue(snapshot_result["ok"])
        capture = next(
            item
            for item in snapshot_result["snapshot"]["events"]
            if item["event_id"] == "capture"
        )
        self.assertTrue(capture["enabled"])
        self.assertEqual(100, capture["volume_percent"])

    def test_browser_pack_commands_route_only_closed_world_payloads(self) -> None:
        api, manager, _ = _api()
        sound = api._sound_settings_application
        self.assertIsNotNone(sound)
        snapshot = sound.snapshot(language="en")
        routed = SoundSettingsResult(True, snapshot, "Pack changed.")

        with mock.patch.object(sound, "select_pack", return_value=routed) as select:
            result = api.sound_settings_command("select_pack", {"pack_id": "soft"})
            self.assertTrue(result["ok"])
            select.assert_called_once_with("soft", language="en")

        with mock.patch.object(sound, "install_pack", return_value=routed) as install:
            result = api.sound_settings_command(
                "install_pack",
                {"pack_id": "soft", "activate": True},
            )
            self.assertTrue(result["ok"])
            install.assert_called_once_with("soft", activate=True, language="en")

        with mock.patch.object(sound, "uninstall_pack", return_value=routed) as uninstall:
            result = api.sound_settings_command("uninstall_pack", {"pack_id": "soft"})
            self.assertTrue(result["ok"])
            uninstall.assert_called_once_with("soft", language="en")

        before = manager.current
        invalid = (
            ("select_pack", {"pack_id": "soft", "extra": True}),
            ("select_pack", {"pack_id": None}),
            ("install_pack", {"pack_id": "soft", "activate": 1}),
            ("install_pack", {"activate": True}),
            ("uninstall_pack", {"pack_id": "soft", "extra": True}),
        )
        for command, payload in invalid:
            with self.subTest(command=command, payload=payload):
                result = api.sound_settings_command(command, payload)
                self.assertFalse(result["ok"])
                self.assertEqual(before, manager.current)

    def test_browser_sound_payload_contract_rejects_extra_and_noop_fields(self) -> None:
        api, manager, playback = _api()
        before = manager.current

        cases = (
            ("set_master", {"enabled": False, "unexpected": True}),
            ("set_master", {}),
            ("set_master", {"enabled": None}),
            ("set_master", {"volume_percent": None}),
            ("set_master", {"volume_percent": True}),
            ("set_event", {"event_id": "move"}),
            ("set_event", {"event_id": "move", "enabled": None}),
            ("set_event", {"event_id": "move", "volume_percent": None}),
            ("set_event", {"event_id": "move", "enabled": False, "sound_id": "move.alt"}),
            ("preview", {"event_id": "move", "unexpected": True}),
            ("preview", {1: "move"}),
        )
        for command, payload in cases:
            with self.subTest(command=command, payload=payload):
                result = api.sound_settings_command(command, payload)
                self.assertFalse(result["ok"])
                self.assertEqual(before, manager.current)
                self.assertEqual([], playback.requests)

    def test_partial_pack_failure_returns_current_authoritative_snapshot(self) -> None:
        api, manager, _ = _api()
        sound = api._sound_settings_application
        self.assertIsNotNone(sound)

        def partially_applied_uninstall(pack_id: str, *, language: str = "uk"):
            self.assertEqual("soft", pack_id)
            manager.set_pack("classic")
            raise OSError("asset deletion failed after fallback persistence")

        manager._current = manager.current.__class__(
            pack_id="soft",
            master_enabled=manager.current.master_enabled,
            master_volume_percent=manager.current.master_volume_percent,
            events=manager.current.events,
        )
        with mock.patch.object(sound, "uninstall_pack", side_effect=partially_applied_uninstall):
            result = api.sound_settings_command("uninstall_pack", {"pack_id": "soft"})

        self.assertFalse(result["ok"])
        self.assertEqual("classic", manager.current.pack_id)
        self.assertEqual("classic", result["snapshot"]["active_pack_id"])
        self.assertIn("refreshed", result["message"].lower())

    def test_invalid_browser_command_error_includes_current_snapshot_when_readable(self) -> None:
        api, manager, _ = _api()
        result = api.sound_settings_command("set_master", {"enabled": None})
        self.assertFalse(result["ok"])
        self.assertEqual(manager.current.pack_id, result["snapshot"]["active_pack_id"])

    def test_invalid_browser_sound_command_fails_closed(self) -> None:
        api, manager, _ = _api()
        before = manager.current

        result = api.sound_settings_command("set_event", {"event_id": "not-an-event"})

        self.assertFalse(result["ok"])
        self.assertEqual(before, manager.current)

    def test_second_sound_settings_owner_is_rejected(self) -> None:
        api, _, _ = _api()
        other_manager = SoundProfileManager(_Storage(), lambda _requested: "classic")
        other_manager.load()
        other = SoundSettingsApplication(
            other_manager,
            ProfiledSoundRuntime(_Playback(), other_manager.profile_provider),
        )

        with self.assertRaisesRegex(RuntimeError, "already bound"):
            api.bind_sound_settings_application(other)


if __name__ == "__main__":
    unittest.main()
