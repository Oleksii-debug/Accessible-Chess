from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.analysis_service import AnalysisService
from acs.continuous_analysis import ContinuousAnalysisService
from acs.engine_ports import RawAnalysisLine
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI


class _FakeEngine:
    def analyze(self, fen, multipv=5, depth=16):
        return [
            RawAnalysisLine(depth, "cp", index * 10, ("e2e4",))
            for index in range(1, multipv + 1)
        ]

    def best_move(self, fen, skill_level=10, movetime_ms=500):
        return "e2e4"

    def close(self):
        return None


class CurrentProductEngineStatusUserCopyTests(unittest.TestCase):
    _FORBIDDEN_USER_COPY = (
        "migration",
        "still in progress",
        "перенесення",
        "переноситься",
    )

    def _api(self, lang: str) -> Stage1ReleaseAccessibleChessAPI:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        engine = _FakeEngine()
        analysis = AnalysisService(lambda: engine, owns_engine=False)
        continuous = ContinuousAnalysisService(analysis)
        self.addCleanup(continuous.close)
        return Stage1ReleaseAccessibleChessAPI(
            lang=lang,
            keymap_path=Path(self._tmp.name) / "keymap.json",
            continuous_analysis=continuous,
        )

    def _assert_no_developer_migration_copy(self, payload: dict[str, object]) -> None:
        visible = " ".join(
            str(payload.get(key, ""))
            for key in ("engineStatus", "announcement")
        ).casefold()
        for forbidden in self._FORBIDDEN_USER_COPY:
            self.assertNotIn(forbidden.casefold(), visible)

    def test_shipping_uk_engine_toggle_reports_only_user_state(self) -> None:
        api = self._api("uk")

        enabled = api.toggle_engine()

        self.assertTrue(enabled["ok"])
        self.assertTrue(enabled["engineEnabled"])
        self.assertEqual(enabled["engineStatus"], "Stockfish увімкнено.")
        self.assertEqual(enabled["announcement"], "Аналіз Stockfish увімкнено.")
        self._assert_no_developer_migration_copy(enabled)

        disabled = api.toggle_engine()
        self.assertTrue(disabled["ok"])
        self.assertFalse(disabled["engineEnabled"])
        self.assertEqual(disabled["engineStatus"], "Stockfish вимкнено.")
        self.assertEqual(disabled["announcement"], "Аналіз Stockfish вимкнено.")
        self._assert_no_developer_migration_copy(disabled)

    def test_shipping_en_engine_toggle_reports_only_user_state(self) -> None:
        api = self._api("en")

        enabled = api.toggle_engine()

        self.assertTrue(enabled["ok"])
        self.assertTrue(enabled["engineEnabled"])
        self.assertEqual(enabled["engineStatus"], "Stockfish enabled.")
        self.assertEqual(enabled["announcement"], "Stockfish analysis enabled.")
        self._assert_no_developer_migration_copy(enabled)

        disabled = api.toggle_engine()
        self.assertTrue(disabled["ok"])
        self.assertFalse(disabled["engineEnabled"])
        self.assertEqual(disabled["engineStatus"], "Stockfish disabled.")
        self.assertEqual(disabled["announcement"], "Stockfish analysis disabled.")
        self._assert_no_developer_migration_copy(disabled)


if __name__ == "__main__":
    unittest.main()
