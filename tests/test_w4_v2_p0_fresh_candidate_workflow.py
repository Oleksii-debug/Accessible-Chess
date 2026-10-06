from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "w4-v2-p0-fresh-windows-candidate.yml"
UPLOAD_ARTIFACT_V462 = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"


class W4V2P0FreshCandidateWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_is_manual_single_candidate_wip(self) -> None:
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("owner_final_candidate_approved:", self.text)
        self.assertIn("default: false", self.text)
        self.assertIn("type: boolean", self.text)
        self.assertIn("OWNER_FINAL_CANDIDATE_APPROVAL_REQUIRED", self.text)
        self.assertIn("product_sha:", self.text)
        self.assertIn("sound_pack_url:", self.text)
        self.assertIn("sound_pack_sha256:", self.text)
        self.assertGreaterEqual(self.text.count("required: true"), 3)
        self.assertIn("group: w4-v2-p0-fresh-windows-candidate", self.text)
        self.assertIn("cancel-in-progress: false", self.text)
        self.assertNotIn("schedule:", self.text)

    def test_owner_approval_gate_precedes_build_sound_download_and_artifact_upload(self) -> None:
        approval = self.text.index("OWNER_FINAL_CANDIDATE_APPROVAL_REQUIRED")
        build = self.text.index("Build standalone AccessibleChess.exe")
        sound = self.text.index("Materialize exact user-supplied 330-WAV sound pack")
        upload = self.text.index(UPLOAD_ARTIFACT_V462)
        self.assertLess(approval, build)
        self.assertLess(approval, sound)
        self.assertLess(approval, upload)

    def test_dispatch_ref_uses_live_registered_exact_product_apex(self) -> None:
        self.assertIn('WORKFLOW_REGISTRATION_BRANCH: ${{ github.event.repository.default_branch }}', self.text)
        self.assertIn('FULL_PRODUCT_BRANCH: ${{ github.event.repository.default_branch }}', self.text)
        self.assertIn('test "$GITHUB_REF_TYPE" = "branch"', self.text)
        self.assertIn('test "$GITHUB_REF_NAME" = "$WORKFLOW_REGISTRATION_BRANCH"', self.text)
        self.assertIn('workflow_sha="$(git rev-parse HEAD)"', self.text)
        self.assertIn('git fetch --no-tags origin "$WORKFLOW_REGISTRATION_BRANCH" "$FULL_PRODUCT_BRANCH"', self.text)
        self.assertIn('workflow_live="$(git rev-parse "origin/$WORKFLOW_REGISTRATION_BRANCH")"', self.text)
        self.assertIn('test "$workflow_sha" = "$workflow_live"', self.text)
        self.assertIn('test "$requested" = "$workflow_sha"', self.text)
        self.assertIn("W4_WORKFLOW_REGISTRATION_IDENTITY=PASS", self.text)
        self.assertIn("W4_WORKFLOW_PRODUCT_IDENTITY=PASS", self.text)
        self.assertIn("W4_EXACT_APEX_IDENTITY=PASS", self.text)

    def test_requested_sha_must_equal_live_default_branch_release_apex(self) -> None:
        self.assertIn('FULL_PRODUCT_BRANCH: ${{ github.event.repository.default_branch }}', self.text)
        self.assertIn('git fetch --no-tags origin "$WORKFLOW_REGISTRATION_BRANCH" "$FULL_PRODUCT_BRANCH"', self.text)
        self.assertIn('live="$(git rev-parse "origin/$FULL_PRODUCT_BRANCH")"', self.text)
        self.assertIn('test "$requested" = "$live"', self.text)
        self.assertIn('test "$requested" = "$workflow_sha"', self.text)
        self.assertIn("product_sha must be one exact 40-hex commit", self.text)

    def test_candidate_requires_exact_user_sound_pack_and_never_generates_fallback_tones(self) -> None:
        self.assertIn("sound_pack_url:", self.text)
        self.assertIn("sound_pack_sha256:", self.text)
        self.assertIn("USER_SOUND_WAV_COUNT: '330'", self.text)
        self.assertIn(
            "USER_SOUND_INVENTORY_SHA256: 41f3223040e0720b2268e5c28f3ccec140a4f9d3386c12ffa7a82fc283a1f920",
            self.text,
        )
        self.assertIn("USER_SOUND_PACK_URL_MUST_BE_HTTPS", self.text)
        self.assertIn("USER_SOUND_PACK_SHA256_INVALID", self.text)
        self.assertIn("USER_SOUND_PACK_ZIP_SHA256_MISMATCH", self.text)
        self.assertIn(
            "scripts/build_user_sound_pack.py $archive release-inputs/sounds --expected-source-archive-sha256 $wanted",
            self.text,
        )
        self.assertNotIn("Expand-Archive -LiteralPath $archive -DestinationPath $source", self.text)
        self.assertIn("USER_SOUND_PACK_SOURCE_ZIP_SHA256_MISMATCH", self.text)
        self.assertIn("USER_SOUND_PACK_SOURCE_ZIP_SIZE_MISMATCH", self.text)
        self.assertIn("USER_SOUND_PACK_EXACT=PASS", self.text)
        self.assertIn("USER_SOUND_PACK_CATALOG_SEMANTICS=PASS", self.text)
        self.assertIn("USER_SOUND_PACK_MANIFEST_SEMANTICS_MISMATCH", self.text)
        self.assertIn("USER_SOUND_PACK_VARIANT_SEMANTICS_MISMATCH", self.text)
        self.assertIn("USER_SOUND_PACK_LAYER_SEMANTICS_MISMATCH", self.text)
        self.assertIn("USER_SOUND_PACK_NEWGAME_SEMANTICS_MISMATCH", self.text)
        for authority in (
            "DEFAULT_EVENT_FILES",
            "EVENT_VARIANTS",
            "NEW_GAME_DURATION_SECONDS_BY_VARIANT",
            "NEW_GAME_IMPACTS_BY_VARIANT",
            "SOUND_LAYERS",
        ):
            self.assertIn(authority, self.text)
        self.assertIn("USER_SOUND_PACK_CANONICAL=PASS", self.text)
        self.assertIn("USER_SOUND_PACK_330_WAV=YES", self.text)
        self.assertIn("library/Board/MOVEHIT1.WAV", self.text)
        self.assertIn("library/Board/CAPHIT1.WAV", self.text)
        self.assertIn("USER_SOUND_PACK_MATE_VOICE_MISSING", self.text)
        self.assertIn("USER_SOUND_PACK_DRAW_VOICES_MISSING", self.text)
        self.assertIn("library/Russian/Notation/Mate.wav", self.text)
        self.assertIn("library/English/Draw.wav", self.text)
        self.assertIn("library/Russian/Draw.wav", self.text)
        self.assertIn("USER_SOUND_PACK_LOW_TIME_DEFAULT_INVALID", self.text)
        self.assertIn("USER_SOUND_PACK_LOW_TIME_ALTERNATIVE_MISSING", self.text)
        self.assertIn("library/Server/aooga.wav", self.text)
        self.assertIn("library/Server/ping.wav", self.text)
        self.assertNotIn("Build deterministic nine-event sound input with provenance", self.text)
        self.assertNotIn("generated-tone:v1", self.text)
        self.assertNotIn("frequencies = (330, 220, 660, 440", self.text)
        self.assertNotIn("deterministic tone generator", self.text)

    def test_sound_identity_is_retained_in_run_metadata_before_publication(self) -> None:
        validation = self.text.index("USER_SOUND_PACK_EXACT=PASS")
        metadata = self.text.index('"user_sound_pack_zip_sha256"')
        upload = self.text.index(UPLOAD_ARTIFACT_V462)
        self.assertLess(validation, metadata)
        self.assertLess(metadata, upload)
        self.assertIn('"user_sound_inventory_sha256"', self.text)
        self.assertIn('"user_sound_wav_count"', self.text)
        self.assertIn('os.environ["USER_SOUND_PACK_ZIP_SHA256"]', self.text)
        self.assertIn('os.environ["USER_SOUND_INVENTORY_SHA256"]', self.text)

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

    def test_packaged_diagnostic_requires_the_shipping_final_product_marker(self) -> None:
        self.assertIn("ACCESSIBLE CHESS V2 FINAL-PRODUCT COMPOSITION DIAGNOSTIC PASS", self.text)
        self.assertNotIn("ACCESSIBLE CHESS V2 PRODUCTION COMPOSITION DIAGNOSTIC PASS", self.text)

    def test_fresh_extraction_reproves_exact_user_sound_pack_inside_zip(self) -> None:
        extract = self.text.index("Expand-Archive")
        sound = self.text.index("FRESH_EXTRACTION_USER_SOUND_PACK=PASS")
        diagnostic = self.text.index("PACKAGED_EXE_P0F_DIAGNOSTIC=PASS")
        self.assertLess(extract, sound)
        self.assertLess(sound, diagnostic)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_COUNT_MISMATCH", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_DIGEST_MISMATCH", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_ARCHIVE_SHA256_MISMATCH", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_ARCHIVE_SIZE_MISSING", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_VARIANTS_INVALID", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_LAYERS_INVALID", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_MOVE_LAYER_INVALID", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_CAPTURE_LAYER_INVALID", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_NEWGAME_TIMING_INVALID", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_NEWGAME_VARIANTS_INVALID", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_NEWGAME_IMPACT_COUNT_INVALID", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_LIBRARY_MISMATCH", self.text)
        self.assertIn("inventory.json", self.text)
        self.assertIn("sound_root / 'manifest.json'", self.text)
        self.assertIn("SOUND_INVENTORY.json", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_AUDIT_NOTICE_MISMATCH", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_AUDIT_NOTICE=PASS", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_CATALOG_SEMANTICS=PASS", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_MANIFEST_SEMANTICS_MISMATCH", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_VARIANT_SEMANTICS_MISMATCH", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_LAYER_SEMANTICS_MISMATCH", self.text)
        self.assertIn("FRESH_EXTRACTION_USER_SOUND_NEWGAME_SEMANTICS_MISMATCH", self.text)
        self.assertIn("EXPECTED_SOURCE_INVENTORY_SHA256", self.text)
        self.assertIn("EXPECTED_SOURCE_WAV_COUNT", self.text)

    def test_fresh_extraction_precedes_packaged_machine_acceptance(self) -> None:
        extract = self.text.index("Expand-Archive")
        preflight = self.text.index("FRESH_EXTRACTION_PREFLIGHT=PASS")
        diagnostic = self.text.index("PACKAGED_EXE_P0F_DIAGNOSTIC=PASS")
        uia = self.text.index("FRESH_PACKAGED_UIA_BASELINE=PASS")
        p0 = self.text.index("& scripts\\run_p0_packaged_acceptance.ps1")
        upload = self.text.index(UPLOAD_ARTIFACT_V462)
        self.assertLess(extract, preflight)
        self.assertLess(preflight, diagnostic)
        self.assertLess(diagnostic, uia)
        self.assertLess(uia, p0)
        self.assertLess(p0, upload)

    def test_strict_uia_summary_is_retained_in_uploaded_p0_evidence(self) -> None:
        baseline = self.text.index("FRESH_PACKAGED_UIA_BASELINE=PASS")
        retained = self.text.index("FRESH_PACKAGED_UIA_EVIDENCE_RETAINED=PASS")
        combined = self.text.index("& scripts\\run_p0_packaged_acceptance.ps1")
        upload = self.text.index(UPLOAD_ARTIFACT_V462)
        self.assertLess(retained, baseline)
        self.assertLess(baseline, combined)
        self.assertLess(combined, upload)
        self.assertIn("candidate-output\\p0-evidence", self.text)
        self.assertIn("packaged-uia-strict-summary.json", self.text)

    def test_strict_uia_machine_acceptance_truth_is_explicit_before_retention(self) -> None:
        summary = self.text.index("$summary=Get-Content packaged-uia-strict-summary.json")
        annotate = self.text.index("$summary | Add-Member -NotePropertyName $name -NotePropertyValue $false -Force")
        persist = self.text.index("$summary | ConvertTo-Json -Depth 20 | Set-Content")
        retained = self.text.index("FRESH_PACKAGED_UIA_EVIDENCE_RETAINED=PASS")
        self.assertLess(summary, annotate)
        self.assertLess(annotate, persist)
        self.assertLess(persist, retained)
        self.assertIn("foreach($name in @('human_tested','nvda_verified'))", self.text)
        self.assertIn("$property.Value -isnot [bool]", self.text)
        self.assertIn("$property.Value -ne $false", self.text)
        self.assertIn("Strict UIA machine evidence must never claim or malformed-declare $name", self.text)

    def test_combined_p0_acceptance_uses_exact_sha_and_requires_both_evidence_files(self) -> None:
        self.assertIn("-ProductSha $env:PRODUCT_SHA", self.text)
        self.assertIn("packaged-v2-document-copy-summary.json", self.text)
        self.assertIn("packaged-p0g-hotkey-result-summary.json", self.text)
        self.assertIn("FRESH_PACKAGED_P0_ACCEPTANCE=PASS", self.text)

    def test_source_gate_covers_books_training_volume_and_canonical_resume(self) -> None:
        qualify = self.text.index("Qualify exact Product source before compilation")
        build = self.text.index("Build standalone AccessibleChess.exe")
        for test_name in (
            "tests.test_p0_packaged_document_copy_probe",
            "tests.test_verify_p0_packaged_document_copy_evidence",
            "tests.test_verify_p0_packaged_document_copy_evidence_hardening",
            "tests.test_verify_p0_packaged_document_copy_cli",
            "tests.test_p0_packaged_acceptance_orchestrator",
            "tests.test_verify_p0g_packaged_hotkey_result_evidence",
            "tests.test_verify_p0g_packaged_hotkey_result_cli",
            "tests.test_w3_p0f_starter_books_training_content",
            "tests.test_d08_training_canonical_resume",
            "tests.test_v2_book_epub_import",
            "tests.test_version2_epub_application_reachability",
            "tests.test_v2_native_dialog_language",
            "tests.test_version2_application",
            "tests.test_bookreader",
            "tests.test_bookdocument",
            "tests.test_v2_book_progress_store",
            "tests.test_v2_book_progress_store_production",
        ):
            position = self.text.index(test_name)
            self.assertLess(qualify, position)
            self.assertLess(position, build)
        self.assertIn("SOURCE_P0F_BOOKS_TRAINING_RESUME=PASS", self.text)
        self.assertIn("SOURCE_EPUB_APPLICATION_REACHABILITY=PASS", self.text)
        self.assertIn("SOURCE_EPUB_APPLICATION_REACHABILITY_FAILURE", self.text)

    def test_post_acceptance_relaunch_reproves_packaged_starter_before_publication(self) -> None:
        acceptance = self.text.index("FRESH_PACKAGED_P0_ACCEPTANCE=PASS")
        relaunch = self.text.index("FRESH_PACKAGED_POST_ACCEPTANCE_RELAUNCH=PASS")
        freshness = self.text.index("W4_PRE_UPLOAD_FRESHNESS=PASS")
        upload = self.text.index(UPLOAD_ARTIFACT_V462)
        self.assertLess(acceptance, relaunch)
        self.assertLess(relaunch, freshness)
        self.assertLess(freshness, upload)
        self.assertIn("PACKAGED_POST_ACCEPTANCE_RELAUNCH_FAILURE", self.text)
        self.assertIn("P0-F PACKAGED W2 LIBRARY DIAGNOSTIC PASS", self.text)
        self.assertIn("P0-F PACKAGED STARTER CONTENT DIAGNOSTIC PASS", self.text)

    def test_workflow_and_live_product_are_rechecked_immediately_before_publication(self) -> None:
        acceptance = self.text.index("FRESH_PACKAGED_P0_ACCEPTANCE=PASS")
        workflow_freshness = self.text.index("W4_PRE_UPLOAD_WORKFLOW_FRESHNESS=PASS")
        product_freshness = self.text.index("W4_PRE_UPLOAD_PRODUCT_FRESHNESS=PASS")
        freshness = self.text.index("W4_PRE_UPLOAD_FRESHNESS=PASS")
        upload = self.text.index(UPLOAD_ARTIFACT_V462)
        self.assertLess(acceptance, workflow_freshness)
        self.assertLess(workflow_freshness, product_freshness)
        self.assertLess(product_freshness, freshness)
        self.assertLess(freshness, upload)
        self.assertIn('git fetch --no-tags origin "$WORKFLOW_REGISTRATION_BRANCH" "$FULL_PRODUCT_BRANCH"', self.text)
        self.assertIn('workflow_live="$(git rev-parse "origin/$WORKFLOW_REGISTRATION_BRANCH")"', self.text)
        self.assertIn('workflow_sha="$(git rev-parse HEAD)"', self.text)
        self.assertIn('test "$workflow_sha" = "$workflow_live"', self.text)
        self.assertIn("STALE_W4_WORKFLOW", self.text)
        self.assertIn('live="$(git rev-parse "origin/$FULL_PRODUCT_BRANCH")"', self.text)
        self.assertIn('test "$PRODUCT_SHA" = "$live"', self.text)
        self.assertIn("STALE_W4_CANDIDATE", self.text)
        self.assertIn("STALE_W4_EXACT_APEX", self.text)
        self.assertIn("W4_PRE_UPLOAD_EXACT_APEX=PASS", self.text)


    def test_run_metadata_is_bound_after_freshness_and_before_publication(self) -> None:
        bind = self.text.index('echo "WORKFLOW_AUTHORITY_SHA=$workflow_sha" >> "$GITHUB_ENV"')
        freshness = self.text.index("W4_PRE_UPLOAD_FRESHNESS=PASS")
        metadata = self.text.index("Write run-bound candidate metadata after freshness proof")
        metadata_pass = self.text.index("W4_RUN_METADATA=PASS")
        upload = self.text.index(UPLOAD_ARTIFACT_V462)
        self.assertLess(bind, freshness)
        self.assertLess(freshness, metadata)
        self.assertLess(metadata, metadata_pass)
        self.assertLess(metadata_pass, upload)
        self.assertIn('"product_sha": product_sha', self.text)
        self.assertIn('"workflow_sha": workflow_sha', self.text)
        self.assertIn("RUN_METADATA_EXACT_APEX_MISMATCH", self.text)
        self.assertIn('"pre_upload_product_freshness": True', self.text)
        self.assertIn('"pre_upload_workflow_freshness": True', self.text)
        self.assertIn('"human_tested": False', self.text)
        self.assertIn('"nvda_verified": False', self.text)
        self.assertIn("w4-run-metadata.json", self.text)

    def test_candidate_checkpoint_precedes_artifact_publication(self) -> None:
        checkpoint = self.text.index("CANDIDATE_PRODUCT_SHA=")
        upload = self.text.index(UPLOAD_ARTIFACT_V462)
        self.assertLess(checkpoint, upload)
        self.assertLess(self.text.index("HUMAN_TESTED=NO"), upload)
        self.assertLess(self.text.index("NVDA_VERIFIED=NO"), upload)
        self.assertLess(self.text.index("USER_SOUND_PACK_330_WAV=YES"), upload)

    def test_successful_run_does_not_rebind_freshness_after_artifact_upload(self) -> None:
        upload = self.text.index(UPLOAD_ARTIFACT_V462)
        metadata = self.text.index("W4_RUN_METADATA=PASS")
        self.assertLess(metadata, upload)
        for forbidden in (
            "Recheck workflow and Full Product freshness after artifact upload",
            "STALE_W4_WORKFLOW_AFTER_UPLOAD",
            "STALE_W4_CANDIDATE_AFTER_UPLOAD",
            "W4_POST_UPLOAD_WORKFLOW_FRESHNESS=PASS",
            "W4_POST_UPLOAD_PRODUCT_FRESHNESS=PASS",
            "W4_POST_UPLOAD_FRESHNESS=PASS",
        ):
            self.assertNotIn(forbidden, self.text)
        self.assertIn("pre_upload_product_freshness", self.text)
        self.assertIn("pre_upload_workflow_freshness", self.text)

    def test_candidate_artifact_publication_is_exactly_pinned_and_contains_evidence(self) -> None:
        self.assertIn(UPLOAD_ARTIFACT_V462, self.text)
        self.assertNotIn("actions/upload-artifact@v4", self.text)
        upload = self.text.index(UPLOAD_ARTIFACT_V462)
        tail = self.text[upload:]
        self.assertIn("Accessible-Chess-V2-*-NVDA-test-candidate.zip", tail)
        self.assertIn("candidate-output/p0-evidence/*.json", tail)
        self.assertIn("if-no-files-found: error", tail)

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
