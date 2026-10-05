from __future__ import annotations

import unittest

from acs.engine_ports import EngineContractError, EngineMoveRequest, EngineMoveResult


class CurrentEngineMovePassiveDtoTests(unittest.TestCase):
    def test_move_request_rejects_active_integer_subclasses(self) -> None:
        class HostileInt(int):
            touched = False

            def __lt__(self, other):
                type(self).touched = True
                raise AssertionError("hostile request integer comparison must not execute")

            def __le__(self, other):
                type(self).touched = True
                raise AssertionError("hostile request integer comparison must not execute")

        with self.assertRaises(EngineContractError):
            EngineMoveRequest("fen", level=HostileInt(5))
        self.assertFalse(HostileInt.touched)

        with self.assertRaises(EngineContractError):
            EngineMoveRequest("fen", movetime_ms=HostileInt(100))
        self.assertFalse(HostileInt.touched)

    def test_move_result_rejects_active_text_before_strip(self) -> None:
        class HostileText(str):
            touched = False

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile move strip must not execute")

        with self.assertRaises(EngineContractError):
            EngineMoveResult(HostileText("e2e4"), 5, 100)
        self.assertFalse(HostileText.touched)

    def test_move_result_rejects_active_integer_subclasses_before_bounds(self) -> None:
        class HostileInt(int):
            touched = False

            def __lt__(self, other):
                type(self).touched = True
                raise AssertionError("hostile result integer comparison must not execute")

            def __le__(self, other):
                type(self).touched = True
                raise AssertionError("hostile result integer comparison must not execute")

            def __gt__(self, other):
                type(self).touched = True
                raise AssertionError("hostile result integer comparison must not execute")

            def __ge__(self, other):
                type(self).touched = True
                raise AssertionError("hostile result integer comparison must not execute")

        with self.assertRaises(EngineContractError):
            EngineMoveResult("e2e4", HostileInt(5), 100)
        self.assertFalse(HostileInt.touched)

        with self.assertRaises(EngineContractError):
            EngineMoveResult("e2e4", 5, HostileInt(100))
        self.assertFalse(HostileInt.touched)

    def test_exact_builtin_move_dtos_keep_existing_semantics(self) -> None:
        request = EngineMoveRequest("  fen-current  ", level=-5, movetime_ms=-1)
        self.assertEqual(request.fen, "fen-current")
        self.assertEqual(request.level, -5)
        self.assertEqual(request.movetime_ms, -1)

        result = EngineMoveResult("  e2e4  ", 5, 100)
        self.assertEqual(result.move, "e2e4")
        self.assertEqual(result.level, 5)
        self.assertEqual(result.movetime_ms, 100)


if __name__ == "__main__":
    unittest.main()
