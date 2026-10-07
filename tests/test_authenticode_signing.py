from __future__ import annotations

from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from acs.authenticode_signing import (
    SigningRequest,
    SigningStatus,
    WindowsSignToolSigner,
)


THUMBPRINT = "A1" * 20
TIMESTAMP = "https://timestamp.example.invalid/rfc3161"


def _write_pe(path: Path, *, marker: bytes = b"payload") -> None:
    pe_offset = 0x80
    data = bytearray(512)
    data[0:2] = b"MZ"
    data[0x3C:0x40] = pe_offset.to_bytes(4, "little")
    data[pe_offset:pe_offset + 4] = b"PE\x00\x00"
    data[-len(marker):] = marker
    path.write_bytes(data)


class SigningRequestTests(unittest.TestCase):
    def test_normalizes_public_certificate_thumbprint(self) -> None:
        request = SigningRequest(
            certificate_thumbprint="a1 " * 19 + "a1",
            timestamp_url=TIMESTAMP,
        )
        self.assertEqual(request.certificate_thumbprint, THUMBPRINT)

    def test_rejects_malformed_thumbprints(self) -> None:
        for value in ("", "A1" * 19, "G1" * 20, "A1" * 21):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    SigningRequest(value, TIMESTAMP)

    def test_timestamp_must_be_canonical_https_without_credentials_or_fragment(self) -> None:
        bad = (
            "http://timestamp.example.test",
            "https://user@timestamp.example.test",
            "https://timestamp.example.test/path#fragment",
            " https://timestamp.example.test/path",
            "https://timestamp.example.test\\evil",
            "https://timestamp.example.test/\nnext",
        )
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    SigningRequest(THUMBPRINT, value)


class WindowsSignToolSignerTests(unittest.TestCase):
    def _paths(self, root: str) -> tuple[Path, Path]:
        target = Path(root) / "AccessibleChess.exe"
        tool = Path(root) / "signtool.exe"
        _write_pe(target)
        tool.write_bytes(b"fake-signtool")
        return target, tool

    @staticmethod
    def _mutating_runner(target: Path, calls: list[tuple[list[str], dict]]):
        def run(args, **kwargs):
            calls.append((list(args), dict(kwargs)))
            data = target.read_bytes()
            target.write_bytes(data + b"signed")
            return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")
        return run

    def test_non_windows_returns_unavailable_without_provider_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target, tool = self._paths(tmp)
            runner = mock.Mock(side_effect=AssertionError("provider must not run"))
            with mock.patch("acs.authenticode_signing.sys.platform", "linux"):
                result = WindowsSignToolSigner(runner=runner).sign(
                    target,
                    signtool=tool.resolve(),
                    request=SigningRequest(THUMBPRINT, TIMESTAMP),
                )
        self.assertEqual(result.status, SigningStatus.UNAVAILABLE)
        self.assertFalse(result.operation_succeeded)
        runner.assert_not_called()

    def test_builds_shell_free_sha256_rfc3161_command_and_requires_byte_change(self) -> None:
        calls: list[tuple[list[str], dict]] = []
        with tempfile.TemporaryDirectory() as tmp:
            target, tool = self._paths(tmp)
            with mock.patch("acs.authenticode_signing.sys.platform", "win32"):
                result = WindowsSignToolSigner(
                    runner=self._mutating_runner(target, calls)
                ).sign(
                    target,
                    signtool=tool.resolve(),
                    request=SigningRequest(THUMBPRINT, TIMESTAMP),
                )
        self.assertEqual(result.status, SigningStatus.SIGNED)
        self.assertTrue(result.operation_succeeded)
        self.assertTrue(result.bytes_changed)
        self.assertNotEqual(result.before_sha256, result.after_sha256)
        args, kwargs = calls[0]
        self.assertEqual(args[1:6], ["sign", "/fd", "SHA256", "/td", "SHA256"])
        self.assertEqual(args[6:10], ["/tr", TIMESTAMP, "/sha1", THUMBPRINT])
        self.assertEqual(kwargs["shell"], False)
        self.assertEqual(kwargs["timeout"], 120)
        self.assertTrue(Path(args[-1]).is_absolute())

    def test_zero_exit_without_mutation_fails_closed(self) -> None:
        def runner(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            target, tool = self._paths(tmp)
            with mock.patch("acs.authenticode_signing.sys.platform", "win32"):
                result = WindowsSignToolSigner(runner=runner).sign(
                    target,
                    signtool=tool.resolve(),
                    request=SigningRequest(THUMBPRINT, TIMESTAMP),
                )
        self.assertEqual(result.status, SigningStatus.ERROR)
        self.assertFalse(result.operation_succeeded)
        self.assertEqual(result.before_sha256, result.after_sha256)

    def test_provider_error_does_not_surface_output_or_mark_success(self) -> None:
        def runner(args, **kwargs):
            return subprocess.CompletedProcess(
                args,
                1,
                stdout="certificate details",
                stderr="machine path and provider details",
            )

        with tempfile.TemporaryDirectory() as tmp:
            target, tool = self._paths(tmp)
            with mock.patch("acs.authenticode_signing.sys.platform", "win32"):
                result = WindowsSignToolSigner(runner=runner).sign(
                    target,
                    signtool=tool.resolve(),
                    request=SigningRequest(THUMBPRINT, TIMESTAMP),
                )
        self.assertEqual(result.status, SigningStatus.ERROR)
        self.assertFalse(result.operation_succeeded)
        self.assertIsNone(result.after_sha256)

    def test_rejects_non_pe_target_relative_tool_and_indirect_target(self) -> None:
        request = SigningRequest(THUMBPRINT, TIMESTAMP)
        runner = mock.Mock(side_effect=AssertionError("provider must not run"))
        with tempfile.TemporaryDirectory() as tmp:
            target, tool = self._paths(tmp)
            non_pe = Path(tmp) / "not-pe.exe"
            non_pe.write_bytes(b"ordinary text")
            with mock.patch("acs.authenticode_signing.sys.platform", "win32"):
                self.assertEqual(
                    WindowsSignToolSigner(runner=runner).sign(
                        non_pe,
                        signtool=tool.resolve(),
                        request=request,
                    ).status,
                    SigningStatus.REJECTED,
                )
                self.assertEqual(
                    WindowsSignToolSigner(runner=runner).sign(
                        target,
                        signtool="signtool.exe",
                        request=request,
                    ).status,
                    SigningStatus.REJECTED,
                )
                link = Path(tmp) / "linked.exe"
                try:
                    link.symlink_to(target)
                except OSError:
                    link = None
                if link is not None:
                    self.assertEqual(
                        WindowsSignToolSigner(runner=runner).sign(
                            link,
                            signtool=tool.resolve(),
                            request=request,
                        ).status,
                        SigningStatus.REJECTED,
                    )
        runner.assert_not_called()

    def test_windows_reparse_target_is_rejected_before_provider(self) -> None:
        request = SigningRequest(THUMBPRINT, TIMESTAMP)
        runner = mock.Mock(side_effect=AssertionError("provider must not run"))
        reparse_info = mock.Mock(
            st_mode=stat.S_IFREG | 0o644,
            st_file_attributes=0x400,
            st_size=512,
        )
        with mock.patch.object(Path, "lstat", return_value=reparse_info):
            with mock.patch("acs.authenticode_signing.sys.platform", "win32"):
                result = WindowsSignToolSigner(runner=runner).sign(
                    "candidate.exe",
                    signtool=Path("C:/tools/signtool.exe"),
                    request=request,
                )
        self.assertEqual(result.status, SigningStatus.REJECTED)
        runner.assert_not_called()

    def test_contract_has_no_pfx_password_or_key_material_inputs(self) -> None:
        annotations = SigningRequest.__annotations__
        self.assertEqual(set(annotations), {"certificate_thumbprint", "timestamp_url"})
        forbidden = {"password", "pfx", "private_key", "secret", "token"}
        joined = " ".join(annotations).casefold()
        self.assertTrue(all(word not in joined for word in forbidden))


if __name__ == "__main__":
    unittest.main()
