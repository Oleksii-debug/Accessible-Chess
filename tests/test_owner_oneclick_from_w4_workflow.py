from __future__ import annotations

from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/owner-oneclick-from-w4.yml")


class OwnerOneClickFromW4WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_finalizer_is_manual_owner_approved_and_exact_apex_bound(self) -> None:
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("owner_final_candidate_approved:", self.text)
        self.assertIn("OWNER_FINAL_CANDIDATE_APPROVAL_REQUIRED", self.text)
        self.assertIn('EXACT_PRODUCT_SHA=$env:GITHUB_SHA', self.text)
        self.assertIn("metadata.get('product_sha') != exact", self.text)
        self.assertIn("W4_PRODUCT_SHA_STALE", self.text)

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

    def test_artifact_upload_is_final_oneclick_only_after_machine_launch(self) -> None:
        launch_index = self.text.index("Launch exact root one-click bytes")
        upload_index = self.text.index("Upload exact owner one-click candidate")
        self.assertLess(launch_index, upload_index)
        self.assertIn("Accessible-Chess-ONECLICK-OWNER-FINAL.zip", self.text)
        self.assertIn("owner-final-receipt.json", self.text)
        self.assertIn("owner-oneclick/launch-report.txt", self.text)


if __name__ == "__main__":
    unittest.main()
