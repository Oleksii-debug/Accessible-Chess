from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "w4-v2-p0-candidate-artifact-readback.yml"
CANONICAL_BRANCH = "work/full-product-teacher-education-reachability-20260911"


class W4CandidateArtifactReadbackWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_trigger_is_exact_w4_candidate_workflow_on_canonical_branch_only(self) -> None:
        self.assertIn("workflows: ['W4 V2 P0 Fresh Windows Candidate']", self.text)
        self.assertIn(f"branches: [{CANONICAL_BRANCH}]", self.text)
        self.assertIn("types: [completed]", self.text)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", self.text)
        self.assertIn(f"github.event.workflow_run.head_branch == '{CANONICAL_BRANCH}'", self.text)

    def test_readback_has_read_only_repo_and_artifact_permissions(self) -> None:
        self.assertIn("actions: read", self.text)
        self.assertIn("contents: read", self.text)
        for forbidden in ("contents: write", "actions: write", "pull-requests: write", "id-token: write"):
            self.assertNotIn(forbidden, self.text)

    def test_exact_completed_run_head_is_checked_out_and_reproved(self) -> None:
        self.assertIn("ref: ${{ github.event.workflow_run.head_sha }}", self.text)
        self.assertIn('test "$actual" = "$EXPECTED_SHA"', self.text)
        self.assertIn(f"test \"$EXPECTED_BRANCH\" = '{CANONICAL_BRANCH}'", self.text)
        self.assertNotIn("test -f scripts/verify_w4_candidate_artifact.py", self.text)
        self.assertIn("W4_READBACK_PRODUCT_AUTHORITY", self.text)

    def test_verifier_is_materialized_from_pinned_w4_authority(self) -> None:
        self.assertIn("W4_VERIFIER_COMMIT: 04430fc55c5de0329463a71a3c9a2a3076c5b977", self.text)
        self.assertIn("W4_VERIFIER_BLOB_SHA: 877804819fdcd8b487023dc1174f90b994254427", self.text)
        self.assertIn('git fetch --no-tags origin "$W4_VERIFIER_COMMIT"', self.text)
        self.assertIn('actual_blob="$(git rev-parse "$W4_VERIFIER_COMMIT:scripts/verify_w4_candidate_artifact.py")"', self.text)
        self.assertIn('test "$actual_blob" = "$W4_VERIFIER_BLOB_SHA"', self.text)
        self.assertIn('git show "$W4_VERIFIER_COMMIT:scripts/verify_w4_candidate_artifact.py" > .w4-readback/verify_w4_candidate_artifact.py', self.text)

    def test_artifact_resolution_is_bound_to_exact_completed_run_id(self) -> None:
        self.assertIn("RUN_ID: ${{ github.event.workflow_run.id }}", self.text)
        self.assertIn("/actions/runs/{run}/artifacts?per_page=100", self.text)
        self.assertIn("Accessible-Chess-V2-NVDA-test-candidate", self.text)
        self.assertIn("expected exactly one non-expired candidate artifact", self.text)
        self.assertIn("candidate artifact API digest missing", self.text)

    def test_raw_outer_archive_is_downloaded_by_exact_artifact_id_with_bound(self) -> None:
        self.assertIn("ARTIFACT_ID: ${{ steps.artifact.outputs.artifact_id }}", self.text)
        self.assertIn("/actions/artifacts/{artifact}/zip", self.text)
        self.assertIn("candidate-artifact.zip", self.text)
        self.assertIn("max_outer_bytes=300 * 1024 * 1024", self.text)
        self.assertIn("candidate artifact exceeds 300 MiB download bound", self.text)
        self.assertIn("W4_RAW_ARTIFACT_DOWNLOAD_BYTES", self.text)
        self.assertIn("W4_RAW_ARTIFACT_DOWNLOAD=PASS", self.text)

    def test_expected_product_sha_comes_from_completed_run_without_preverifier_archive_parse(self) -> None:
        self.assertIn("Bind expected Product SHA from completed canonical workflow authority", self.text)
        self.assertIn("WORKFLOW_SHA: ${{ github.event.workflow_run.head_sha }}", self.text)
        self.assertIn("completed workflow head_sha is not exact 40-hex", self.text)
        self.assertIn("W4_READBACK_EXPECTED_PRODUCT_SHA", self.text)
        self.assertNotIn("zipfile.ZipFile('candidate-artifact.zip'", self.text)
        self.assertNotIn("RELEASE_MANIFEST.json", self.text)

    def test_long_build_staleness_is_rejected_after_artifact_publication(self) -> None:
        self.assertIn("Recheck live Full Product freshness after build and upload", self.text)
        self.assertIn(f"canonical='{CANONICAL_BRANCH}'", self.text)
        self.assertIn('git fetch --no-tags origin "$canonical"', self.text)
        self.assertIn('live="$(git rev-parse "origin/$canonical")"', self.text)
        self.assertIn('test "$PRODUCT_SHA" = "$live"', self.text)
        self.assertIn("STALE_W4_CANDIDATE", self.text)
        self.assertIn("W4_POST_BUILD_FRESHNESS=PASS", self.text)

    def test_independent_verifier_receives_api_outer_digest(self) -> None:
        self.assertIn("python .w4-readback/verify_w4_candidate_artifact.py", self.text)
        self.assertIn("--artifact candidate-artifact.zip", self.text)
        self.assertIn("--product-sha '${{ steps.product.outputs.product_sha }}'", self.text)
        self.assertIn("--outer-sha256 '${{ steps.artifact.outputs.artifact_digest }}'", self.text)
        self.assertIn("W4_EXACT_RUN_ARTIFACT_READBACK=PASS", self.text)

    def test_readback_cannot_claim_human_or_nvda_acceptance(self) -> None:
        self.assertIn("HUMAN_TESTED=NO", self.text)
        self.assertIn("NVDA_VERIFIED=NO", self.text)
        self.assertNotIn("HUMAN_TESTED=YES", self.text)
        self.assertNotIn("NVDA_VERIFIED=YES", self.text)


if __name__ == "__main__":
    unittest.main()
