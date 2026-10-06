from __future__ import annotations

import unittest

from acs.analysis_service import AnalysisLine, AnalysisResult, AnalysisService
from acs.engine_ports import EngineContractError, RawAnalysisLine


class OutputEngine:
    def __init__(self, output) -> None:
        self.output = output

    def analyze(self, fen, multipv=5, depth=16):
        return self.output

    def close(self) -> None:
        pass


class CurrentAnalysisPassiveDtoBoundaryTests(unittest.TestCase):
    def test_raw_line_rejects_active_scalar_and_tuple_subclasses_before_hooks(self) -> None:
        class HostileInt(int):
            touched = False

            def __lt__(self, other):
                type(self).touched = True
                raise AssertionError("hostile integer comparison must not execute")

            def __le__(self, other):
                type(self).touched = True
                raise AssertionError("hostile integer comparison must not execute")

        class HostileText(str):
            touched = False

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile text strip must not execute")

        class HostileTuple(tuple):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("hostile tuple length must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("hostile tuple iteration must not execute")

        cases = (
            lambda: RawAnalysisLine(HostileInt(1), "cp", 0, ("e2e4",)),
            lambda: RawAnalysisLine(1, HostileText("cp"), 0, ("e2e4",)),
            lambda: RawAnalysisLine(1, "cp", HostileInt(0), ("e2e4",)),
            lambda: RawAnalysisLine(1, "cp", 0, HostileTuple(("e2e4",))),
            lambda: RawAnalysisLine(1, "cp", 0, (HostileText("e2e4"),)),
        )
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(EngineContractError):
                    case()
                self.assertFalse(HostileInt.touched)
                self.assertFalse(HostileText.touched)
                self.assertFalse(HostileTuple.touched)

    def test_analysis_result_rejects_active_container_line_and_error_subclasses(self) -> None:
        class HostileTuple(tuple):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("hostile result tuple length must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("hostile result tuple iteration must not execute")

        class HostileText(str):
            touched = False

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile result error strip must not execute")

        class HostileLine(AnalysisLine):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if name in {"multipv", "depth", "score_kind", "score_value", "pv"} and type(self).armed:
                    type(self).touched = True
                    raise AssertionError("hostile AnalysisLine attribute hook must not execute")
                return super().__getattribute__(name)

        exact = AnalysisLine(1, 12, "cp", 0, ("e2e4",))
        hostile_line = HostileLine(1, 12, "cp", 0, ("e2e4",))
        HostileLine.armed = True

        with self.assertRaises(EngineContractError):
            AnalysisResult("fen", 1, False, HostileTuple((exact,)))
        self.assertFalse(HostileTuple.touched)

        with self.assertRaises(EngineContractError):
            AnalysisResult("fen", 1, False, (hostile_line,))
        self.assertFalse(HostileLine.touched)

        with self.assertRaises(EngineContractError):
            AnalysisResult("fen", 1, False, (), HostileText("provider failed"))
        self.assertFalse(HostileText.touched)

    def test_legacy_provider_rejects_active_tuple_and_raw_line_subclasses_before_hooks(self) -> None:
        class HostileTuple(tuple):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("hostile legacy tuple length must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("hostile legacy tuple iteration must not execute")

        class HostileRaw(RawAnalysisLine):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if name in {"depth", "score_kind", "score_value", "pv"} and type(self).armed:
                    type(self).touched = True
                    raise AssertionError("hostile raw analysis attribute hook must not execute")
                return super().__getattribute__(name)

        raw_subclass = HostileRaw(12, "cp", 0, ("e2e4",))
        HostileRaw.armed = True

        outputs = (
            (HostileTuple((12, ("cp", 0), ("e2e4",))),),
            ((12, HostileTuple(("cp", 0)), ("e2e4",)),),
            (raw_subclass,),
        )
        for output in outputs:
            with self.subTest(output=output):
                result = AnalysisService(lambda value=output: OutputEngine(value)).analyze(
                    "fen", multipv=1
                )
                self.assertIsNotNone(result.error)
                self.assertEqual(result.lines, ())
                self.assertFalse(HostileTuple.touched)
                self.assertFalse(HostileRaw.touched)

    def test_exact_builtin_analysis_values_preserve_existing_semantics(self) -> None:
        result = AnalysisService(
            lambda: OutputEngine(((12, ("cp", 20), ("e2e4", "e7e5")),))
        ).analyze(" fen ", multipv=1)

        self.assertIsNone(result.error)
        self.assertEqual(result.fen, "fen")
        self.assertEqual(result.lines[0].pv, ("e2e4", "e7e5"))


if __name__ == "__main__":
    unittest.main()
