from __future__ import annotations

from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/owner-oneclick-from-w4.yml")


class OwnerOneClickFromW4WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_finalizer_is_manual_owner_approved_and_live_exact_apex_bound(self) -> None:
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("owner_final_candidate_approved:", self.text)
        self.assertIn("OWNER_FINAL_CANDIDATE_APPROVAL_REQUIRED", self.text)
        self.assertIn('RELEASE_BRANCH: ${{ github.event.repository.default_branch }}', self.text)
        self.assertIn('test "$GITHUB_REF_TYPE" = "branch"', self.text)
        self.assertIn('test "$GITHUB_REF_NAME" = "$RELEASE_BRANCH"', self.text)
        self.assertIn('test "$exact" = "$live"', self.text)
        self.assertIn('echo "EXACT_PRODUCT_SHA=$exact"', self.text)
        self.assertIn("OWNER_FINALIZER_LIVE_RELEASE_APEX=PASS", self.text)
        self.assertIn("metadata.get('product_sha') != exact", self.text)
        self.assertIn("metadata.get('workflow_sha') != exact", self.text)
        self.assertIn("W4_PRODUCT_SHA_STALE", self.text)
        self.assertIn("W4_WORKFLOW_SHA_STALE", self.text)

    def test_w4_run_id_uses_canonical_provenance_verifier_and_exact_sha_before_download(self) -> None:
        verify = self.text.index("Fetch and verify exact W4 workflow run authority")
        bind = self.text.index("Bind verified W4 run to exact release SHA")
        download = self.text.index("Download exact W4 artifact by run ID")
        self.assertLess(verify, bind)
        self.assertLess(bind, download)
        for token in (
            "actions: read",
            "scripts/verify_owner_w4_run_provenance.py",
            "--run-json w4-run.json",
            "--run-id $env:W4_RUN_ID",
            "--repository $env:REPOSITORY",
            "--default-branch $env:RELEASE_BRANCH",
            "--github-output $env:GITHUB_OUTPUT",
            "steps.w4_provenance.outputs.workflow_sha",
            "steps.w4_provenance.outputs.workflow_id",
            "steps.w4_provenance.outputs.run_attempt",
            "W4_RUN_PRODUCT_SHA_MISMATCH",
            'test "$W4_VERIFIED_SHA" = "$EXACT_PRODUCT_SHA"',
            "W4_RUN_AUTHORITY=PASS",
        ):
            self.assertIn(token, self.text)
        self.assertNotIn("$run.workflow_id", self.text)
        self.assertNotIn("$run.head_sha", self.text)

    def test_w4_metadata_is_strict_fresh_and_stably_read(self) -> None:
        for token in (
            "_stable_bytes",
            "maximum=64 * 1024",
            "object_pairs_hook=unique_pairs",
            "W4_METADATA_DUPLICATE_KEY",
            "W4_METADATA_CONTRACT_INVALID",
            "type(metadata.get('schema_version')) is not int",
            "W4_METADATA_SCHEMA_INVALID",
            "W4_METADATA_FRESHNESS_PROOF_INVALID",
            "type(metadata.get('user_sound_wav_count')) is not int",
            "EXPECTED_SOURCE_INVENTORY_SHA256",
            "W4_SOUND_INVENTORY_SHA_MISMATCH",
            "_stable_digest(",
            "maximum=2 * 1024 * 1024 * 1024",
            "W4_CANDIDATE_UNSTABLE",
        ):
            self.assertIn(token, self.text)
        self.assertNotIn("candidate.read_bytes()", self.text)
        self.assertNotIn("metadata_files[0].read_text", self.text)

    def test_w4_artifact_is_bound_by_run_identity_product_and_sha(self) -> None:
        self.assertIn("w4_run_id:", self.text)
        self.assertIn("w4_candidate_sha256:", self.text)
        self.assertIn("run-id: ${{ env.W4_RUN_ID }}", self.text)
        self.assertIn("Accessible-Chess-V2-NVDA-test-candidate", self.text)
        self.assertIn("W4_CANDIDATE_SHA_MISMATCH", self.text)
        self.assertIn("W4_EXACT_ARTIFACT_BINDING=PASS", self.text)
        self.assertIn("validate_version2_package_tree(", self.text)

    def test_w4_extraction_reuses_canonical_windows_path_authority(self) -> None:
        self.assertIn("Version2PackagePreflightError", self.text)
        self.assertIn("_relative_token", self.text)
        self.assertIn("token = _relative_token(token, label='W4 ZIP member')", self.text)
        self.assertIn("W4_ZIP_MEMBER_PATH_INVALID", self.text)
        for unsafe in ("C:evil", "file:stream", "CON", "name.", "name "):
            with self.subTest(unsafe=unsafe):
                from acs.version2_package_preflight import Version2PackagePreflightError, _relative_token
                with self.assertRaises(Version2PackagePreflightError):
                    _relative_token(unsafe, label="W4 ZIP member")

    def test_owner_external_inputs_are_explicit_https_and_sha_bound(self) -> None:
        for token in (
            "owner_seed_url:",
            "owner_seed_sha256:",
            "first_docx_url:",
            "first_docx_name:",
            "first_docx_sha256:",
            "second_docx_url:",
            "second_docx_name:",
            "second_docx_sha256:",
            "sound_archive_sha256:",
            "MUST_BE_HTTPS",
            "OWNER_EXTERNAL_BYTES_BOUND=PASS",
        ):
            self.assertIn(token, self.text)

    def test_private_seed_is_materialized_canonically_before_inner_reassembly(self) -> None:
        self.assertIn("materialize_owner_library_seed", self.text)
        self.assertIn("expected_source_count=6", self.text)
        self.assertIn("expected_game_count=3738", self.text)
        self.assertIn("assemble_version2_package_tree(", self.text)
        self.assertIn("OWNER_CANONICAL_INNER_WITH_PRIVATE_SEED=PASS", self.text)

    def test_final_outer_package_uses_canonical_owner_gate(self) -> None:
        self.assertIn("scripts/build_owner_portable_candidate.py", self.text)
        self.assertIn("--seed-source-count 6", self.text)
        self.assertIn("--seed-game-count 3738", self.text)
        self.assertIn("--sound-archive-sha256", self.text)
        self.assertIn("OWNER_FINAL_SOUND_COUNT_INVALID", self.text)
        self.assertIn("OWNER_FINAL_LIBRARY_IDENTITY_INVALID", self.text)

    def test_final_receipt_retains_verified_w4_run_provenance(self) -> None:
        for token in (
            "w4_workflow_id",
            "w4_run_id",
            "w4_run_attempt",
            "w4_candidate_sha256",
            "W4_WORKFLOW_ID",
            "W4_RUN_ATTEMPT",
            "OWNER_FINAL_RECEIPT_PROVENANCE=PASS",
        ):
            self.assertIn(token, self.text)

    def test_real_root_launcher_bytes_are_machine_smoked_without_acceptance_overclaim(self) -> None:
        self.assertIn("Build native x64 root launcher without CRT", self.text)
        self.assertIn("packaging\\portable_launcher.c", self.text)
        self.assertIn("Start-Process -FilePath $launcher", self.text)
        self.assertIn("STATUS: CHILD_RUNNING_AFTER_STARTUP_OBSERVATION", self.text)
        self.assertIn("USER_NVDA_PROVEN: NO", self.text)
        self.assertIn("HUMAN_TESTED=NO", self.text)
        self.assertIn("NVDA_VERIFIED=NO", self.text)
        self.assertNotIn("HUMAN_TESTED=YES", self.text)
        self.assertNotIn("NVDA_VERIFIED=YES", self.text)

    def test_artifact_upload_is_between_pre_and_post_publication_freshness(self) -> None:
        launch_index = self.text.index("Launch exact root one-click bytes")
        freshness_index = self.text.index("Recheck live release apex immediately before publication")
        upload_index = self.text.index("Upload exact owner one-click candidate")
        post_upload_index = self.text.index(
            "Confirm published artifact still matches live release apex"
        )
        self.assertLess(launch_index, freshness_index)
        self.assertLess(freshness_index, upload_index)
        self.assertLess(upload_index, post_upload_index)
        self.assertIn("OWNER_FINALIZER_STALE_BEFORE_UPLOAD", self.text)
        self.assertIn("OWNER_FINALIZER_PRE_UPLOAD_FRESHNESS=PASS", self.text)
        self.assertIn("OWNER_FINALIZER_STALE_AFTER_UPLOAD", self.text)
        self.assertIn("OWNER_FINALIZER_POST_UPLOAD_FRESHNESS=PASS", self.text)
        self.assertIn("Accessible-Chess-ONECLICK-OWNER-FINAL.zip", self.text)
        self.assertIn("owner-final-receipt.json", self.text)
        self.assertIn("owner-oneclick/launch-report.txt", self.text)


if __name__ == "__main__":
    unittest.main()
