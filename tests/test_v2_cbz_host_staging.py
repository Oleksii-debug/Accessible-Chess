from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from acs.cbv_extractor import ExternalCbvExtractorConfig
from acs.cbz_extractor import (
    CbzExtraction,
    CbzExtractCode,
    CbzExtractError,
    _WORKSPACE_MARKER,
    _make_private_workspace,
    recover_stale_cbz_workspaces,
)
from acs.cbz_host_staging import CbzHostStagingAuthority, CbzPasswordRequest
from acs.import_contract import fingerprint
from acs.version2_windows_cbz_recovery_host import (
    Version2WindowsCbzRecoveryPreflight,
    WindowsCbzRecoveryStatus,
)


class CbzHostStagingAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.recovery_root = self.root / "cbz-private"
        self.recovery_root.mkdir()
        self.source = self.root / "Archive.cbz"
        self.source.write_bytes(b"opaque encrypted test fixture")
        self.backend = self.root / "uncbv"
        self.backend.write_bytes(b"pinned external test backend")
        self.backend_sha256 = sha256(self.backend.read_bytes()).hexdigest()
        self.config = ExternalCbvExtractorConfig(
            self.backend,
            expected_backend_sha256=self.backend_sha256,
            timeout_seconds=3,
        )
        self.authority = CbzHostStagingAuthority(self.recovery_root)

    def _fake_extraction(self, _path, output, _config, password, **_kwargs):
        self.assertEqual(password, "test-secret")
        output = Path(output)
        (output / "db.cbh").write_bytes(b"header")
        return CbzExtraction(
            source=fingerprint(self.source),
            primary_path=output / "db.cbh",
            entry_count=1,
            extracted_bytes=6,
            backend_name="uncbv",
            backend_sha256=self.backend_sha256,
            decrypted_cbv_sha256="0" * 64,
        )

    def test_password_request_is_masked_path_free_nonpersistent_and_one_shot(self) -> None:
        requests: list[CbzPasswordRequest] = []

        def provider(request: CbzPasswordRequest) -> str:
            requests.append(request)
            return "test-secret"

        with mock.patch(
            "acs.cbz_host_staging.extract_cbz_external",
            side_effect=self._fake_extraction,
        ) as extractor:
            with self.authority.stage_for_canonical_import(
                self.source,
                self.config,
                provider,
            ) as result:
                self.assertTrue(result.primary_path.is_file())

        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request.format_name, "CBZ")
        self.assertTrue(request.masked_input_required)
        self.assertFalse(request.persistence_allowed)
        self.assertFalse(request.command_line_allowed)
        self.assertNotIn(str(self.source), repr(request))
        self.assertNotIn("test-secret", repr(request))
        self.assertEqual(extractor.call_count, 1)

    def test_all_published_proprietary_bytes_stay_inside_marker_qualified_outer_workspace(self) -> None:
        observed_outer: Path | None = None

        def extractor(_path, output, _config, _password, **_kwargs):
            nonlocal observed_outer
            output = Path(output)
            observed_outer = output.parent
            self.assertEqual(observed_outer.parent, self.recovery_root)
            self.assertTrue((observed_outer / _WORKSPACE_MARKER).is_file())
            self.assertTrue(observed_outer.name.startswith(".accessible-chess-cbz-"))
            (output / "db.cbh").write_bytes(b"private extracted bytes")
            return CbzExtraction(
                source=fingerprint(self.source),
                primary_path=output / "db.cbh",
                entry_count=1,
                extracted_bytes=23,
                backend_name="uncbv",
                backend_sha256=self.backend_sha256,
                decrypted_cbv_sha256="1" * 64,
            )

        with mock.patch(
            "acs.cbz_host_staging.extract_cbz_external",
            side_effect=extractor,
        ):
            with self.authority.stage_for_canonical_import(
                self.source,
                self.config,
                lambda _request: "test-secret",
            ) as result:
                self.assertTrue(result.primary_path.is_file())
                self.assertTrue(observed_outer is not None and observed_outer.exists())

        self.assertIsNotNone(observed_outer)
        self.assertFalse(observed_outer.exists())
        self.assertEqual(list(self.recovery_root.iterdir()), [])

    def test_cancel_before_password_entry_requests_no_secret_and_creates_no_workspace(self) -> None:
        cancelled = threading.Event()
        cancelled.set()
        provider = mock.Mock(return_value="test-secret")
        with self.assertRaises(CbzExtractError) as caught:
            with self.authority.stage_for_canonical_import(
                self.source,
                self.config,
                provider,
                cancel_event=cancelled,
            ):
                self.fail("cancelled CBZ stage must not yield")
        self.assertEqual(caught.exception.code, CbzExtractCode.CANCELLED)
        provider.assert_not_called()
        self.assertEqual(list(self.recovery_root.iterdir()), [])

    def test_cancelled_password_prompt_cleans_outer_workspace_without_backend(self) -> None:
        with mock.patch("acs.cbz_host_staging.extract_cbz_external") as extractor:
            with self.assertRaises(CbzExtractError) as caught:
                with self.authority.stage_for_canonical_import(
                    self.source,
                    self.config,
                    lambda _request: None,
                ):
                    self.fail("cancelled password prompt must not yield")
        self.assertEqual(caught.exception.code, CbzExtractCode.CANCELLED)
        extractor.assert_not_called()
        self.assertEqual(list(self.recovery_root.iterdir()), [])

    def test_password_provider_exception_is_redacted_and_workspace_removed(self) -> None:
        def provider(_request):
            raise RuntimeError("secret-provider-internal-path C:/private/password.txt")

        with mock.patch("acs.cbz_host_staging.extract_cbz_external") as extractor:
            with self.assertRaises(CbzExtractError) as caught:
                with self.authority.stage_for_canonical_import(
                    self.source,
                    self.config,
                    provider,
                ):
                    self.fail("provider failure must not yield")
        self.assertEqual(caught.exception.code, CbzExtractCode.PASSWORD_INVALID)
        rendered = str(caught.exception)
        self.assertNotIn("secret-provider", rendered)
        self.assertNotIn("C:/private", rendered)
        extractor.assert_not_called()
        self.assertEqual(list(self.recovery_root.iterdir()), [])

    def test_recovery_preflight_is_bound_to_exact_same_application_root(self) -> None:
        preflight = self.authority.recovery_preflight()
        self.assertIsInstance(preflight, Version2WindowsCbzRecoveryPreflight)
        with mock.patch(
            "acs.version2_windows_cbz_recovery_host.recover_stale_cbz_workspaces"
        ):
            # Constructor captures the public recoverer before this patch, so
            # this assertion is intentionally structural: the authority does
            # not derive or discover any second root.
            self.assertEqual(preflight._recovery_root, self.recovery_root)

    def test_application_restart_removes_stale_outer_stage_with_nested_published_bytes(self) -> None:
        outer = _make_private_workspace(self.recovery_root)
        published = outer / "published"
        published.mkdir()
        (published / "db.cbh").write_bytes(b"private post-decrypt bytes")

        marker_path = outer / _WORKSPACE_MARKER
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["owner_pid"] = 0xFFFFFFFE
        marker["created_unix_ns"] = time.time_ns() - 3_000_000_000
        marker_path.write_text(
            json.dumps(marker, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

        preflight = Version2WindowsCbzRecoveryPreflight(
            self.recovery_root,
            recoverer=lambda root: recover_stale_cbz_workspaces(
                root,
                min_age_seconds=1,
            ),
        )
        event = preflight.run_once()
        self.assertEqual(event.status, WindowsCbzRecoveryStatus.RECOVERED)
        self.assertEqual(event.removed, 1)
        self.assertFalse(outer.exists())
        self.assertEqual(list(self.recovery_root.iterdir()), [])

    def test_relative_and_symlink_roots_fail_closed(self) -> None:
        with self.assertRaises(CbzExtractError) as relative:
            CbzHostStagingAuthority(Path("relative-cbz-root"))
        self.assertEqual(relative.exception.code, CbzExtractCode.RECOVERY_ROOT_INVALID)

        target = self.root / "target-root"
        target.mkdir()
        symlink = self.root / "linked-root"
        try:
            symlink.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            return
        with self.assertRaises(CbzExtractError) as linked:
            CbzHostStagingAuthority(symlink)
        self.assertEqual(linked.exception.code, CbzExtractCode.RECOVERY_ROOT_INVALID)

    def test_underlying_extractor_escape_is_fail_closed_and_outer_stage_is_cleaned(self) -> None:
        escaped = self.root / "escaped.cbh"
        escaped.write_bytes(b"foreign")

        def extractor(_path, _output, _config, _password, **_kwargs):
            return CbzExtraction(
                source=fingerprint(self.source),
                primary_path=escaped,
                entry_count=1,
                extracted_bytes=7,
                backend_name="uncbv",
                backend_sha256=self.backend_sha256,
                decrypted_cbv_sha256="2" * 64,
            )

        with mock.patch(
            "acs.cbz_host_staging.extract_cbz_external",
            side_effect=extractor,
        ):
            with self.assertRaises(CbzExtractError) as caught:
                with self.authority.stage_for_canonical_import(
                    self.source,
                    self.config,
                    lambda _request: "test-secret",
                ):
                    self.fail("escaped stage must not yield")
        self.assertEqual(caught.exception.code, CbzExtractCode.OUTPUT_INVALID)
        self.assertEqual(escaped.read_bytes(), b"foreign")
        self.assertEqual(list(self.recovery_root.iterdir()), [])

    def test_machine_contract_keeps_cbz_and_2cbz_blocked(self) -> None:
        manifest = (
            Path(__file__).parents[1]
            / "docs"
            / "automation"
            / "V2_CBZ_HOST_STAGING_AUTHORITY.json"
        )
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload["format_status"]["cbz"], "BLOCKED")
        self.assertEqual(payload["format_status"]["2cbz"], "BLOCKED")
        self.assertFalse(payload["support_promotion_allowed"])
        self.assertTrue(payload["host_contract"]["single_explicit_recovery_root"])
        self.assertTrue(payload["host_contract"]["outer_marker_qualified_stage"])
        self.assertTrue(payload["host_contract"]["restart_recovery_reuses_same_root"])
        self.assertTrue(payload["password_contract"]["masked_input_required"])
        self.assertFalse(payload["password_contract"]["persistence_allowed"])
        self.assertFalse(payload["password_contract"]["command_line_allowed"])
        self.assertFalse(payload["password_contract"]["immutable_str_wipe_guaranteed"])


if __name__ == "__main__":
    unittest.main()
