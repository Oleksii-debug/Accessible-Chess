from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "run_accessible_chess_v2.py"
COMPOSITION = ROOT / "acs" / "version2_release_app.py"


class Version2ReleaseDiagnosticCompositionTests(unittest.TestCase):
    @staticmethod
    def _diagnostic_source() -> str:
        source = LAUNCHER.read_text(encoding="utf-8")
        marker = 'if "--diagnostic" in sys.argv:'
        if marker not in source or "\nelse:" not in source:
            raise AssertionError("V2 launcher diagnostic branch is missing")
        return source.split(marker, 1)[1].split("\nelse:", 1)[0]

    def test_diagnostic_and_real_launcher_share_production_composition_root(self) -> None:
        diagnostic = self._diagnostic_source()
        composition = COMPOSITION.read_text(encoding="utf-8")
        self.assertIn("create_version2_release_application", diagnostic)
        self.assertNotIn("Stage1ReleaseAccessibleChessAPI()", diagnostic)
        self.assertIn("def main()", composition)
        self.assertIn("create_version2_release_application(defer_ui=True)", composition)

    def test_external_effects_are_replaced_only_through_existing_ports(self) -> None:
        diagnostic = self._diagnostic_source()
        self.assertIn("runtime_factory=", diagnostic)
        self.assertIn("sound_playback=", diagnostic)
        self.assertIn("data_root=", diagnostic)
        self.assertIn("copy_text=", diagnostic)
        self.assertNotIn("StockfishRuntime(", diagnostic)
        self.assertNotIn("WindowsSoundPlaybackAdapter(", diagnostic)

    def test_diagnostic_exercises_real_v2_library_projection(self) -> None:
        diagnostic = self._diagnostic_source()
        self.assertIn("v2_snapshot(", diagnostic)
        self.assertIn('v2_state.get("library")', diagnostic)

    def test_cleanup_is_confirmed_in_application_analysis_runtime_order(self) -> None:
        diagnostic = self._diagnostic_source()
        application = diagnostic.index("application.shutdown(")
        analysis = diagnostic.index("api.close_analysis(")
        runtime = diagnostic.index("runtime.close(")
        self.assertLess(application, analysis)
        self.assertLess(analysis, runtime)
        self.assertIn(
            'cleanup_order != ["application", "analysis", "runtime"]',
            diagnostic,
        )
        self.assertIn("or not runtime.closed", diagnostic)

    def test_machine_diagnostic_does_not_claim_candidate_or_human_nvda(self) -> None:
        diagnostic = self._diagnostic_source()
        self.assertIn("Human NVDA verification remains Oleksii-only", diagnostic)
        self.assertNotIn("NVDA_VERIFIED=YES", diagnostic)
        self.assertNotIn("RELEASE-CANDIDATE DIAGNOSTIC PASS", diagnostic)
        self.assertIn("PRODUCTION COMPOSITION DIAGNOSTIC PASS", diagnostic)


if __name__ == "__main__":
    unittest.main()
