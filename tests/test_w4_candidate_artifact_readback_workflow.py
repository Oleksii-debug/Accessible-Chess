from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "w4-v2-p0-candidate-artifact-readback.yml"
FULL_PRODUCT_BRANCH = "work/full-product-teacher-education-reachability-20260911"
CORE_VERIFIER_BLOB = "50056ca618abc42450512d7cb0dbc3efa9442809"
CURRENT_VERIFIER_BLOB = "e3722b39f585e54bbc37fcc79ae595ce57d13f8a"


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

    def test_expected_product_and_sound_identity_are_bound_to_current_run_metadata(self) -> None:
        self.assertIn("Bind Product and sound identity to current completed-run metadata", self.text)
        self.assertIn("EXPECTED_WORKFLOW_SHA: ${{ github.event.workflow_run.head_sha }}", self.text)
        self.assertIn('target = "p0-evidence/w4-run-metadata.json"', self.text)
        self.assertIn('if workflow != expected_workflow:', self.text)
        for field in (
            '"user_sound_pack_zip_sha256"',
            '"user_sound_inventory_sha256"',
            '"user_sound_wav_count"',
        ):
            self.assertIn(field, self.text)
        self.assertIn("run metadata user sound archive SHA-256 is invalid", self.text)
        self.assertIn("run metadata user sound inventory SHA-256 is invalid", self.text)
        self.assertIn("run metadata user sound WAV count is invalid", self.text)
        self.assertIn('metadata.get("pre_upload_product_freshness") is not True', self.text)
        self.assertIn('metadata.get("pre_upload_workflow_freshness") is not True', self.text)
        self.assertIn('stream.write(f"product_sha={product}\\n")', self.text)
        self.assertNotIn('stream.write(f"config_sha={config_sha}\\n")', self.text)
        self.assertNotIn('config_sha = metadata.get("winforms_accessibility_config_sha256")', self.text)
        self.assertIn("W4_READBACK_RUN_SOUND_ZIP_SHA256=", self.text)
        self.assertIn("W4_READBACK_RUN_SOUND_INVENTORY_SHA256=", self.text)
        self.assertIn("W4_READBACK_RUN_SOUND_WAV_COUNT=", self.text)
        self.assertIn("W4_READBACK_RUN_IDENTITY=PASS", self.text)
        self.assertNotIn("FULL_PRODUCT_BRANCH:", self.text)

    def test_archive_product_identity_is_bound_to_completed_workflow_authority(self) -> None:
        self.assertIn('zipfile.ZipFile("candidate-artifact.zip", "r")', self.text)
        self.assertIn('if workflow != expected_workflow:', self.text)
        self.assertIn("EXPECTED_WORKFLOW_SHA: ${{ github.event.workflow_run.head_sha }}", self.text)
        self.assertNotIn('product_sha="$(unzip', self.text)
        self.assertNotIn("RELEASE_MANIFEST.json", self.text)

    def test_core_and_current_verifier_bytes_are_pinned_to_completed_workflow_authority(self) -> None:
        self.assertNotIn("W4_VERIFIER_COMMIT:", self.text)
        self.assertIn(f"W4_VERIFIER_BLOB_SHA: {CORE_VERIFIER_BLOB}", self.text)
        self.assertIn(f"W4_CURRENT_VERIFIER_BLOB_SHA: {CURRENT_VERIFIER_BLOB}", self.text)
        self.assertIn('workflow_sha="$(git rev-parse HEAD)"', self.text)
        self.assertIn('git worktree add --detach .w4-readback-source "$workflow_sha"', self.text)
        self.assertIn(
            'git -C .w4-readback-source rev-parse "HEAD:scripts/verify_w4_candidate_artifact.py"',
            self.text,
        )
        self.assertIn(
            'git -C .w4-readback-source rev-parse "HEAD:scripts/verify_w4_current_candidate_artifact.py"',
            self.text,
        )
        self.assertIn('test "$actual_blob" = "$W4_VERIFIER_BLOB_SHA"', self.text)
        self.assertIn('test "$current_blob" = "$W4_CURRENT_VERIFIER_BLOB_SHA"', self.text)
        self.assertIn("W4_READBACK_VERIFIER_AUTHORITY=PASS", self.text)

    def test_product_dependencies_and_config_identity_come_from_exact_product_source(self) -> None:
        self.assertIn('PRODUCT_SHA: ${{ steps.product.outputs.product_sha }}', self.text)
        self.assertNotIn('PRODUCT_CONFIG_SHA256: ${{ steps.product.outputs.config_sha }}', self.text)
        self.assertIn('git fetch --no-tags origin "$PRODUCT_SHA"', self.text)
        self.assertIn('git worktree add --detach .w4-product-source "$PRODUCT_SHA"', self.text)
        self.assertIn('test "$(git -C .w4-product-source rev-parse HEAD)" = "$PRODUCT_SHA"', self.text)
        for dependency in (
            "acs/acsdb.py",
            "acs/gametree.py",
            "acs/pgn_roundtrip.py",
            "acs/version2_package_preflight.py",
            "packaging/AccessibleChess.exe.config",
        ):
            self.assertIn(dependency, self.text)
        self.assertIn("sha256sum .w4-product-source/packaging/AccessibleChess.exe.config", self.text)
        self.assertIn('echo "PRODUCT_CONFIG_SHA256=$actual_config_sha" >> "$GITHUB_ENV"', self.text)
        self.assertIn("W4_READBACK_PRODUCT_CONFIG_AUTHORITY=PASS", self.text)
        self.assertIn("validate_winforms_accessibility_app_config", self.text)
        self.assertIn("W4_READBACK_PRODUCT_CONFIG_SEMANTICS_FAILURE", self.text)
        config_authority = self.text.index("W4_READBACK_PRODUCT_CONFIG_AUTHORITY=PASS")
        config_semantics = self.text.index("W4_READBACK_PRODUCT_CONFIG_SEMANTICS=PASS")
        verifier_copy = self.text.index(
            "cp .w4-readback-source/scripts/verify_w4_candidate_artifact.py "
            ".w4-product-source/scripts/verify_w4_candidate_artifact.py"
        )
        self.assertLess(config_authority, config_semantics)
        self.assertLess(config_semantics, verifier_copy)

    def test_both_verifiers_are_copied_and_hash_reproved_inside_exact_product(self) -> None:
        self.assertIn(
            "cp .w4-readback-source/scripts/verify_w4_candidate_artifact.py "
            ".w4-product-source/scripts/verify_w4_candidate_artifact.py",
            self.text,
        )
        self.assertIn(
            "cp .w4-readback-source/scripts/verify_w4_current_candidate_artifact.py "
            ".w4-product-source/scripts/verify_w4_current_candidate_artifact.py",
            self.text,
        )
        self.assertIn(
            'copied_blob="$(git hash-object .w4-product-source/scripts/verify_w4_candidate_artifact.py)"',
            self.text,
        )
        self.assertIn(
            'copied_current_blob="$(git hash-object .w4-product-source/scripts/verify_w4_current_candidate_artifact.py)"',
            self.text,
        )
        self.assertIn('test "$copied_blob" = "$W4_VERIFIER_BLOB_SHA"', self.text)
        self.assertIn('test "$copied_current_blob" = "$W4_CURRENT_VERIFIER_BLOB_SHA"', self.text)
        self.assertIn("W4_READBACK_PRODUCT_DEPENDENCY_GRAPH=PASS", self.text)

    def test_declared_verifier_blobs_match_exact_checked_out_scripts(self) -> None:
        core = subprocess.run(
            ["git", "rev-parse", "HEAD:scripts/verify_w4_candidate_artifact.py"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        current = subprocess.run(
            ["git", "rev-parse", "HEAD:scripts/verify_w4_current_candidate_artifact.py"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(CORE_VERIFIER_BLOB, core)
        self.assertEqual(CURRENT_VERIFIER_BLOB, current)
        self.assertIn(f"W4_VERIFIER_BLOB_SHA: {core}", self.text)
        self.assertIn(f"W4_CURRENT_VERIFIER_BLOB_SHA: {current}", self.text)

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

    def test_independent_current_verifier_receives_all_independent_identities(self) -> None:
        self.assertIn("python .w4-product-source/scripts/verify_w4_current_candidate_artifact.py", self.text)
        self.assertIn("--artifact candidate-artifact.zip", self.text)
        self.assertIn("--product-sha '${{ steps.product.outputs.product_sha }}'", self.text)
        self.assertIn("--workflow-sha '${{ github.event.workflow_run.head_sha }}'", self.text)
        self.assertIn('--product-config-sha256 "$PRODUCT_CONFIG_SHA256"', self.text)
        self.assertIn("W4_EXACT_RUN_ARTIFACT_READBACK=PASS", self.text)

    def test_readback_cannot_claim_human_or_nvda_acceptance(self) -> None:
        self.assertIn("HUMAN_TESTED=NO", self.text)
        self.assertIn("NVDA_VERIFIED=NO", self.text)
        self.assertNotIn("HUMAN_TESTED=YES", self.text)
        self.assertNotIn("NVDA_VERIFIED=YES", self.text)


if __name__ == "__main__":
    unittest.main()
