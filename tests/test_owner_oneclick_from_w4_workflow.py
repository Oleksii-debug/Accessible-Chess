from __future__ import annotations

from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/owner-oneclick-from-w4.yml")


class OwnerOneClickFromW4WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_finalizer_separates_registered_workflow_and_exact_product_authorities(self) -> None:
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("owner_final_candidate_approved:", self.text)
        self.assertIn("OWNER_FINAL_CANDIDATE_APPROVAL_REQUIRED", self.text)
        self.assertIn(
            'WORKFLOW_REGISTRATION_BRANCH: ${{ github.event.repository.default_branch }}',
            self.text,
        )
        self.assertIn(
            "RELEASE_APEX_BRANCH: fix/owner-portable-qualification-snapshot-pin-20261004-sol56",
            self.text,
        )
        self.assertIn(
            "FULL_PRODUCT_BRANCH: work/full-product-teacher-education-reachability-20260911",
            self.text,
        )
        self.assertIn('test "$GITHUB_REF_NAME" = "$WORKFLOW_REGISTRATION_BRANCH"', self.text)
        self.assertIn('echo "FINALIZER_WORKFLOW_SHA=$workflow_sha"', self.text)
        self.assertIn('echo "EXACT_PRODUCT_SHA=$release_live"', self.text)
        self.assertIn("OWNER_FINALIZER_WORKFLOW_REGISTRATION=PASS", self.text)
        self.assertIn("OWNER_FINALIZER_LIVE_RELEASE_APEX=PASS", self.text)

    def test_product_checkout_occurs_after_registration_binding(self) -> None:
        bind = self.text.index("Bind live workflow authority and exact release-apex product")
        checkout = self.text.index("Checkout exact owner release product")
        prove = self.text.index("Prove exact owner release product checkout")
        setup = self.text.index("Setup exact Python")
        self.assertLess(bind, checkout)
        self.assertLess(checkout, prove)
        self.assertLess(prove, setup)
        self.assertIn("id: bind", self.text)
        self.assertIn('echo "product_sha=$release_live" >> "$GITHUB_OUTPUT"', self.text)
        self.assertIn('ref: ${{ steps.bind.outputs.product_sha }}', self.text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$EXACT_PRODUCT_SHA"', self.text)

    def test_release_apex_must_descend_from_live_full_product(self) -> None:
        proof = 'git merge-base --is-ancestor "$full_product_live" "$release_live"'
        self.assertEqual(self.text.count(proof), 2)
        self.assertIn("OWNER_FINALIZER_RELEASE_APEX_ANCESTRY_INVALID", self.text)
        self.assertIn("OWNER_FINALIZER_RELEASE_APEX_ANCESTRY_STALE", self.text)

    def test_w4_metadata_binds_distinct_product_and_workflow_sha(self) -> None:
        self.assertIn("metadata.get('product_sha') != exact", self.text)
        self.assertIn("metadata.get('workflow_sha') != workflow", self.text)
        self.assertIn("os.environ['EXACT_PRODUCT_SHA']", self.text)
        self.assertIn("os.environ['FINALIZER_WORKFLOW_SHA']", self.text)
        self.assertNotIn("metadata.get('workflow_sha') != exact", self.text)
        self.assertIn("W4_PRODUCT_SHA_STALE", self.text)
        self.assertIn("W4_WORKFLOW_SHA_STALE", self.text)

    def test_w4_run_id_is_bound_to_registered_successful_workflow_run(self) -> None:
        for token in (
            "Verify exact W4 workflow run authority",
            "actions/workflows/w4-v2-p0-fresh-windows-candidate.yml",
            "actions/runs/$env:W4_RUN_ID",
            "W4_RUN_WORKFLOW_ID_MISMATCH",
            "W4_RUN_EVENT_INVALID",
            "W4_RUN_NOT_SUCCESSFUL",
            "W4_RUN_BRANCH_MISMATCH",
            "W4_RUN_WORKFLOW_SHA_MISMATCH",
            "W4_RUN_AUTHORITY=PASS",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)
        verify = self.text.index("Verify exact W4 workflow run authority")
        download = self.text.index("Download exact W4 artifact by run ID")
        self.assertLess(verify, download)

    def test_w4_artifact_is_bound_by_run_identity_product_and_sha(self) -> None:
        self.assertIn("w4_run_id:", self.text)
        self.assertIn("w4_candidate_sha256:", self.text)
        self.assertIn("run-id: ${{ env.W4_RUN_ID }}", self.text)
        self.assertIn("Accessible-Chess-V2-NVDA-test-candidate", self.text)
        self.assertIn("W4_CANDIDATE_SHA_MISMATCH", self.text)
        self.assertIn("W4_EXACT_ARTIFACT_BINDING=PASS", self.text)
        self.assertIn("validate_version2_package_tree(", self.text)

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
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_private_seed_is_materialized_canonically_before_inner_reassembly(self) -> None:
        self.assertIn("materialize_owner_library_seed", self.text)
        self.assertIn("expected_source_count=6", self.text)
        self.assertIn("expected_game_count=3738", self.text)
        self.assertIn("assemble_version2_package_tree(", self.text)
        self.assertIn("OWNER_CANONICAL_INNER_WITH_PRIVATE_SEED=PASS", self.text)

    def test_final_outer_package_uses_snapshot_pinned_canonical_owner_gate(self) -> None:
        self.assertIn("scripts/build_owner_portable_candidate.py", self.text)
        self.assertIn("--seed-source-count 6", self.text)
        self.assertIn("--seed-game-count 3738", self.text)
        self.assertIn("--sound-archive-sha256", self.text)
        self.assertIn("OWNER_FINAL_SOUND_COUNT_INVALID", self.text)
        self.assertIn("OWNER_FINAL_LIBRARY_IDENTITY_INVALID", self.text)

    def test_preupload_freshness_rechecks_both_authorities(self) -> None:
        launch_index = self.text.index("Launch exact root one-click bytes")
        freshness_index = self.text.index(
            "Recheck workflow registration and release apex immediately before publication"
        )
        upload_index = self.text.index("Upload exact owner one-click candidate")
        self.assertLess(launch_index, freshness_index)
        self.assertLess(freshness_index, upload_index)
        self.assertIn("OWNER_FINALIZER_WORKFLOW_STALE_BEFORE_UPLOAD", self.text)
        self.assertIn("OWNER_FINALIZER_PRODUCT_STALE_BEFORE_UPLOAD", self.text)
        self.assertIn("OWNER_FINALIZER_PRE_UPLOAD_WORKFLOW_FRESHNESS=PASS", self.text)
        self.assertIn("OWNER_FINALIZER_PRE_UPLOAD_PRODUCT_FRESHNESS=PASS", self.text)
        self.assertIn("OWNER_FINALIZER_PRE_UPLOAD_FRESHNESS=PASS", self.text)

    def test_machine_launch_does_not_overclaim_human_or_nvda_acceptance(self) -> None:
        self.assertIn("Build native x64 root launcher without CRT", self.text)
        self.assertIn("packaging\\portable_launcher.c", self.text)
        self.assertIn("Start-Process -FilePath $launcher", self.text)
        self.assertIn("STATUS: CHILD_RUNNING_AFTER_STARTUP_OBSERVATION", self.text)
        self.assertIn("USER_NVDA_PROVEN: NO", self.text)
        self.assertIn("HUMAN_TESTED=NO", self.text)
        self.assertIn("NVDA_VERIFIED=NO", self.text)
        self.assertNotIn("HUMAN_TESTED=YES", self.text)
        self.assertNotIn("NVDA_VERIFIED=YES", self.text)
        self.assertIn("Accessible-Chess-ONECLICK-OWNER-FINAL.zip", self.text)
        self.assertIn("owner-final-receipt.json", self.text)
        self.assertIn("owner-oneclick/launch-report.txt", self.text)


if __name__ == "__main__":
    unittest.main()
