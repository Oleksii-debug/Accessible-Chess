from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import tempfile
import unittest

from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI
from acs.webapp import MAX_MOVE_ENTRY_CHARS
from tests.test_version2_release_ui import _Application


class _ActiveText(str):
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
            raise AssertionError("active text hook must not execute")

    def strip(self, *args, **kwargs):
        type(self)._touch()
        return super().strip(*args, **kwargs)

    def startswith(self, *args, **kwargs):
        type(self)._touch()
        return super().startswith(*args, **kwargs)

    def __hash__(self):
        type(self)._touch()
        return super().__hash__()

    def __eq__(self, other):
        type(self)._touch()
        return super().__eq__(other)

    def __len__(self):
        type(self)._touch()
        return super().__len__()

    def __contains__(self, item):
        type(self)._touch()
        return super().__contains__(item)

    def __str__(self):
        type(self)._touch()
        return super().__str__()


class _ActiveMapping(Mapping):
    touched = False

    @classmethod
    def reset(cls) -> None:
        cls.touched = False

    def __iter__(self):
        type(self).touched = True
        raise AssertionError("active mapping iterator must not execute")

    def __len__(self):
        type(self).touched = True
        raise AssertionError("active mapping length must not execute")

    def __getitem__(self, key):
        type(self).touched = True
        raise AssertionError("active mapping item read must not execute")


class Stage1V2BoardCommandPassiveIngressTests(unittest.TestCase):
    def make_stage1(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return Stage1ReleaseAccessibleChessAPI(
            keymap_path=Path(temp.name) / "keymap.json"
        )

    def make_v2(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        api = Version2ReleaseAccessibleChessAPI(
            keymap_path=Path(temp.name) / "keymap.json"
        )
        api.bind_version2_application(_Application())
        return api

    def test_stage1_rejects_active_action_id_before_text_hooks(self) -> None:
        api = self.make_stage1()
        _ActiveText.reset()
        value = _ActiveText("board.current")
        _ActiveText.armed = True

        result = api.dispatch_action(value, "e2")

        self.assertFalse(result["ok"])
        self.assertFalse(_ActiveText.touched)

    def test_stage1_rejects_active_board_square_before_text_hooks(self) -> None:
        api = self.make_stage1()
        _ActiveText.reset()
        value = _ActiveText("e2")
        _ActiveText.armed = True

        result = api.dispatch_action("board.current", value)

        self.assertFalse(result["ok"])
        self.assertFalse(_ActiveText.touched)

    def test_stage1_rejects_active_move_text_before_keymap_normalization(self) -> None:
        api = self.make_stage1()
        before = api.board.fen()
        _ActiveText.reset()
        value = _ActiveText("e4")
        _ActiveText.armed = True

        result = api.make_move(value)

        self.assertFalse(result["ok"])
        self.assertEqual(api.board.fen(), before)
        self.assertFalse(_ActiveText.touched)

    def test_stage1_move_entry_bound_precedes_keymap_alias_processing(self) -> None:
        api = self.make_stage1()
        before = api.board.fen()

        result = api.make_move("e" * (MAX_MOVE_ENTRY_CHARS + 1))

        self.assertFalse(result["ok"])
        self.assertEqual(api.board.fen(), before)

    def test_v2_keyboard_dispatch_rejects_active_action_and_square(self) -> None:
        api = self.make_v2()

        _ActiveText.reset()
        action = _ActiveText("screen.library")
        _ActiveText.armed = True
        rejected_action = api.dispatch_action(action)
        self.assertFalse(rejected_action["ok"])
        self.assertFalse(_ActiveText.touched)

        _ActiveText.reset()
        square = _ActiveText("e2")
        _ActiveText.armed = True
        rejected_square = api.dispatch_action("screen.library", square)
        self.assertFalse(rejected_square["ok"])
        self.assertFalse(_ActiveText.touched)

    def test_v2_board_bridge_rejects_active_action_before_strip(self) -> None:
        api = self.make_v2()
        _ActiveText.reset()
        action = _ActiveText("board.current")
        _ActiveText.armed = True

        with self.assertRaisesRegex(ValueError, "board action id"):
            api.v2_board_dispatch(action, {"square": "e2"})

        self.assertFalse(_ActiveText.touched)

    def test_v2_board_bridge_rejects_active_mapping_root_before_hooks(self) -> None:
        api = self.make_v2()
        _ActiveMapping.reset()

        with self.assertRaisesRegex(TypeError, "canonical dict"):
            api.v2_board_dispatch("board.current", _ActiveMapping())

        self.assertFalse(_ActiveMapping.touched)

    def test_v2_board_bridge_rejects_active_dict_key_before_hash_or_equality(self) -> None:
        api = self.make_v2()
        _ActiveText.reset()
        key = _ActiveText("square")
        payload = {key: "e2"}
        _ActiveText.armed = True

        with self.assertRaisesRegex(ValueError, "payload is not supported"):
            api.v2_board_dispatch("board.current", payload)

        self.assertFalse(_ActiveText.touched)

    def test_v2_board_bridge_rejects_active_square_value_before_hooks(self) -> None:
        api = self.make_v2()
        _ActiveText.reset()
        square = _ActiveText("e2")
        payload = {"square": square}
        _ActiveText.armed = True

        with self.assertRaisesRegex(ValueError, "payload is not supported"):
            api.v2_board_dispatch("board.current", payload)

        self.assertFalse(_ActiveText.touched)

    def test_exact_stage1_and_v2_board_commands_keep_existing_behavior(self) -> None:
        stage1 = self.make_stage1()
        move = stage1.make_move("e4")
        self.assertTrue(move["ok"])
        current = stage1.dispatch_action("board.current", "e4")
        self.assertTrue(current["ok"])
        self.assertEqual(current["focusSquare"], "e4")

        v2 = self.make_v2()
        bridged = v2.v2_board_dispatch(" board.current ", {"square": "e2"})
        self.assertTrue(bridged["ok"])
        self.assertEqual(bridged["focusSquare"], "e2")


if __name__ == "__main__":
    unittest.main()
