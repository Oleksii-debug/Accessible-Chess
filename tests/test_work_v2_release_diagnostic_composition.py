from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "run_accessible_chess_v2.py"


class Version2ReleaseDiagnosticCompositionEvidenceTests(unittest.TestCase):
    """Evidence only: the V2 diagnostic must exercise the production V2 composition.

    The launcher currently prints a release-candidate diagnostic PASS after
    constructing only the inherited Stage1 API and checking that V2 resource
    files exist.  That cannot prove the V2 application/Library/runtime
    composition.  Product repair remains owned by the runtime/release lane.
    """

    @staticmethod
    def _diagnostic_source() -> str:
        source = LAUNCHER.read_text(encoding="utf-8")
        marker = 'if "--diagnostic" in sys.argv:'
        if marker not in source or "\nelse:" not in source:
            raise AssertionError("V2 launcher diagnostic branch is missing")
        return source.split(marker, 1)[1].split("\nelse:", 1)[0]

    def test_v2_diagnostic_consumes_the_production_v2_composition_root(self) -> None:
        diagnostic = self._diagnostic_source()

        self.assertIn(
            "create_version2_release_application",
            diagnostic,
            "a V2 release-candidate diagnostic must instantiate the same production V2 composition root used by the launcher",
        )
        self.assertNotIn(
            "Stage1ReleaseAccessibleChessAPI()",
            diagnostic,
            "the V2 diagnostic must not substitute a standalone Stage1 API for the V2 application composition",
        )

    def test_v2_diagnostic_exercises_v2_state_and_closes_owned_resources(self) -> None:
        diagnostic = self._diagnostic_source()

        self.assertTrue(
            "v2_snapshot(" in diagnostic or "application.snapshot(" in diagnostic,
            "the diagnostic must exercise V2 application state rather than only checking resource filenames",
        )
        self.assertIn(
            "application.shutdown(",
            diagnostic,
            "a diagnostic-created V2 application must close its Library/import/application resources",
        )
        self.assertIn(
            "runtime.close(",
            diagnostic,
            "a diagnostic-created production engine runtime must be closed",
        )


if __name__ == "__main__":
    unittest.main()
