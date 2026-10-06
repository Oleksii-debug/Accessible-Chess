from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import tempfile
import unittest

from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI


class _HostileMapping(Mapping):
    touched = False

    @classmethod
    def reset(cls) -> None:
        cls.touched = False

    def __iter__(self):
        type(self).touched = True
        raise AssertionError("hostile clock mapping iteration must not execute")

    def __len__(self):
        type(self).touched = True
        raise AssertionError("hostile clock mapping length must not execute")

    def __getitem__(self, key):
        type(self).touched = True
        raise AssertionError("hostile clock mapping item access must not execute")


class _HostileText(str):
    armed = False
    touched = False

    @classmethod
    def reset(cls) -> None:
        cls.armed = False
        cls.touched = False

    @classmethod
    def _touch(cls) -> None:
        if cls.armed:
            cls.touched = True
            raise AssertionError("hostile clock text hook must not execute")

    def __hash__(self):
        type(self)._touch()
        return super().__hash__()

    def __eq__(self, other):
        type(self)._touch()
        return super().__eq__(other)

    def __str__(self):
        type(self)._touch()
        return super().__str__()


class _HostileTruth:
    touched = False

    def __bool__(self):
        type(self).touched = True
        raise AssertionError("hostile clock truth hook must not execute")


class _HostileInt(int):
    armed = False
    touched = False

    @classmethod
    def reset(cls) -> None:
        cls.armed = False
        cls.touched = False

    def __lt__(self, other):
        if type(self).armed:
            type(self).touched = True
            raise AssertionError("hostile clock integer comparison must not execute")
        return super().__lt__(other)

    def __eq__(self, other):
        if type(self).armed:
            type(self).touched = True
            raise AssertionError("hostile clock integer equality must not execute")
        return super().__eq__(other)

    def __int__(self):
        if type(self).armed:
            type(self).touched = True
            raise AssertionError("hostile clock integer coercion must not execute")
        return super().__int__()


class Stage1BoardClockProjectionPassiveTests(unittest.TestCase):
    def make_api(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return Stage1ReleaseAccessibleChessAPI(
            keymap_path=Path(temp.name) / "keymap.json"
        )

    @staticmethod
    def timed_projection(**overrides):
        value = {
            "available": True,
            "configured": True,
            "active": True,
            "phase": "active",
            "thinking": False,
            "humanSide": "w",
            "engineSide": "b",
            "level": 5,
            "initialMinutes": 5,
            "incrementSeconds": 3,
            "turn": "human",
            "whiteClock": "4:58",
            "blackClock": "4:57",
            "clockStatus": "",
            "canTakeback": True,
            "canOfferDraw": True,
            "canStop": True,
            "canRetry": False,
            "error": None,
            "status": "",
        }
        value.update(overrides)
        return value

    def test_active_mapping_root_is_rejected_before_mapping_hooks(self) -> None:
        api = self.make_api()
        _HostileMapping.reset()
        api._engine_game_projection = lambda: _HostileMapping()

        self.assertEqual(api._clock_pair(), (None, None))
        self.assertFalse(_HostileMapping.touched)

        result = api.dispatch_action("board.my_clock", "e2")
        self.assertFalse(result["ok"])
        self.assertFalse(_HostileMapping.touched)

    def test_active_dict_key_is_rejected_before_hash_or_equality(self) -> None:
        api = self.make_api()
        _HostileText.reset()
        key = _HostileText("configured")
        projection = self.timed_projection()
        del projection["configured"]
        projection[key] = True
        _HostileText.armed = True
        api._engine_game_projection = lambda: projection

        self.assertEqual(api._clock_pair(), (None, None))
        self.assertFalse(_HostileText.touched)

    def test_configured_truth_object_is_rejected_before_truthiness(self) -> None:
        api = self.make_api()
        _HostileTruth.touched = False
        api._engine_game_projection = lambda: self.timed_projection(
            configured=_HostileTruth()
        )

        self.assertEqual(api._clock_pair(), (None, None))
        self.assertFalse(_HostileTruth.touched)

    def test_integer_subclasses_are_rejected_before_comparison_or_coercion(self) -> None:
        api = self.make_api()
        for field in ("initialMinutes", "incrementSeconds"):
            with self.subTest(field=field):
                _HostileInt.reset()
                value = _HostileInt(5)
                _HostileInt.armed = True
                api._engine_game_projection = lambda f=field, v=value: self.timed_projection(
                    **{f: v}
                )
                self.assertEqual(api._clock_pair(), (None, None))
                self.assertFalse(_HostileInt.touched)

    def test_active_human_side_and_clock_values_are_rejected_before_hooks(self) -> None:
        api = self.make_api()
        for field, raw in (
            ("humanSide", "w"),
            ("whiteClock", "4:58"),
            ("blackClock", "4:57"),
        ):
            with self.subTest(field=field):
                _HostileText.reset()
                value = _HostileText(raw)
                _HostileText.armed = True
                api._engine_game_projection = lambda f=field, v=value: self.timed_projection(
                    **{f: v}
                )
                self.assertEqual(api._clock_pair(), (None, None))
                self.assertFalse(_HostileText.touched)

    def test_projection_width_is_bounded_before_field_lookup(self) -> None:
        api = self.make_api()
        projection = self.timed_projection()
        projection["unexpected"] = "value"
        self.assertEqual(len(projection), 21)
        api._engine_game_projection = lambda: projection

        self.assertEqual(api._clock_pair(), (None, None))

    def test_exact_timed_projection_preserves_human_relative_clock_order(self) -> None:
        api = self.make_api()
        api._engine_game_projection = lambda: self.timed_projection()

        self.assertEqual(api._clock_pair(), ("4:58", "4:57"))
        mine = api.dispatch_action("board.my_clock", "e2")
        opponent = api.dispatch_action("board.opponent_clock", "e2")
        self.assertTrue(mine["ok"])
        self.assertTrue(opponent["ok"])
        self.assertIn("4:58", mine["announcement"])
        self.assertIn("4:57", opponent["announcement"])

        api._engine_game_projection = lambda: self.timed_projection(humanSide="b")
        self.assertEqual(api._clock_pair(), ("4:57", "4:58"))

    def test_exact_untimed_projection_keeps_existing_accessible_label(self) -> None:
        api = self.make_api()
        api._engine_game_projection = lambda: self.timed_projection(
            initialMinutes=0,
            incrementSeconds=0,
            whiteClock="0:00",
            blackClock="0:00",
        )

        self.assertEqual(api._clock_pair(), ("Без годинника", "Без годинника"))
        result = api.dispatch_action("board.my_clock", "e2")
        self.assertTrue(result["ok"])
        self.assertIn("Без годинника", result["announcement"])


if __name__ == "__main__":
    unittest.main()
