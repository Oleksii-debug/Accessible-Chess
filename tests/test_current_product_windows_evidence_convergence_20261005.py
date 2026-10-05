from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / ".github" / "workflows" / "current-product-windows-evidence-convergence.yml"
ONECLICK = ROOT / ".github" / "workflows" / "p0-user-oneclick-portable-launcher.yml"
LAUNCH_REPORT = ROOT / ".github" / "workflows" / "portable-launch-report-reparse-safety.yml"


class CurrentProductWindowsEvidenceConvergenceTests(unittest.TestCase):
    def test_gate_is_dual_os_exact_head_and_fail_closed(self) -> None:
        text = GATE.read_text(encoding="utf-8")
        self.assertIn("ubuntu-22.04", text)
        self.assertIn("windows-2025", text)
        self.assertIn("WINDOWS_EVIDENCE_SUPERSEDED", text)
        self.assertIn('fetch_exact "$PRODUCT_REF" "$PRODUCT_HEAD" WINDOWS_EVIDENCE_PRODUCT', text)
        self.assertIn("printf '%s_MOVED expected=%s live=%s", text)
        self.assertIn("INITIAL_PRODUCT_HEAD: 08e7641854a45b1435ea87eb461d10472058dc20", text)
        self.assertIn("PRODUCT_HEAD: 8f78c4c88890f07f974b5d552fda7e274beadc50", text)
        self.assertIn('test "$(git show -s --format=%P "$INITIAL_CONVERGENCE_MERGE")" = "$INITIAL_PRODUCT_HEAD $ONECLICK_HEAD $LAUNCH_REPORT_HEAD"', text)
        self.assertIn('git merge-base --is-ancestor "$INITIAL_CONVERGENCE_MERGE" HEAD', text)
        self.assertIn('test "$(git show -s --format=%P "$PRODUCT_RECONVERGENCE_MERGE")" = "$PRE_PRODUCT_RECONVERGENCE $PRODUCT_HEAD"', text)
        self.assertIn('git merge-base --is-ancestor "$PRODUCT_RECONVERGENCE_MERGE" HEAD', text)
        self.assertNotIn("continue-on-error:", text)

    def test_oneclick_exact_head_guard_is_integrated(self) -> None:
        text = ONECLICK.read_text(encoding="utf-8")
        self.assertIn("P0_ONECLICK_SUPERSEDED", text)
        self.assertIn("github.event.pull_request.head.sha || github.sha", text)

    def test_launch_report_keeps_focused_mode_and_adds_current_product_mode(self) -> None:
        text = LAUNCH_REPORT.read_text(encoding="utf-8")
        self.assertIn("PRODUCT_BASE: 59486e2c9eff903e416d59a0e7c349c22ee2111d", text)
        self.assertIn("CURRENT_PRODUCT_HEAD: 8f78c4c88890f07f974b5d552fda7e274beadc50", text)
        self.assertIn("PORTABLE_LAUNCH_REPORT_PRODUCT_MOVED", text)
        self.assertIn("INITIAL_CONVERGENCE_MERGE: 5a02ace57c693c893007f4509a93ad15001f0c77", text)
        self.assertIn("PRODUCT_RECONVERGENCE_MERGE: 43bf457011f77f04b885b39eeb49d6cf20066af3", text)
        self.assertIn("CURRENT_REPORT_PATHS_BLOB: fafc8696a846a1b9c96a8ce89a76ce82593fd582", text)
        self.assertNotIn("continue-on-error:", text)

    def test_gate_runs_packaging_privacy_and_whole_product_smoke(self) -> None:
        text = GATE.read_text(encoding="utf-8")
        for token in (
            "tests.test_p0_oneclick_exact_head_concurrency",
            "tests.test_portable_launch_report_reparse_concurrency",
            "tests.test_report_paths",
            "tests.test_portable_launcher_contract",
            "tests.test_version2_portable_package",
            "tests.test_pgn_service",
            "tests.test_pgn_conversion",
            "tests.test_pgn_conversion_windows",
            "tests.test_pgn_conversion_native_windows",
            "python -m acs.selftest",
            "python run_accessible_chess.py --diagnostic",
        ):
            with self.subTest(token=token):
                self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
