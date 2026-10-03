from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from acs.authenticode import (
    AuthenticodeStatus,
    WindowsAuthenticodeVerifier,
    require_trusted_authenticode,
)


class AuthenticodeVerifierTests(unittest.TestCase):
    def _target(self, directory: str) -> Path:
        target = Path(directory) / "Accessible Chess test.exe"
        target.write_bytes(b"not a real executable")
        return target

    @staticmethod
    def _runner(payload: object, *, returncode: int = 0):
        stdout = payload if isinstance(payload, str) else json.dumps(payload)

        def run(args, **kwargs):
            return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")

        return run

    def test_non_windows_is_explicitly_unavailable_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self._target(tmp)
            verifier = WindowsAuthenticodeVerifier()
            with mock.patch("acs.authenticode.sys.platform", "linux"):
                evidence = verifier.verify(target)
        self.assertEqual(evidence.status, AuthenticodeStatus.UNAVAILABLE)
        self.assertFalse(evidence.trusted)
        self.assertFalse(evidence.acceptable_for_release)

    def test_missing_target_is_error_without_invoking_provider(self) -> None:
        runner = mock.Mock(side_effect=AssertionError("runner must not execute"))
        evidence = WindowsAuthenticodeVerifier(runner=runner).verify("missing.exe")
        self.assertEqual(evidence.status, AuthenticodeStatus.ERROR)
        self.assertFalse(evidence.trusted)
        runner.assert_not_called()

    def test_symlink_target_is_error_without_invoking_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self._target(tmp)
            indirect = Path(tmp) / "candidate-link.exe"
            try:
                indirect.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {type(exc).__name__}")
            runner = mock.Mock(side_effect=AssertionError("runner must not execute"))
            with mock.patch("acs.authenticode.sys.platform", "win32"):
                evidence = WindowsAuthenticodeVerifier(runner=runner).verify(indirect)
        self.assertEqual(evidence.status, AuthenticodeStatus.ERROR)
        self.assertFalse(evidence.trusted)
        self.assertFalse(evidence.acceptable_for_release)
        runner.assert_not_called()

    def test_windows_reparse_attribute_is_error_without_invoking_provider(self) -> None:
        runner = mock.Mock(side_effect=AssertionError("runner must not execute"))
        reparse_info = mock.Mock(
            st_mode=stat.S_IFREG | 0o644,
            st_file_attributes=0x400,
        )
        with mock.patch.object(Path, "lstat", return_value=reparse_info):
            with mock.patch("acs.authenticode.sys.platform", "win32"):
                evidence = WindowsAuthenticodeVerifier(runner=runner).verify("candidate.exe")
        self.assertEqual(evidence.status, AuthenticodeStatus.ERROR)
        self.assertFalse(evidence.trusted)
        self.assertFalse(evidence.acceptable_for_release)
        runner.assert_not_called()

    def test_valid_windows_signature_is_release_acceptable(self) -> None:
        payload = {
            "Status": "Valid",
            "SignerSubject": "CN=Accessible Chess Release",
            "SignerThumbprint": "aa bb 01",
            "TimestampSubject": "CN=Timestamp Authority",
        }
        with tempfile.TemporaryDirectory() as tmp:
            target = self._target(tmp)
            with mock.patch("acs.authenticode.sys.platform", "win32"):
                evidence = WindowsAuthenticodeVerifier(
                    runner=self._runner(payload)
                ).verify(target)
        self.assertEqual(evidence.status, AuthenticodeStatus.VALID)
        self.assertTrue(evidence.trusted)
        self.assertTrue(evidence.acceptable_for_release)
        self.assertEqual(evidence.signer_thumbprint, "AABB01")
        self.assertEqual(evidence.signer_subject, "CN=Accessible Chess Release")
        self.assertEqual(evidence.timestamp_subject, "CN=Timestamp Authority")

    def test_unsigned_untrusted_and_hash_mismatch_all_fail_closed(self) -> None:
        cases = [
            ("NotSigned", AuthenticodeStatus.UNSIGNED),
            ("NotTrusted", AuthenticodeStatus.UNTRUSTED),
            ("HashMismatch", AuthenticodeStatus.INVALID),
            ("NotSupported", AuthenticodeStatus.INVALID),
            ("UnknownError", AuthenticodeStatus.ERROR),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            target = self._target(tmp)
            for provider_status, expected in cases:
                with self.subTest(provider_status=provider_status):
                    with mock.patch("acs.authenticode.sys.platform", "win32"):
                        evidence = WindowsAuthenticodeVerifier(
                            runner=self._runner({"Status": provider_status})
                        ).verify(target)
                    self.assertEqual(evidence.status, expected)
                    self.assertFalse(evidence.trusted)
                    self.assertFalse(evidence.acceptable_for_release)

    def test_provider_failure_and_malformed_json_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self._target(tmp)
            with mock.patch("acs.authenticode.sys.platform", "win32"):
                failed = WindowsAuthenticodeVerifier(
                    runner=self._runner({}, returncode=1)
                ).verify(target)
                malformed = WindowsAuthenticodeVerifier(
                    runner=self._runner("not-json")
                ).verify(target)
        self.assertEqual(failed.status, AuthenticodeStatus.ERROR)
        self.assertEqual(malformed.status, AuthenticodeStatus.ERROR)

    def test_provider_is_invoked_without_embedding_target_in_command(self) -> None:
        calls = []

        def runner(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps({"Status": "NotSigned"}),
                stderr="",
            )

        with tempfile.TemporaryDirectory() as tmp:
            target = self._target(tmp)
            with mock.patch("acs.authenticode.sys.platform", "win32"):
                WindowsAuthenticodeVerifier(runner=runner).verify(target)

        args, kwargs = calls[0]
        self.assertNotIn(str(target), " ".join(args))
        self.assertEqual(kwargs["env"]["ACS_AUTHENTICODE_TARGET"], str(target.resolve()))
        self.assertNotIn(str(target), kwargs["input"])
        self.assertEqual(kwargs["timeout"], 20)

    def test_evidence_fields_are_bounded_and_nul_stripped(self) -> None:
        payload = {
            "Status": "Valid",
            "SignerSubject": "A" * 700 + "\x00secret",
            "SignerThumbprint": "ab" * 100,
            "TimestampSubject": "T" * 700,
        }
        with tempfile.TemporaryDirectory() as tmp:
            target = self._target(tmp)
            with mock.patch("acs.authenticode.sys.platform", "win32"):
                evidence = WindowsAuthenticodeVerifier(
                    runner=self._runner(payload)
                ).verify(target)
        self.assertEqual(len(evidence.signer_subject or ""), 512)
        self.assertNotIn("\x00", evidence.signer_subject or "")
        self.assertLessEqual(len(evidence.signer_thumbprint or ""), 128)
        self.assertEqual(len(evidence.timestamp_subject or ""), 512)

    def test_release_requirement_raises_only_bounded_status(self) -> None:
        class UnsignedVerifier:
            def verify(self, path):
                from acs.authenticode import AuthenticodeEvidence

                return AuthenticodeEvidence(AuthenticodeStatus.UNSIGNED, False)

        private_path = r"C:\Users\person\secret\candidate.exe"
        with self.assertRaisesRegex(ValueError, "unsigned") as caught:
            require_trusted_authenticode(private_path, verifier=UnsignedVerifier())
        self.assertNotIn("person", str(caught.exception))
        self.assertNotIn("candidate.exe", str(caught.exception))

    @unittest.skipUnless(sys.platform == "win32", "real Authenticode provider requires Windows")
    def test_real_windows_unsigned_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "unsigned.ps1"
            target.write_text("Write-Output 'unsigned fixture'\n", encoding="utf-8")
            evidence = WindowsAuthenticodeVerifier().verify(target)
        self.assertEqual(evidence.status, AuthenticodeStatus.UNSIGNED)
        self.assertFalse(evidence.acceptable_for_release)


if __name__ == "__main__":
    unittest.main()
