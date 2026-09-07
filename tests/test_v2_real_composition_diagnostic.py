from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "run_accessible_chess_v2.py"


class Version2RealCompositionDiagnosticTests(unittest.TestCase):
    @staticmethod
    def _diagnostic_source() -> str:
        source = LAUNCHER.read_text(encoding="utf-8")
        marker = 'if "--diagnostic" in sys.argv:'
        if marker not in source or "\nelse:" not in source:
            raise AssertionError("V2 launcher diagnostic branch is missing")
        return source.split(marker, 1)[1].split("\nelse:", 1)[0]

    def test_diagnostic_uses_production_composition_factory_not_stage1_substitute(self) -> None:
        source = self._diagnostic_source()
        self.assertIn("create_version2_release_application", source)
        self.assertNotIn("Stage1ReleaseAccessibleChessAPI()", source)

    def test_diagnostic_exercises_v2_snapshot_and_closes_owned_resources(self) -> None:
        source = self._diagnostic_source()
        self.assertIn("v2_snapshot(", source)
        self.assertIn("application.shutdown(", source)
        self.assertIn("api.close_analysis(", source)
        self.assertIn("runtime.close(", source)

    def test_diagnostic_is_gui_free_and_uses_isolated_data_root(self) -> None:
        source = self._diagnostic_source()
        self.assertIn("TemporaryDirectory", source)
        self.assertIn("data_root=", source)
        self.assertNotIn("run_version2_release_window(", source)


if __name__ == "__main__":
    unittest.main()
