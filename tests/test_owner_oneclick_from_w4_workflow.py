from __future__ import annotations

from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/owner-oneclick-from-w4.yml")
W4_WORKFLOW = Path(".github/workflows/w4-v2-p0-fresh-windows-candidate.yml")
CONTRACT_WORKFLOW = Path(".github/workflows/owner-oneclick-finalizer-contract.yml")


class OwnerOneClickFromW4WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.w4_text = W4_WORKFLOW.read_text(encoding="utf-8")
        cls.contract_text = CONTRACT_WORKFLOW.read_text(encoding="utf-8")

    def test_w4_producer_contract_matches_finalizer_artifact_topology(self) -> None:
        artifact_name = "Accessible-Chess-V2-NVDA-test-candidate"
        self.assertIn(f"name: {artifact_name}", self.w4_text)
        self.assertIn(f"name: {artifact_name}", self.text)
        self.assertGreaterEqual(
            self.contract_text.count(
                "'.github/workflows/w4-v2-p0-fresh-windows-candidate.yml'"
            ),
            2,
        )
        self.assertIn(
            'echo "CANDIDATE_FILE=Accessible-Chess-V2-${short}-NVDA-test-candidate.zip"',
            self.w4_text,
        )
        self.assertIn(
            "product-source/candidate-output/Accessible-Chess-V2-*-NVDA-test-candidate.zip",
            self.w4_text,
        )
        self.assertIn(
            "product-source/candidate-output/p0-evidence/*.json",
            self.w4_text,
        )
        self.assertIn(
            'Path("candidate-output/p0-evidence/w4-run-metadata.json")',
            self.w4_text,
        )
        self.assertIn(
            "root / 'p0-evidence' / 'w4-run-metadata.json'",
            self.text,
        )
        self.assertIn(
            "Accessible-Chess-V2-{exact[:7]}-NVDA-test-candidate.zip",
            self.text,
        )

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
        self.assertIn("metadata.get('workflow_sha') != validated_workflow", self.text)
        self.assertIn("W4_RUN_WORKFLOW_SHA_STALE", self.text)
        self.assertIn("W4_PRODUCT_SHA_STALE", self.text)
        self.assertIn("W4_WORKFLOW_SHA_STALE", self.text)

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
        self.assertIn("root / 'p0-evidence' / 'w4-run-metadata.json'", self.text)
        self.assertIn("Accessible-Chess-V2-{exact[:7]}-NVDA-test-candidate.zip", self.text)
        self.assertIn("W4_METADATA_LOCATION_INVALID", self.text)
        self.assertIn("W4_CANDIDATE_LOCATION_INVALID", self.text)
        self.assertLess(
            self.text.index("if metadata_files[0] != expected_metadata"),
            self.text.index("label='W4 run metadata'"),
        )
        self.assertLess(
            self.text.index("if candidate != expected_candidate"),
            self.text.index("label='W4 candidate ZIP'"),
        )

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

    def test_w4_zip_rejects_encrypted_and_special_members_before_materialization(self) -> None:
        for token in (
            "info.flag_bits & 0x1",
            "W4_ZIP_ENCRYPTED_MEMBER_FORBIDDEN",
            "unix_type not in {0, 0o040000}",
            "unix_type not in {0, 0o100000}",
            "W4_ZIP_SPECIAL_MEMBER_FORBIDDEN",
            "W4_ZIP_SYMLINK_FORBIDDEN",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

        encrypted = self.text.index("info.flag_bits & 0x1")
        special = self.text.index("unix_type not in {0, 0o100000}")
        materialize = self.text.index("source.open(info, 'r')")
        self.assertLess(encrypted, materialize)
        self.assertLess(special, materialize)

    def test_w4_run_provenance_uses_single_canonical_verifier_before_download(self) -> None:
        fetch_index = self.text.index("Fetch and authenticate exact W4 workflow run provenance")
        bind_index = self.text.index("Bind validated W4 workflow authority to final equal apex")
        download_index = self.text.index("Download exact W4 artifact by run ID")
        self.assertLess(fetch_index, bind_index)
        self.assertLess(bind_index, download_index)

        for token in (
            "id: w4_run_provenance",
            'gh api --method GET "repos/$env:GH_REPOSITORY/actions/runs/$env:W4_RUN_ID"',
            "scripts/verify_owner_w4_run_provenance.py",
            "--run-json $runJson",
            "--run-id $env:W4_RUN_ID",
            "--repository $env:GH_REPOSITORY",
            "--default-branch $env:RELEASE_BRANCH",
            "--workflow-path $env:W4_WORKFLOW_PATH",
            "--github-output $env:GITHUB_OUTPUT",
            "${{ steps.w4_run_provenance.outputs.workflow_sha }}",
            "W4_RUN_WORKFLOW_SHA_INVALID",
            "W4_RUN_WORKFLOW_SHA_STALE",
            "W4_RUN_WORKFLOW_SHA=$actual",
            "W4_RUN_PROVENANCE=PASS",
            "os.environ['W4_RUN_WORKFLOW_SHA']",
            "metadata.get('workflow_sha') != validated_workflow",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

        self.assertIn("actions: read", self.text)
        self.assertNotIn("urllib.request", self.text)
        self.assertNotIn("json.load(response)", self.text)
        self.assertNotIn("payload.get('path')", self.text)

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
            "INVALID_HTTPS_URL",
            "[System.Uri]::TryCreate",
            "$value -ne $value.Trim()",
            "$value -match '[\\x00-\\x1F\\x7F]'",
            "$uri.Scheme -cne 'https'",
            "$uri.UserInfo",
            "OWNER_EXTERNAL_BYTES_BOUND=PASS",
        ):
            self.assertIn(token, self.text)

        validation = self.text.index("INVALID_HTTPS_URL")
        export = self.text.index('"OWNER_SEED_URL=$env:OWNER_SEED_URL_INPUT"')
        download = self.text.index("Download and bind exact private seed and owner DOCX bytes")
        self.assertLess(validation, export)
        self.assertLess(export, download)
        self.assertNotIn("MUST_BE_HTTPS", self.text)

    def test_owner_docx_names_use_win32_portable_authority_before_download(self) -> None:
        validation = self.text.index("Bind explicit owner inputs and exact product identity")
        download = self.text.index("Download and bind exact private seed and owner DOCX bytes")
        self.assertLess(validation, download)
        self.assertIn(
            "from scripts.build_owner_portable_candidate import _owner_docx_filename",
            self.text,
        )
        self.assertIn(
            "validated = tuple(_owner_docx_filename(name) for name in names)",
            self.text,
        )
        self.assertNotIn(
            "from acs.version2_portable_package import _portable_docx_name",
            self.text,
        )

    def test_private_seed_is_materialized_canonically_before_inner_reassembly(self) -> None:
        self.assertIn("materialize_owner_library_seed", self.text)
        self.assertIn("expected_source_count=6", self.text)
        self.assertIn("expected_game_count=3738", self.text)
        self.assertIn("assemble_version2_package_tree(", self.text)
        self.assertIn("OWNER_CANONICAL_INNER_WITH_PRIVATE_SEED=PASS", self.text)

    def test_machine_launch_uses_fresh_extraction_of_exact_uploaded_zip(self) -> None:
        extract = self.text.index("Fresh-extract and launch exact final ZIP bytes")
        freshness = self.text.index("Recheck live release apex immediately before publication")
        upload_recheck = self.text.index(
            "Recheck final ZIP bytes immediately before artifact upload"
        )
        upload = self.text.index("Upload exact owner one-click candidate and receipt")
        self.assertLess(extract, freshness)
        self.assertLess(freshness, upload_recheck)
        self.assertLess(upload_recheck, upload)

        for token in (
            "Expand-Archive -LiteralPath $archive -DestinationPath $extracted",
            "owner-oneclick-from-zip",
            "validate_owner_portable_candidate_tree(",
            "expected_seed_source_count=6",
            "expected_seed_game_count=3738",
            "_stable_digest(path, label=label)",
            "OWNER_FINAL_EXTRACTED_DOCX_SHA_MISMATCH",
            "OWNER_FINAL_ZIP_CHANGED_DURING_EXTRACTION",
            "OWNER_FINAL_ZIP_CHANGED_DURING_MACHINE_LAUNCH",
            "$root=(Resolve-Path $extracted).Path",
            "OWNER_FINAL_ZIP_FRESH_EXTRACTION=PASS",
            "OWNER_FINAL_ZIP_PRE_UPLOAD_BINDING=PASS",
            "owner-oneclick-from-zip/launch-report.txt",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

        self.assertNotIn("$root=(Resolve-Path 'owner-oneclick').Path", self.text)
        self.assertNotIn("owner-oneclick/launch-report.txt", self.text)

    def test_final_receipt_binds_authenticated_provenance_after_machine_smoke_and_freshness(self) -> None:
        launch = self.text.index("Fresh-extract and launch exact final ZIP bytes")
        freshness = self.text.index("Recheck live release apex immediately before publication")
        finalize = self.text.index("Finalize exact owner receipt provenance")
        zip_recheck = self.text.index("Recheck final ZIP bytes immediately before artifact upload")
        upload = self.text.index("Upload exact owner one-click candidate and receipt")
        self.assertLess(launch, freshness)
        self.assertLess(freshness, finalize)
        self.assertLess(finalize, zip_recheck)
        self.assertLess(zip_recheck, upload)

        for token in (
            "python -m scripts.finalize_owner_final_receipt",
            "--receipt owner-final-receipt.json",
            "--final-zip Accessible-Chess-ONECLICK-OWNER-FINAL.zip",
            "--product-sha $env:EXACT_PRODUCT_SHA",
            "--w4-candidate-sha256 $env:W4_CANDIDATE_SHA_INPUT",
            "--seed-archive-sha256 $env:OWNER_SEED_SHA_INPUT",
            "--w4-run-id $env:W4_RUN_ID",
            "${{ steps.w4_run_provenance.outputs.run_attempt }}",
            "${{ steps.w4_run_provenance.outputs.workflow_id }}",
            "${{ github.run_id }}",
            "${{ github.run_attempt }}",
            "--w4-workflow-sha $env:W4_RUN_WORKFLOW_SHA",
            "OWNER_FINAL_RECEIPT_PROVENANCE_BOUND=PASS",
            "OWNER_FINAL_RECEIPT_MACHINE_LAUNCH_MISSING",
            "OWNER_FINAL_RECEIPT_FRESHNESS_MISSING",
            "OWNER_FINAL_RECEIPT_OVERCLAIMS_ACCEPTANCE",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

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
        self.assertIn("WaitForExit(45000)", self.text)
        self.assertNotIn("WaitForExit(15000)", self.text)
        self.assertIn("STATUS: STARTUP_WINDOW_READY", self.text)
        self.assertIn("USER_WINDOW_PROVEN: YES", self.text)
        self.assertIn("USER_NVDA_PROVEN: NO", self.text)
        self.assertIn("STATUS: CHILD_RUNNING_AFTER_STARTUP_OBSERVATION", self.text)
        self.assertIn("OWNER_ROOT_LAUNCH_REPORT_LEGACY_LIVENESS_SUCCESS", self.text)
        self.assertIn(
            "$childPath=(Resolve-Path (Join-Path $root 'App\\AccessibleChess.exe')).Path",
            self.text,
        )
        self.assertIn("$baselineChildPids=@(", self.text)
        self.assertIn("try { $_.Path -eq $childPath } catch { $false }", self.text)
        self.assertIn("^CHILD_PROCESS_ID: [0-9]+$", self.text)
        self.assertIn("[uint32]::TryParse($rawChildPid,[ref]$reportedChildPid)", self.text)
        self.assertIn("$baselineChildPids -contains [int]$reportedChildPid", self.text)
        self.assertIn("Get-Process -Id $reportedChildPid -ErrorAction Stop", self.text)
        self.assertIn("$launchedChildPath=$launchedChild.Path", self.text)
        self.assertIn("$launchedChildPath -ne $childPath", self.text)
        self.assertIn("Stop-Process -Id $reportedChildPid -Force -ErrorAction Stop", self.text)
        baseline_index = self.text.index("$baselineChildPids=@(")
        launch_index = self.text.index(
            "$proc=Start-Process -FilePath $launcher -WorkingDirectory $root -PassThru"
        )
        cleanup_index = self.text.index(
            "Stop-Process -Id $reportedChildPid -Force -ErrorAction Stop"
        )
        self.assertLess(baseline_index, launch_index)
        self.assertLess(launch_index, cleanup_index)
        self.assertNotIn(
            "$candidatePath -eq $childPath -and $baselineChildPids -notcontains $candidateId",
            self.text,
        )
        self.assertNotIn(
            "Get-Process AccessibleChess -ErrorAction SilentlyContinue | Stop-Process -Force",
            self.text,
        )
        self.assertIn("HUMAN_TESTED=NO", self.text)
        self.assertIn("NVDA_VERIFIED=NO", self.text)
        self.assertNotIn("HUMAN_TESTED=YES", self.text)
        self.assertNotIn("NVDA_VERIFIED=YES", self.text)

    def test_artifact_upload_is_final_oneclick_only_after_machine_launch_and_freshness(self) -> None:
        launch_index = self.text.index("Fresh-extract and launch exact final ZIP bytes")
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
        self.assertIn("OWNER_FINALIZER_CHECKOUT_DRIFT_AFTER_UPLOAD", self.text)
        self.assertIn("OWNER_FINALIZER_STALE_AFTER_UPLOAD", self.text)
        self.assertIn("OWNER_FINALIZER_POST_UPLOAD_FRESHNESS=PASS", self.text)
        self.assertIn("Accessible-Chess-ONECLICK-OWNER-FINAL.zip", self.text)
        self.assertIn("owner-final-receipt.json", self.text)
        self.assertIn("owner-oneclick-from-zip/launch-report.txt", self.text)


if __name__ == "__main__":
    unittest.main()
