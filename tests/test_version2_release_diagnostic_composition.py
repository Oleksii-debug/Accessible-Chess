from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "run_accessible_chess_v2.py"


class Version2ReleaseDiagnosticCompositionTests(unittest.TestCase):
    @staticmethod
    def _diagnostic_source() -> str:
        source = LAUNCHER.read_text(encoding="utf-8")
        marker = 'if "--diagnostic" in sys.argv:'
        if marker not in source or "\nelse:" not in source:
            raise AssertionError("V2 launcher diagnostic branch is missing")
        return source.split(marker, 1)[1].split("\nelse:", 1)[0]

    def test_diagnostic_uses_the_production_v2_composition_root(self) -> None:
        diagnostic = self._diagnostic_source()
        self.assertIn("create_version2_release_application", diagnostic)
        self.assertNotIn("Stage1ReleaseAccessibleChessAPI()", diagnostic)
        self.assertIn("runtime_factory=", diagnostic)
        self.assertIn("data_root=", diagnostic)

    def test_diagnostic_exercises_v2_state_and_closes_owned_resources(self) -> None:
        diagnostic = self._diagnostic_source()
        self.assertIn("v2_snapshot(", diagnostic)
        self.assertIn("application.shutdown(", diagnostic)
        self.assertIn("api.close_analysis(", diagnostic)
        self.assertIn("runtime.close(", diagnostic)

    def test_diagnostic_keeps_human_nvda_acceptance_out_of_machine_evidence(self) -> None:
        diagnostic = self._diagnostic_source()
        self.assertIn("Human NVDA verification remains Oleksii-only", diagnostic)
        self.assertNotIn("NVDA_VERIFIED=YES", diagnostic)


if __name__ == "__main__":
    unittest.main()
