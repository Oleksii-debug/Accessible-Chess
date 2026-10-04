from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import textwrap
import os
import json
import io
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

    def test_w4_run_provenance_is_authenticated_before_download(self) -> None:
        provenance_index = self.text.index("Authenticate exact W4 workflow run provenance")
        download_index = self.text.index("Download exact W4 artifact by run ID")
        self.assertLess(provenance_index, download_index)

        for token in (
            "actions/runs/{run_id}",
            "W4_WORKFLOW_PATH: .github/workflows/w4-v2-p0-fresh-windows-candidate.yml",
            "payload.get('path') != workflow_path",
            "payload.get('event') != 'workflow_dispatch'",
            "payload.get('status') != 'completed'",
            "payload.get('conclusion') != 'success'",
            "payload.get('head_branch') != release_branch",
            "actual_sha != exact",
            "W4_RUN_WORKFLOW_PATH_INVALID",
            "W4_RUN_EVENT_INVALID",
            "W4_RUN_STATUS_INVALID",
            "W4_RUN_CONCLUSION_INVALID",
            "W4_RUN_HEAD_BRANCH_INVALID",
            "W4_RUN_HEAD_SHA_INVALID",
            "W4_RUN_REPOSITORY_INVALID",
            "W4_RUN_PROVENANCE=PASS",
        ):
            self.assertIn(token, self.text)

        self.assertIn("Authorization': f'Bearer {token}", self.text)
        self.assertIn("actions: read", self.text)

    def _w4_run_provenance_script(self) -> str:
        start = self.text.index("      - name: Authenticate exact W4 workflow run provenance")
        end = self.text.index("      - name: Download exact W4 artifact by run ID", start)
        step = self.text[start:end]
        begin_marker = "          @'\n"
        end_marker = "          '@ | python -\n"
        begin = step.index(begin_marker) + len(begin_marker)
        finish = step.index(end_marker, begin)
        return textwrap.dedent(step[begin:finish])

    def _run_provenance_script(self, payload: dict[str, object]) -> None:
        script = self._w4_run_provenance_script()
        environment = {
            "W4_RUN_ID": "123456",
            "EXACT_PRODUCT_SHA": "a" * 40,
            "RELEASE_BRANCH": "main",
            "GH_API_URL": "https://api.github.test",
            "GH_REPOSITORY": "Oleksii-debug/Accessible-Chess",
            "GH_TOKEN": "test-token",
            "W4_WORKFLOW_PATH": ".github/workflows/w4-v2-p0-fresh-windows-candidate.yml",
        }

        def fake_urlopen(*_args: object, **_kwargs: object) -> io.BytesIO:
            return io.BytesIO(json.dumps(payload).encode("utf-8"))

        with patch.dict(os.environ, environment, clear=False), patch(
            "urllib.request.urlopen", side_effect=fake_urlopen
        ):
            exec(compile(script, "<w4-run-provenance>", "exec"), {})

    def test_w4_run_provenance_embedded_python_is_executable(self) -> None:
        payload = {
            "id": 123456,
            "path": ".github/workflows/w4-v2-p0-fresh-windows-candidate.yml",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "head_branch": "main",
            "head_sha": "a" * 40,
            "repository": {"full_name": "Oleksii-debug/Accessible-Chess"},
        }
        self._run_provenance_script(payload)

    def test_w4_run_provenance_rejects_wrong_run_authority(self) -> None:
        canonical = {
            "id": 123456,
            "path": ".github/workflows/w4-v2-p0-fresh-windows-candidate.yml",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "head_branch": "main",
            "head_sha": "a" * 40,
            "repository": {"full_name": "Oleksii-debug/Accessible-Chess"},
        }
        cases = (
            ("id", 999999, "W4_RUN_ID_MISMATCH"),
            ("path", ".github/workflows/other.yml", "W4_RUN_WORKFLOW_PATH_INVALID"),
            ("event", "push", "W4_RUN_EVENT_INVALID"),
            ("status", "in_progress", "W4_RUN_STATUS_INVALID"),
            ("conclusion", "failure", "W4_RUN_CONCLUSION_INVALID"),
            ("head_branch", "other", "W4_RUN_HEAD_BRANCH_INVALID"),
            ("head_sha", "b" * 40, "W4_RUN_HEAD_SHA_INVALID"),
            ("repository", {"full_name": "other/repo"}, "W4_RUN_REPOSITORY_INVALID"),
        )
        for key, value, marker in cases:
            with self.subTest(key=key):
                payload = dict(canonical)
                payload[key] = value
                with self.assertRaisesRegex(SystemExit, marker):
                    self._run_provenance_script(payload)

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

    def test_artifact_upload_is_final_oneclick_only_after_machine_launch_and_freshness(self) -> None:
        launch_index = self.text.index("Launch exact root one-click bytes")
        freshness_index = self.text.index("Recheck live release apex immediately before publication")
        upload_index = self.text.index("Upload exact owner one-click candidate")
        self.assertLess(launch_index, freshness_index)
        self.assertLess(freshness_index, upload_index)
        self.assertIn("OWNER_FINALIZER_STALE_BEFORE_UPLOAD", self.text)
        self.assertIn("OWNER_FINALIZER_PRE_UPLOAD_FRESHNESS=PASS", self.text)
        self.assertIn("Accessible-Chess-ONECLICK-OWNER-FINAL.zip", self.text)
        self.assertIn("owner-final-receipt.json", self.text)
        self.assertIn("owner-oneclick/launch-report.txt", self.text)


if __name__ == "__main__":
    unittest.main()
