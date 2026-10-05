from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs import version2_package_preflight as preflight
from acs.version2_package_preflight import Version2PackagePreflightError
from tests.test_version2_package_preflight import (
    _make_tree,
    _minimal_windows_pe,
    _validate_tree,
    _write_checksums,
)


def _with_optional_magic(payload: bytes, magic: int) -> bytes:
    data = bytearray(payload)
    pe_offset = int.from_bytes(data[0x3C:0x40], "little")
    optional_header = pe_offset + 24
    data[optional_header:optional_header + 2] = magic.to_bytes(2, "little")
    return bytes(data)


class Version2PackagePeIdentityTests(unittest.TestCase):
    def _package(self, td: str) -> Path:
        root = Path(td) / "package"
        root.mkdir()
        _make_tree(root)
        return root

    def test_amd64_product_requires_pe32_plus_optional_header(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            executable = root / "AccessibleChess" / "AccessibleChess.exe"
            executable.write_bytes(
                _with_optional_magic(_minimal_windows_pe(machine=0x8664), 0x010B)
            )
            _write_checksums(root)

            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                r"unexpected Windows PE optional magic .*expected 0x020b",
            ):
                _validate_tree(root)

    def test_amd64_native_runtime_requires_pe32_plus_optional_header(self):
        relative = "AccessibleChess/webview/lib/runtimes/win-x64/native/WebView2Loader.dll"
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            runtime = root.joinpath(*relative.split("/"))
            runtime.write_bytes(
                _with_optional_magic(_minimal_windows_pe(machine=0x8664), 0x010B)
            )
            _write_checksums(root)

            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                r"unexpected Windows PE optional magic .*expected 0x020b",
            ):
                _validate_tree(root)

    def test_managed_anycpu_pe32_runtime_remains_allowed_with_clr_metadata(self):
        relative = "AccessibleChess/pythonnet/runtime/Python.Runtime.dll"
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            managed = root.joinpath(*relative.split("/"))
            managed.write_bytes(_minimal_windows_pe(machine=0x014C, managed=True))
            _write_checksums(root)

            report = _validate_tree(root)
            self.assertIn(relative, report.inventory)

    def test_native_pe_rejects_truncated_optional_header(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "runtime.dll"
            payload = bytearray(_minimal_windows_pe(machine=0x8664))
            pe_offset = int.from_bytes(payload[0x3C:0x40], "little")
            coff = pe_offset + 4
            payload[coff + 16:coff + 18] = (2).to_bytes(2, "little")
            target.write_bytes(payload)

            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "not a valid Windows PE executable",
            ):
                preflight._validate_windows_pe_executable(
                    target,
                    label="test runtime",
                    expected_machine=0x8664,
                    expected_optional_magic=0x020B,
                )

    def test_native_pe_rejects_missing_section_table(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "runtime.dll"
            payload = bytearray(_minimal_windows_pe(machine=0x8664))
            pe_offset = int.from_bytes(payload[0x3C:0x40], "little")
            coff = pe_offset + 4
            optional_size = int.from_bytes(
                payload[coff + 16:coff + 18],
                "little",
            )
            section_table = coff + 20 + optional_size
            target.write_bytes(bytes(payload[:section_table]))

            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "not a valid Windows PE executable",
            ):
                preflight._validate_windows_pe_executable(
                    target,
                    label="test runtime",
                    expected_machine=0x8664,
                    expected_optional_magic=0x020B,
                )

    def test_native_pe_validation_reads_machine_and_magic_from_one_open_handle(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "runtime.dll"
            target.write_bytes(_minimal_windows_pe(machine=0x8664))
            real_open = Path.open
            read_opens = 0

            def counting_open(path: Path, *args, **kwargs):
                nonlocal read_opens
                mode = args[0] if args else kwargs.get("mode", "r")
                if path == target and mode == "rb":
                    read_opens += 1
                return real_open(path, *args, **kwargs)

            with patch.object(Path, "open", new=counting_open):
                preflight._validate_windows_pe_executable(
                    target,
                    label="test runtime",
                    expected_machine=0x8664,
                    expected_optional_magic=0x020B,
                )
            self.assertEqual(read_opens, 1)

    def test_managed_pe_and_clr_validation_share_one_open_handle(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "managed.dll"
            target.write_bytes(_minimal_windows_pe(machine=0x014C, managed=True))
            real_open = Path.open
            read_opens = 0

            def counting_open(path: Path, *args, **kwargs):
                nonlocal read_opens
                mode = args[0] if args else kwargs.get("mode", "r")
                if path == target and mode == "rb":
                    read_opens += 1
                return real_open(path, *args, **kwargs)

            with patch.object(Path, "open", new=counting_open):
                preflight._validate_windows_pe_executable(
                    target,
                    label="managed runtime",
                    expected_machine=0x014C,
                    expected_optional_magic=0x010B,
                    require_clr=True,
                )
            self.assertEqual(read_opens, 1)

    def test_pe_validation_rejects_identity_change_while_opening(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "runtime.dll"
            target.write_bytes(_minimal_windows_pe(machine=0x8664))

            with patch.object(preflight, "_same_file_snapshot", return_value=False):
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "changed while being opened",
                ):
                    preflight._validate_windows_pe_executable(
                        target,
                        label="test runtime",
                        expected_machine=0x8664,
                        expected_optional_magic=0x020B,
                    )

    def test_pe_validation_rejects_identity_change_after_read(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "runtime.dll"
            target.write_bytes(_minimal_windows_pe(machine=0x8664))

            with patch.object(
                preflight,
                "_same_file_snapshot",
                side_effect=(True, True, False),
            ):
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "changed while being read",
                ):
                    preflight._validate_windows_pe_executable(
                        target,
                        label="test runtime",
                        expected_machine=0x8664,
                        expected_optional_magic=0x020B,
                    )


if __name__ == "__main__":
    unittest.main()
