from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "w4-v2-p0-candidate-artifact-readback.yml"
FULL_PRODUCT_BRANCH = "work/full-product-teacher-education-reachability-20260911"


class W4CandidateArtifactReadbackWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_trigger_follows_dispatch_workflow_not_product_branch(self) -> None:
        self.assertIn("workflows: ['W4 V2 P0 Fresh Windows Candidate']", self.text)
        self.assertIn("types: [completed]", self.text)
        self.assertNotIn(f"branches: [{FULL_PRODUCT_BRANCH}]", self.text)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", self.text)
        self.assertIn("github.event.workflow_run.event == 'workflow_dispatch'", self.text)
        self.assertIn(
            "github.event.workflow_run.head_branch == github.event.repository.default_branch",
            self.text,
        )

    def test_readback_has_read_only_permissions(self) -> None:
        self.assertIn("actions: read", self.text)
        self.assertIn("contents: read", self.text)
        for forbidden in (
            "contents: write",
            "actions: write",
            "pull-requests: write",
            "id-token: write",
        ):
            self.assertNotIn(forbidden, self.text)

    def test_completed_run_head_is_workflow_authority_not_product_identity(self) -> None:
        self.assertIn("ref: ${{ github.event.workflow_run.head_sha }}", self.text)
        self.assertIn("EXPECTED_DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}", self.text)
        self.assertIn("EXPECTED_EVENT: ${{ github.event.workflow_run.event }}", self.text)
        self.assertIn("test \"$EXPECTED_EVENT\" = 'workflow_dispatch'", self.text)
        self.assertIn('test "$EXPECTED_BRANCH" = "$EXPECTED_DEFAULT_BRANCH"', self.text)
        self.assertIn('test "$actual" = "$EXPECTED_SHA"', self.text)
        self.assertIn("W4_READBACK_WORKFLOW_AUTHORITY", self.text)
        self.assertNotIn("W4_READBACK_PRODUCT_AUTHORITY", self.text)
        self.assertIn("EXPECTED_WORKFLOW_SHA: ${{ github.event.workflow_run.head_sha }}", self.text)

    def test_expected_product_sha_is_bound_to_completed_run_metadata(self) -> None:
        self.assertIn("Bind Product identity to the completed run metadata", self.text)
        self.assertIn("EXPECTED_WORKFLOW_SHA: ${{ github.event.workflow_run.head_sha }}", self.text)
        self.assertIn('target = "p0-evidence/w4-run-metadata.json"', self.text)
        self.assertIn('if workflow != expected_workflow:', self.text)
        self.assertIn('metadata.get("pre_upload_product_freshness") is not True', self.text)
        self.assertIn('metadata.get("pre_upload_workflow_freshness") is not True', self.text)
        self.assertIn('stream.write(f"product_sha={product}\\n")', self.text)
        self.assertIn("W4_READBACK_RUN_IDENTITY=PASS", self.text)
        self.assertNotIn("FULL_PRODUCT_BRANCH:", self.text)

    def test_archive_product_identity_is_bound_to_completed_workflow_authority(self) -> None:
        self.assertIn('zipfile.ZipFile("candidate-artifact.zip", "r")', self.text)
        self.assertIn('if workflow != expected_workflow:', self.text)
        self.assertIn("EXPECTED_WORKFLOW_SHA: ${{ github.event.workflow_run.head_sha }}", self.text)
        self.assertNotIn('product_sha="$(unzip', self.text)
        self.assertNotIn("RELEASE_MANIFEST.json", self.text)

    def test_verifier_dependency_graph_is_bound_to_completed_workflow_authority(self) -> None:
        self.assertNotIn("W4_VERIFIER_COMMIT:", self.text)
        self.assertIn(
            "W4_VERIFIER_BLOB_SHA: 45219a753090d822ec95c5766c8ad94586793da2",
            self.text,
        )
        self.assertIn('workflow_sha="$(git rev-parse HEAD)"', self.text)
        self.assertIn('git worktree add --detach .w4-readback-source "$workflow_sha"', self.text)
        self.assertIn('git -C .w4-readback-source rev-parse HEAD', self.text)
        self.assertIn(
            'git -C .w4-readback-source rev-parse "HEAD:scripts/verify_w4_candidate_artifact.py"',
            self.text,
        )
        self.assertIn('test "$actual_blob" = "$W4_VERIFIER_BLOB_SHA"', self.text)
        for dependency in (
            ".w4-readback-source/acs/acsdb.py",
            ".w4-readback-source/acs/gametree.py",
            ".w4-readback-source/acs/pgn_roundtrip.py",
        ):
            self.assertIn(dependency, self.text)
        self.assertIn("W4_READBACK_VERIFIER_WORKFLOW_SHA=$workflow_sha", self.text)
        self.assertIn("W4_READBACK_PINNED_DEPENDENCY_GRAPH=PASS", self.text)

    def test_declared_verifier_blob_matches_exact_checked_out_script(self) -> None:
        declared = "45219a753090d822ec95c5766c8ad94586793da2"
        actual = subprocess.run(
            ["git", "rev-parse", "HEAD:scripts/verify_w4_candidate_artifact.py"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(declared, actual)
        self.assertIn(f"W4_VERIFIER_BLOB_SHA: {declared}", self.text)

    def test_artifact_resolution_is_bound_to_exact_completed_run(self) -> None:
        self.assertIn("RUN_ID: ${{ github.event.workflow_run.id }}", self.text)
        self.assertIn("/actions/runs/{run}/artifacts?per_page=100", self.text)
        self.assertIn("Accessible-Chess-V2-NVDA-test-candidate", self.text)
        self.assertIn("expected exactly one non-expired candidate artifact", self.text)
        self.assertIn("candidate artifact API digest missing", self.text)

    def test_outer_archive_download_is_bounded_and_digest_bound(self) -> None:
        self.assertIn("ARTIFACT_ID: ${{ steps.artifact.outputs.artifact_id }}", self.text)
        self.assertIn("/actions/artifacts/{artifact}/zip", self.text)
        self.assertIn("max_outer_bytes=300 * 1024 * 1024", self.text)
        self.assertIn("candidate artifact exceeds 300 MiB download bound", self.text)
        self.assertIn("--outer-sha256 '${{ steps.artifact.outputs.artifact_digest }}'", self.text)

    def test_product_movement_after_upload_does_not_invalidate_completed_run(self) -> None:
        self.assertNotIn("Recheck live Full Product freshness after build and upload", self.text)
        self.assertNotIn('git fetch --no-tags origin "$FULL_PRODUCT_BRANCH"', self.text)
        self.assertNotIn("STALE_W4_CANDIDATE", self.text)
        self.assertIn("pre_upload_product_freshness", self.text)
        self.assertIn("pre_upload_workflow_freshness", self.text)
        self.assertIn("github.event.workflow_run.head_sha", self.text)

    def test_independent_verifier_receives_independently_bound_product_sha(self) -> None:
        self.assertIn("python .w4-readback-source/scripts/verify_w4_candidate_artifact.py", self.text)
        self.assertIn("--artifact candidate-artifact.zip", self.text)
        self.assertIn("--product-sha '${{ steps.product.outputs.product_sha }}'", self.text)
        self.assertIn("--workflow-sha '${{ github.event.workflow_run.head_sha }}'", self.text)
        self.assertIn("W4_EXACT_RUN_ARTIFACT_READBACK=PASS", self.text)

    def test_readback_cannot_claim_human_or_nvda_acceptance(self) -> None:
        self.assertIn("HUMAN_TESTED=NO", self.text)
        self.assertIn("NVDA_VERIFIED=NO", self.text)
        self.assertNotIn("HUMAN_TESTED=YES", self.text)
        self.assertNotIn("NVDA_VERIFIED=YES", self.text)


if __name__ == "__main__":
    unittest.main()
