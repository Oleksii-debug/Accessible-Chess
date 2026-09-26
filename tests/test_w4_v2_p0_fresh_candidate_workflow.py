from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "w4-v2-p0-fresh-windows-candidate.yml"


class W4V2P0FreshCandidateWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_is_manual_single_candidate_wip(self) -> None:
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("product_sha:", self.text)
        self.assertIn("required: true", self.text)
        self.assertIn("group: w4-v2-p0-fresh-windows-candidate", self.text)
        self.assertIn("cancel-in-progress: false", self.text)
        self.assertNotIn("schedule:", self.text)

    def test_requested_sha_must_equal_live_canonical_full_product_head(self) -> None:
        self.assertIn("FULL_PRODUCT_BRANCH: work/full-product-teacher-education-reachability-20260911", self.text)
        self.assertIn('git fetch --no-tags origin "$FULL_PRODUCT_BRANCH"', self.text)
        self.assertIn('live="$(git rev-parse "origin/$FULL_PRODUCT_BRANCH")"', self.text)
        self.assertIn('test "$requested" = "$live"', self.text)
        self.assertIn("product_sha must be one exact 40-hex commit", self.text)

    def test_build_reuses_qualified_nuitka_and_v2_release_authorities(self) -> None:
        self.assertIn("NUITKA_UPSTREAM_FIX_COMMIT: b7ea05bf570e0b6950de6db7c4c8e579e1b77d29", self.text)
        self.assertIn("python -m nuitka --standalone", self.text)
        self.assertIn("run_accessible_chess_v2.py", self.text)
        self.assertIn("prepare_version2_release_payload", self.text)
        self.assertIn("assemble_version2_package_tree", self.text)
        self.assertIn("write_version2_package_zip", self.text)
        self.assertIn("validate_version2_package_tree", self.text)

    def test_official_stockfish_is_hash_pinned(self) -> None:
        self.assertIn("official-stockfish/Stockfish/releases/download/sf_18/stockfish-windows-x86-64.zip", self.text)
        self.assertIn("STOCKFISH_SHA256: 40cc975817e7eee270b03f354810d20956df565420d320f6dd37d454dc81a139", self.text)
        self.assertIn("STOCKFISH_SHA256_MISMATCH", self.text)

    def test_p0f_bundle_is_materialized_into_prepared_product_before_package_assembly(self) -> None:
        build = self.text.index("tools/p0f_lawful_starter_bundle.py")
        inject = self.text.index("release-content' / 'w2-starter")
        assemble = self.text.index("assemble_version2_package_tree")
        self.assertLess(build, inject)
        self.assertLess(inject, assemble)
        for name in ("starter_uk.pgn", "stress_uk.pgn", "sample_library.acsdb", "manifest.json"):
            self.assertIn(name, self.text)

    def test_fresh_extraction_precedes_packaged_machine_acceptance(self) -> None:
        extract = self.text.index("Expand-Archive")
        preflight = self.text.index("FRESH_EXTRACTION_PREFLIGHT=PASS")
        diagnostic = self.text.index("PACKAGED_EXE_P0F_DIAGNOSTIC=PASS")
        uia = self.text.index("FRESH_PACKAGED_UIA_BASELINE=PASS")
        p0 = self.text.index("run_p0_packaged_acceptance.ps1")
        upload = self.text.index("actions/upload-artifact@v4")
        self.assertLess(extract, preflight)
        self.assertLess(preflight, diagnostic)
        self.assertLess(diagnostic, uia)
        self.assertLess(uia, p0)
        self.assertLess(p0, upload)

    def test_combined_p0_acceptance_uses_exact_sha_and_requires_both_evidence_files(self) -> None:
        self.assertIn("-ProductSha $env:PRODUCT_SHA", self.text)
        self.assertIn("packaged-v2-document-copy-summary.json", self.text)
        self.assertIn("packaged-p0g-hotkey-result-summary.json", self.text)
        self.assertIn("FRESH_PACKAGED_P0_ACCEPTANCE=PASS", self.text)

    def test_candidate_never_claims_human_or_nvda_acceptance(self) -> None:
        self.assertIn("HUMAN_TESTED=NO", self.text)
        self.assertIn("NVDA_VERIFIED=NO", self.text)
        self.assertNotRegex(self.text, re.compile(r"HUMAN_TESTED\s*=\s*YES", re.I))
        self.assertNotRegex(self.text, re.compile(r"NVDA_VERIFIED\s*=\s*YES", re.I))

    def test_artifact_is_nvda_test_candidate_not_final_release(self) -> None:
        self.assertIn("NVDA-test-candidate.zip", self.text)
        self.assertNotIn("FINAL_WINDOWS_ZIP=YES", self.text)
        self.assertIn("VERSION2_WINDOWS_ZIP=YES", self.text)


if __name__ == "__main__":
    unittest.main()
