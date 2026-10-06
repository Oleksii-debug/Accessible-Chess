from __future__ import annotations

from pathlib import Path
import threading
import time
import unittest

from acs.analysis_service import AnalysisService
from acs.continuous_analysis import ContinuousAnalysisService
from acs.engine import UCIEngine
from acs.engine_ports import EngineContractError
from acs.ui_analysis_adapter import AnalysisPresentationAdapter
from acs.webapp_keymap import KeymapAwareAccessibleChessAPI


class _Proc:
    def __init__(self) -> None:
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class _UciAnalysisHarness(UCIEngine):
    def __init__(self) -> None:
        super().__init__("stockfish")
        self.sent: list[str] = []

    def start(self) -> None:
        if self.proc is None:
            self.proc = _Proc()

    def send(self, command: str) -> None:
        self.sent.append(command)

    def _drain(self) -> None:
        return None

    def _configure_request_options(self, *, multipv: int, skill_level: int) -> None:
        self.sent.append(f"options multipv={multipv} skill={skill_level}")


class _RecordingAnalysisEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int, int | None]] = []
        self.closed = False

    def analyze(self, fen, multipv=5, depth=16, movetime_ms=None):
        self.calls.append((fen, multipv, depth, movetime_ms))
        return [(depth, ("cp", 28), ("e2e4", "e7e5"))][:multipv]

    def close(self):
        self.closed = True


def _wait(predicate, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class StockfishAnalysisTimeControlTests(unittest.TestCase):
    def test_uci_analysis_uses_movetime_without_starting_second_provider(self):
        engine = _UciAnalysisHarness()
        engine.q.put("info depth 11 multipv 1 score cp 22 pv e2e4 e7e5")
        engine.q.put("bestmove e2e4")

        lines = engine.analyze("fen-a", multipv=1, depth=40, movetime_ms=750)

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].depth, 11)
        self.assertIn("go movetime 750", engine.sent)
        self.assertNotIn("go depth 40", engine.sent)

    def test_depth_mode_remains_original_go_depth_contract(self):
        engine = _UciAnalysisHarness()
        engine.q.put("info depth 18 multipv 1 score cp 12 pv d2d4")
        engine.q.put("bestmove d2d4")

        engine.analyze("fen-a", multipv=1, depth=18)

        self.assertIn("go depth 18", engine.sent)
        self.assertFalse(any(item.startswith("go movetime") for item in engine.sent))

    def test_time_limits_fail_closed_outside_controlled_range(self):
        engine = _UciAnalysisHarness()
        for value in (True, 49, 60_001, "1000"):
            with self.subTest(value=value):
                with self.assertRaises(EngineContractError):
                    engine.analyze("fen-a", movetime_ms=value)

    def test_continuous_analysis_switches_depth_time_and_back(self):
        engine = _RecordingAnalysisEngine()
        service = ContinuousAnalysisService(AnalysisService(lambda: engine))
        try:
            service.start("fen-a", multipv=1, depth=12)
            self.assertTrue(_wait(lambda: len(engine.calls) >= 1))
            self.assertEqual(engine.calls[-1], ("fen-a", 1, 12, None))

            service.configure(movetime_ms=900)
            self.assertTrue(_wait(lambda: len(engine.calls) >= 2))
            self.assertEqual(engine.calls[-1], ("fen-a", 1, 12, 900))
            self.assertEqual(service.state().movetime_ms, 900)

            service.configure(depth=20, movetime_ms=None)
            self.assertTrue(_wait(lambda: len(engine.calls) >= 3))
            self.assertEqual(engine.calls[-1], ("fen-a", 1, 20, None))
            self.assertIsNone(service.state().movetime_ms)
        finally:
            service.close()

    def test_accessible_adapter_exposes_selected_limit_mode(self):
        engine = _RecordingAnalysisEngine()
        service = ContinuousAnalysisService(AnalysisService(lambda: engine))
        adapter = AnalysisPresentationAdapter(service, multipv=2, depth=16)
        try:
            adapter.configure(multipv=3, depth=24, movetime_ms=1200)
            self.assertEqual(adapter.movetime_ms, 1200)
            adapter.enable("fen-a")
            self.assertTrue(_wait(lambda: service.state().last_result is not None))
            snap = adapter.snapshot("fen-a")
            self.assertEqual(snap.movetime_ms, 1200)
            self.assertEqual(snap.as_dict()["movetimeMs"], 1200)

            adapter.configure(multipv=3, depth=22, movetime_ms=None)
            self.assertIsNone(adapter.movetime_ms)
            self.assertTrue(_wait(lambda: service.state().last_result is not None))
            self.assertIsNone(adapter.snapshot("fen-a").movetime_ms)
        finally:
            adapter.close()

    def test_web_ui_exposes_depth_time_bestmove_and_evaluation_controls(self):
        html = (
            Path(__file__).resolve().parents[1] / "web" / "index.html"
        ).read_text(encoding="utf-8")
        for marker in (
            'id="analysis-limit-mode"',
            '<option value="depth">Глибина</option>',
            '<option value="time">Час</option>',
            'id="analysis-time" type="number" min="50" max="60000"',
            'id="analysis-evaluation"',
            'id="analysis-best-move"',
            "apiAction('configure_analysis'",
            "apiAction('dispatch_action','board.evaluation')",
            "apiAction('dispatch_action','board.best_move')",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

    def test_web_api_reports_time_mode_and_keeps_bestmove_accessible(self):
        engine = _RecordingAnalysisEngine()
        service = ContinuousAnalysisService(AnalysisService(lambda: engine))
        with self.subTest("api"):
            api = KeymapAwareAccessibleChessAPI(
                "uk",
                keymap_path=Path("unused-stockfish-time-keymap.json"),
                continuous_analysis=service,
            )
            try:
                configured = api.configure_analysis(2, 16, 800)
                self.assertTrue(configured["ok"])
                self.assertIn("800", configured["announcement"])
                started = api.start_analysis()
                self.assertTrue(started["ok"])
                self.assertTrue(_wait(lambda: service.state().last_result is not None))
                state = api.get_state()
                self.assertEqual(state["analysis"]["movetimeMs"], 800)
                best = api.dispatch_action("board.best_move")
                evaluation = api.dispatch_action("board.evaluation")
                self.assertTrue(best["ok"])
                self.assertTrue(evaluation["ok"])
                self.assertIn("Найкращий хід", best["announcement"])
                self.assertIn("Оцінка", evaluation["announcement"])
            finally:
                api.close_analysis()


if __name__ == "__main__":
    unittest.main()
