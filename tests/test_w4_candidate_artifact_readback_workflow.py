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
        self.assertIn("test -f scripts/verify_w4_candidate_artifact.py", self.text)

    def test_artifact_resolution_is_bound_to_exact_completed_run_id(self) -> None:
        self.assertIn("RUN_ID: ${{ github.event.workflow_run.id }}", self.text)
        self.assertIn("/actions/runs/{run}/artifacts?per_page=100", self.text)
        self.assertIn("Accessible-Chess-V2-NVDA-test-candidate", self.text)
        self.assertIn("expected exactly one non-expired candidate artifact", self.text)
        self.assertIn("candidate artifact API digest missing", self.text)

    def test_raw_outer_archive_is_downloaded_by_exact_artifact_id_and_bounded(self) -> None:
        self.assertIn("ARTIFACT_ID: ${{ steps.artifact.outputs.artifact_id }}", self.text)
        self.assertIn("/actions/artifacts/{artifact}/zip", self.text)
        self.assertIn("candidate-artifact.zip", self.text)
        self.assertIn("maximum=300 * 1024 * 1024", self.text)
        self.assertIn("total > maximum", self.text)
        self.assertIn("exceeds 300 MiB readback bound", self.text)
        self.assertIn("W4_RAW_ARTIFACT_DOWNLOAD=PASS", self.text)

    def test_expected_product_sha_comes_only_from_completed_run_authority(self) -> None:
        self.assertIn(
            "Bind expected Product SHA to completed canonical workflow authority",
            self.text,
        )
        self.assertIn("WORKFLOW_SHA: ${{ github.event.workflow_run.head_sha }}", self.text)
        self.assertIn('[[ "$WORKFLOW_SHA" =~ ^[0-9a-fA-F]{40}$ ]]', self.text)
        self.assertIn('product_sha="${WORKFLOW_SHA,,}"', self.text)
        self.assertIn('echo "product_sha=$product_sha" >> "$GITHUB_OUTPUT"', self.text)
        self.assertIn("W4_READBACK_EXACT_PRODUCT_WORKFLOW_BINDING=PASS", self.text)

    def test_no_candidate_zip_is_parsed_before_independent_verifier(self) -> None:
        verifier_step = self.text.index(
            "- name: Independently verify outer artifact, inner package, checksums, P0-F and P0 evidence"
        )
        before_verifier = self.text[:verifier_step]
        self.assertNotIn("zipfile.ZipFile", before_verifier)
        self.assertNotIn("outer.read(", before_verifier)
        self.assertNotIn("RELEASE_MANIFEST.json", before_verifier)
        self.assertNotIn("candidate filename Product prefix mismatches manifest", before_verifier)

    def test_long_build_staleness_is_rejected_after_artifact_publication(self) -> None:
        self.assertIn("Recheck live Full Product freshness after build and upload", self.text)
        self.assertIn(f"canonical='{CANONICAL_BRANCH}'", self.text)
        self.assertIn('git fetch --no-tags origin "$canonical"', self.text)
        self.assertIn('live="$(git rev-parse "origin/$canonical")"', self.text)
        self.assertIn('test "$PRODUCT_SHA" = "$live"', self.text)
        self.assertIn("STALE_W4_CANDIDATE", self.text)
        self.assertIn("W4_POST_BUILD_FRESHNESS=PASS", self.text)

    def test_independent_verifier_receives_api_outer_digest(self) -> None:
        self.assertIn("python scripts/verify_w4_candidate_artifact.py", self.text)
        self.assertIn("--artifact candidate-artifact.zip", self.text)
        self.assertIn("--outer-sha256 '${{ steps.artifact.outputs.artifact_digest }}'", self.text)
        self.assertIn("W4_EXACT_RUN_ARTIFACT_READBACK=PASS", self.text)

    def test_readback_cannot_claim_human_or_nvda_acceptance(self) -> None:
        self.assertIn("HUMAN_TESTED=NO", self.text)
        self.assertIn("NVDA_VERIFIED=NO", self.text)
        self.assertNotIn("HUMAN_TESTED=YES", self.text)
        self.assertNotIn("NVDA_VERIFIED=YES", self.text)


if __name__ == "__main__":
    unittest.main()
