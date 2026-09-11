from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


class _FakeContinuousAnalysis:
    def __init__(self) -> None:
        self.running = False
        self.fen: str | None = None
        self.multipv = 5
        self.depth = 16
        self.last_result = None

    def start(self, fen: str, multipv: int = 5, depth: int = 16) -> int:
        self.running = True
        self.fen = fen
        self.multipv = multipv
        self.depth = depth
        return 1

    def update_position(self, fen: str) -> int:
        self.fen = fen
        return 1

    def stop(self) -> int:
        self.running = False
        return 1

    def configure(self, *, multipv=None, depth=None) -> int:
        if multipv is not None:
            self.multipv = multipv
        if depth is not None:
            self.depth = depth
        self.last_result = None
        return 1

    def close(self) -> None:
        self.running = False

    def state(self):
        return SimpleNamespace(
            running=self.running,
            fen=self.fen,
            multipv=self.multipv,
            depth=self.depth,
            last_result=self.last_result,
        )

    def publish_lines(self, fen: str) -> None:
        pvs = (
            ("e2e4", "e7e5"),
            ("d2d4", "d7d5"),
            ("c2c4", "e7e5"),
            ("g1f3", "d7d5"),
            ("b2b3", "e7e5"),
        )
        lines = tuple(
            SimpleNamespace(
                multipv=index,
                depth=18 + index,
                score_kind="cp",
                score_value=10 * index,
                pv=pvs[index - 1],
            )
            for index in range(1, self.multipv + 1)
        )
        self.last_result = SimpleNamespace(
            fen=fen,
            stale=False,
            error=None,
            lines=lines,
        )


class Version2BoardAnalysisHotkeyFeedbackTests(unittest.TestCase):
    def make_api(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        engine = _FakeContinuousAnalysis()
        api = Version2ReleaseAccessibleChessAPI(
            keymap_path=Path(temp.name) / "keymap.json",
            continuous_analysis=engine,
        )
        return api, engine

    def test_alt_pv_shortcuts_resolve_from_board_and_expose_result(self) -> None:
        api, engine = self.make_api()
        self.assertTrue(api.toggle_engine()["ok"])
        fen = api.get_state()["fen"]
        engine.publish_lines(fen)

        for index in range(1, 6):
            with self.subTest(index=index):
                resolved = api.keymap_resolve_binding("board", f"Alt+{index}")
                self.assertIsNotNone(resolved)
                self.assertEqual(resolved["actionId"], f"analysis.pv{index}")
                self.assertEqual(resolved["context"], "analysis")

                result = api.dispatch_action(resolved["actionId"])

                self.assertTrue(result["ok"])
                announcement = str(result.get("announcement") or "")
                self.assertIn(f"Варіант {index}", announcement)
                self.assertIn("глибина", announcement.lower())
                self.assertIn("оцінка", announcement.lower())
                self.assertNotIn("e2e4", announcement)

    def test_exact_board_binding_keeps_precedence_over_analysis_fallback(self) -> None:
        api, _engine = self.make_api()

        resolved = api.keymap_resolve_binding("board", "V")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["actionId"], "board.evaluation")
        self.assertEqual(resolved["context"], "board")

    def test_unavailable_analysis_hotkey_is_not_silent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            api = Version2ReleaseAccessibleChessAPI(
                keymap_path=Path(temp) / "keymap.json"
            )
            resolved = api.keymap_resolve_binding("board", "Alt+1")
            self.assertIsNotNone(resolved)

            result = api.dispatch_action(resolved["actionId"])

            self.assertFalse(result["ok"])
            self.assertTrue(str(result.get("announcement") or "").strip())
            self.assertIn("недоступ", str(result["announcement"]).lower())


if __name__ == "__main__":
    unittest.main()
