from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from acs.tactile_input import (
    TactileDeviceCapabilities,
    TactileDeviceProfile,
    TactileDeviceSettingsStore,
    TactileInputController,
    TactileInputError,
    TactileInputEvent,
    TactileOrientation,
    TactileProfileRegistry,
    TactileSettings,
    TactileSettingsError,
    default_tactile_profiles,
)


class Registry:
    def __init__(self):
        self.ids = {
            *(f"board.file_{i}" for i in range(1, 9)),
            *(f"board.rank_{i}" for i in range(1, 9)),
            "board.current",
            "board.read_fen",
            "board.last_captured",
            "board.last_move",
            "board.my_clock",
            "board.opponent_clock",
            "board.legal_moves",
            "board.captures",
            "board.surroundings",
            "board.attackers",
            "board.defenders",
            "board.material",
            "board.evaluation",
            "board.best_move",
            "history.previous",
            "history.next",
            "board.activate",
            "edit.undo",
            "move.submit",
        }

    def definition(self, action_id):
        if action_id not in self.ids:
            raise KeyError(action_id)
        return action_id


class TactileInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "settings.json"
        self.registry = Registry()
        self.calls = []

    def controller(self, profiles=None):
        return TactileInputController(
            TactileProfileRegistry(profiles or default_tactile_profiles()),
            action_registry=self.registry,
            dispatch=lambda action, payload: self.calls.append(
                (action, dict(payload))
            ),
            settings_store=TactileDeviceSettingsStore(self.path),
        )

    def test_white_orientation_routes_a8_and_h1(self):
        controller = self.controller()
        caps = TactileDeviceCapabilities(8, 8, routing=True)
        connection = controller.connect(
            "dev",
            caps,
            profile_id="generic-8x8-white",
            remember=False,
        )
        result = controller.handle(
            TactileInputEvent.routing(
                "dev", connection.generation, 0, 0
            )
        )
        self.assertEqual("a8", result.square)
        self.assertEqual(
            ("board.file_1", "board.rank_8", "board.current"),
            result.dispatched_actions,
        )
        self.calls.clear()
        result = controller.handle(
            TactileInputEvent.routing(
                "dev", connection.generation, 7, 7
            )
        )
        self.assertEqual("h1", result.square)

    def test_black_orientation_routes_h1_and_a8(self):
        controller = self.controller()
        caps = TactileDeviceCapabilities(8, 8, touch=True)
        connection = controller.connect(
            "dev",
            caps,
            profile_id="generic-8x8-black",
            remember=False,
        )
        first = controller.handle(
            TactileInputEvent.touch(
                "dev", connection.generation, 0, 0
            )
        )
        last = controller.handle(
            TactileInputEvent.touch(
                "dev", connection.generation, 7, 7
            )
        )
        self.assertEqual("h1", first.square)
        self.assertEqual("a8", last.square)

    def test_stride_gap_is_not_routed(self):
        profile = TactileDeviceProfile(
            "spaced",
            "Spaced",
            rows=15,
            columns=15,
            row_stride=2,
            column_stride=2,
        )
        controller = self.controller((profile,))
        caps = TactileDeviceCapabilities(15, 15, routing=True)
        connection = controller.connect("dev", caps, remember=False)
        with self.assertRaises(TactileInputError):
            controller.handle(
                TactileInputEvent.routing(
                    "dev", connection.generation, 1, 0
                )
            )
        self.assertEqual([], self.calls)

    def test_unsafe_button_action_is_rejected_at_construction(self):
        profile = TactileDeviceProfile(
            "unsafe",
            "Unsafe",
            8,
            8,
            button_actions=(("play", "board.activate"),),
        )
        with self.assertRaises(TactileInputError):
            self.controller((profile,))

    def test_safe_button_dispatch(self):
        profile = TactileDeviceProfile(
            "keys",
            "Keys",
            8,
            8,
            button_actions=(("last", "board.last_move"),),
        )
        controller = self.controller((profile,))
        caps = TactileDeviceCapabilities(
            8,
            8,
            buttons=frozenset({"last"}),
        )
        connection = controller.connect("dev", caps, remember=False)
        result = controller.handle(
            TactileInputEvent.button_press(
                "dev", connection.generation, "last"
            )
        )
        self.assertEqual(
            ("board.last_move",), result.dispatched_actions
        )
        self.assertEqual(
            [("board.last_move", {})], self.calls
        )

    def test_profile_requires_mapped_buttons(self):
        profile = TactileDeviceProfile(
            "keys",
            "Keys",
            8,
            8,
            button_actions=(("last", "board.last_move"),),
        )
        controller = self.controller((profile,))
        with self.assertRaises(TactileInputError):
            controller.connect(
                "dev",
                TactileDeviceCapabilities(8, 8),
                profile_id="keys",
                remember=False,
            )

    def test_routing_and_touch_require_capability(self):
        controller = self.controller()
        connection = controller.connect(
            "dev",
            TactileDeviceCapabilities(8, 8),
            remember=False,
        )
        with self.assertRaises(TactileInputError):
            controller.handle(
                TactileInputEvent.routing(
                    "dev", connection.generation, 0, 0
                )
            )
        with self.assertRaises(TactileInputError):
            controller.handle(
                TactileInputEvent.touch(
                    "dev", connection.generation, 0, 0
                )
            )
        self.assertEqual([], self.calls)

    def test_disconnect_rejects_input(self):
        controller = self.controller()
        connection = controller.connect(
            "dev",
            TactileDeviceCapabilities(8, 8, routing=True),
            remember=False,
        )
        controller.disconnect("dev")
        with self.assertRaises(TactileInputError):
            controller.handle(
                TactileInputEvent.routing(
                    "dev", connection.generation, 0, 0
                )
            )

    def test_reconnect_generation_rejects_stale_input(self):
        controller = self.controller()
        caps = TactileDeviceCapabilities(8, 8, routing=True)
        first = controller.connect("dev", caps, remember=True)
        controller.disconnect("dev")
        second = controller.reconnect("dev", caps)
        self.assertIsNotNone(second)
        self.assertGreater(second.generation, first.generation)
        with self.assertRaises(TactileInputError):
            controller.handle(
                TactileInputEvent.routing(
                    "dev", first.generation, 0, 0
                )
            )
        self.assertEqual([], self.calls)

    def test_reconnect_survives_store_reload(self):
        controller = self.controller()
        caps = TactileDeviceCapabilities(8, 8, routing=True)
        controller.connect(
            "serial-1",
            caps,
            profile_id="generic-8x8-black",
            remember=True,
        )
        reloaded = self.controller()
        connection = reloaded.reconnect("serial-1", caps)
        self.assertIsNotNone(connection)
        self.assertEqual(
            "generic-8x8-black", connection.profile_id
        )

    def test_reconnect_can_be_disabled_persistently(self):
        controller = self.controller()
        caps = TactileDeviceCapabilities(8, 8, routing=True)
        controller.connect("dev", caps, remember=True)
        controller.set_reconnect_enabled(False)
        reloaded = self.controller()
        self.assertIsNone(reloaded.reconnect("dev", caps))

    def test_incompatible_saved_profile_does_not_reconnect(self):
        profile = TactileDeviceProfile(
            "wide", "Wide", 8, 16
        )
        controller = self.controller((profile,))
        controller.connect(
            "dev",
            TactileDeviceCapabilities(8, 16, routing=True),
            remember=True,
        )
        controller.disconnect("dev")
        self.assertIsNone(
            controller.reconnect(
                "dev",
                TactileDeviceCapabilities(8, 8, routing=True),
            )
        )

    def test_default_profile_selection(self):
        controller = self.controller()
        controller.set_default_profile("generic-8x8-black")
        connection = controller.connect(
            "new",
            TactileDeviceCapabilities(8, 8, routing=True),
            remember=False,
        )
        self.assertEqual(
            "generic-8x8-black", connection.profile_id
        )

    def test_explicit_incompatible_profile_fails_closed(self):
        controller = self.controller()
        with self.assertRaises(TactileInputError):
            controller.connect(
                "dev",
                TactileDeviceCapabilities(8, 8),
                profile_id="generic-8x16-left",
                remember=False,
            )

    def test_profile_change_invalidates_old_generation(self):
        controller = self.controller()
        caps = TactileDeviceCapabilities(8, 8, routing=True)
        first = controller.connect(
            "dev",
            caps,
            profile_id="generic-8x8-white",
            remember=False,
        )
        second = controller.set_connected_profile(
            "dev",
            "generic-8x8-black",
            remember=False,
        )
        self.assertGreater(second.generation, first.generation)
        with self.assertRaises(TactileInputError):
            controller.handle(
                TactileInputEvent.routing(
                    "dev", first.generation, 0, 0
                )
            )

    def test_settings_round_trip(self):
        store = TactileDeviceSettingsStore(self.path)
        expected = TactileSettings(
            default_profile_id="generic-8x8-white",
            reconnect_enabled=True,
            device_profiles=(
                ("dev-a", "generic-8x8-black"),
            ),
        )
        store.save(expected)
        self.assertEqual(expected, store.load())

    def test_settings_unknown_field_fails_closed(self):
        self.path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "default_profile_id": None,
                    "reconnect_enabled": True,
                    "device_profiles": [],
                    "extra": 1,
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(TactileSettingsError):
            TactileDeviceSettingsStore(self.path).load()

    def test_settings_symlink_is_rejected(self):
        target = Path(self.temp.name) / "target.json"
        target.write_text("{}", encoding="utf-8")
        try:
            self.path.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaises(TactileSettingsError):
            TactileDeviceSettingsStore(self.path).load()

    def test_missing_navigation_command_fails_construction(self):
        self.registry.ids.remove("board.rank_8")
        with self.assertRaises(TactileInputError):
            self.controller()

    def test_dispatch_failure_is_not_reported_as_success(self):
        calls = []

        def dispatch(action, payload):
            calls.append(action)
            if action == "board.rank_8":
                raise RuntimeError("host refused")

        controller = TactileInputController(
            TactileProfileRegistry(default_tactile_profiles()),
            action_registry=self.registry,
            dispatch=dispatch,
            settings_store=TactileDeviceSettingsStore(self.path),
        )
        connection = controller.connect(
            "dev",
            TactileDeviceCapabilities(8, 8, routing=True),
            remember=False,
        )
        with self.assertRaises(RuntimeError):
            controller.handle(
                TactileInputEvent.routing(
                    "dev", connection.generation, 0, 0
                )
            )
        self.assertEqual(
            ["board.file_1", "board.rank_8"], calls
        )

    def test_square_navigation_never_dispatches_mutators(self):
        controller = self.controller()
        connection = controller.connect(
            "dev",
            TactileDeviceCapabilities(8, 8, routing=True),
            remember=False,
        )
        for row in range(8):
            for column in range(8):
                controller.handle(
                    TactileInputEvent.routing(
                        "dev",
                        connection.generation,
                        row,
                        column,
                    )
                )
        action_ids = {action for action, _ in self.calls}
        self.assertFalse(
            action_ids.intersection(
                {"board.activate", "edit.undo", "move.submit"}
            )
        )
        self.assertTrue(
            all(
                action.startswith("board.file_")
                or action.startswith("board.rank_")
                or action == "board.current"
                for action in action_ids
            )
        )


if __name__ == "__main__":
    unittest.main()
