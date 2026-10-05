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
        self.assertIn("CAS_PRODUCT_HEAD: ee3fe93aa379284d8af0672ae0cafb9961e88152", text)
        self.assertIn("PARENT_PRODUCT_HEAD: a59a46810fd189b1e8bf2c4efadda9dfebcc3af1", text)
        self.assertIn("PRESENTATION_PRODUCT_HEAD: b3ccef128ff2f885d9c71cc036ab630533158f62", text)
        self.assertIn("LIBRARY_PRODUCT_HEAD: 1ff26020e22008bfd93762b436d4f58bffb0b08f", text)
        self.assertIn("ROUTE_PRODUCT_HEAD: b3d94ebb5c26ef96a32d0309c761a31d4b032c95", text)
        self.assertIn("PRODUCT_HEAD: 492861b4e3ed2365ac63ddf925b182db7d3342e2", text)
        self.assertIn('test "$(git show -s --format=%P "$INITIAL_CONVERGENCE_MERGE")" = "$INITIAL_PRODUCT_HEAD $ONECLICK_HEAD $LAUNCH_REPORT_HEAD"', text)
        self.assertIn('git merge-base --is-ancestor "$INITIAL_CONVERGENCE_MERGE" HEAD', text)
        self.assertIn('test "$(git show -s --format=%P "$PRODUCT_RECONVERGENCE_MERGE")" = "$PRE_PRODUCT_RECONVERGENCE $CAS_PRODUCT_HEAD"', text)
        self.assertIn('git merge-base --is-ancestor "$PRODUCT_RECONVERGENCE_MERGE" HEAD', text)
        self.assertIn('test "$(git show -s --format=%P "$PARENT_RECONVERGENCE_MERGE")" = "$PRE_PARENT_RECONVERGENCE $PARENT_PRODUCT_HEAD"', text)
        self.assertIn('git merge-base --is-ancestor "$PARENT_RECONVERGENCE_MERGE" HEAD', text)
        self.assertIn('test "$(git show -s --format=%P "$PRESENTATION_RECONVERGENCE_MERGE")" = "$PRE_PRESENTATION_RECONVERGENCE $PRESENTATION_PRODUCT_HEAD"', text)
        self.assertIn('git merge-base --is-ancestor "$PRESENTATION_RECONVERGENCE_MERGE" HEAD', text)
        self.assertIn('test "$(git show -s --format=%P "$LIBRARY_RECONVERGENCE_MERGE")" = "$PRE_LIBRARY_RECONVERGENCE $LIBRARY_PRODUCT_HEAD"', text)
        self.assertIn('git merge-base --is-ancestor "$LIBRARY_RECONVERGENCE_MERGE" HEAD', text)
        self.assertIn("PRE_LATEST_PRODUCT_RECONVERGENCE: 455d48d2e964158041320b5067556a0485ab7728", text)
        self.assertIn("LATEST_PRODUCT_RECONVERGENCE_MERGE: 5846c17a32613427b15621d9590fd09e2c529af8", text)
        self.assertIn('test "$(git show -s --format=%P "$LATEST_PRODUCT_RECONVERGENCE_MERGE")" = "$ROUTE_PRODUCT_HEAD $PRE_LATEST_PRODUCT_RECONVERGENCE"', text)
        self.assertIn("PRE_FOCUS_PRODUCT_RECONVERGENCE: 0569c17efa3b798fa11edb69549e0f380de02224", text)
        self.assertIn("FOCUS_PRODUCT_RECONVERGENCE_MERGE: d14081a181ae204f657123ae08a5aadc36256703", text)
        self.assertIn('test "$(git show -s --format=%P "$FOCUS_PRODUCT_RECONVERGENCE_MERGE")" = "$PRE_FOCUS_PRODUCT_RECONVERGENCE $PRODUCT_HEAD"', text)
        self.assertNotIn("continue-on-error:", text)

    def test_oneclick_exact_head_guard_is_integrated(self) -> None:
        text = ONECLICK.read_text(encoding="utf-8")
        self.assertIn("P0_ONECLICK_SUPERSEDED", text)
        self.assertIn("github.event.pull_request.head.sha || github.sha", text)

    def test_launch_report_keeps_focused_mode_and_adds_current_product_mode(self) -> None:
        text = LAUNCH_REPORT.read_text(encoding="utf-8")
        self.assertIn("PRODUCT_BASE: 59486e2c9eff903e416d59a0e7c349c22ee2111d", text)
        self.assertIn("CAS_PRODUCT_HEAD: ee3fe93aa379284d8af0672ae0cafb9961e88152", text)
        self.assertIn("PARENT_PRODUCT_HEAD: a59a46810fd189b1e8bf2c4efadda9dfebcc3af1", text)
        self.assertIn("PRESENTATION_PRODUCT_HEAD: b3ccef128ff2f885d9c71cc036ab630533158f62", text)
        self.assertIn("LIBRARY_PRODUCT_HEAD: 1ff26020e22008bfd93762b436d4f58bffb0b08f", text)
        self.assertIn("ROUTE_PRODUCT_HEAD: b3d94ebb5c26ef96a32d0309c761a31d4b032c95", text)
        self.assertIn("CURRENT_PRODUCT_HEAD: 492861b4e3ed2365ac63ddf925b182db7d3342e2", text)
        self.assertIn("PORTABLE_LAUNCH_REPORT_PRODUCT_MOVED", text)
        self.assertIn("INITIAL_CONVERGENCE_MERGE: 5a02ace57c693c893007f4509a93ad15001f0c77", text)
        self.assertIn("PRODUCT_RECONVERGENCE_MERGE: 8816ce114b07d7ced39b8b661f12d61fce2b0e6a", text)
        self.assertIn("PARENT_RECONVERGENCE_MERGE: 4808f82eaecfea1b0b9689b4beb4facee446d32a", text)
        self.assertIn("PRESENTATION_RECONVERGENCE_MERGE: 9195b8b2ebea1ff68285896e4e4a5872eea89623", text)
        self.assertIn("LIBRARY_RECONVERGENCE_MERGE: 412f61c833042f4ac741f853a03f1eaab000e1cb", text)
        self.assertIn("LATEST_PRODUCT_RECONVERGENCE_MERGE: 5846c17a32613427b15621d9590fd09e2c529af8", text)
        self.assertIn("PRE_FOCUS_PRODUCT_RECONVERGENCE: 0569c17efa3b798fa11edb69549e0f380de02224", text)
        self.assertIn("FOCUS_PRODUCT_RECONVERGENCE_MERGE: d14081a181ae204f657123ae08a5aadc36256703", text)
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
            "tests.test_d07_library_export_service",
            "tests.test_v2_windows_library_export",
            "tests.test_dev1_library_webview_projection",
            "tests.test_dev1_full_product_webview_adapter",
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
