from __future__ import annotations

import os
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
                r"expected PE32\+ 0x020b for AMD64",
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
                r"expected PE32\+ 0x020b for AMD64",
            ):
                _validate_tree(root)

    def test_managed_anycpu_pe32_runtime_remains_allowed(self):
        relative = "AccessibleChess/pythonnet/runtime/Python.Runtime.dll"
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            managed = root.joinpath(*relative.split("/"))
            managed.write_bytes(
                _with_optional_magic(_minimal_windows_pe(machine=0x014C), 0x010B)
            )
            _write_checksums(root)

            report = _validate_tree(root)
            self.assertIn(relative, report.inventory)

    def test_pe_validation_rejects_path_replacement_during_single_identity_read(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "runtime.dll"
            replacement = root / "replacement.dll"
            target.write_bytes(_minimal_windows_pe(machine=0x8664))
            replacement.write_bytes(b"MZ" + b"\x00" * 510)

            real_open = Path.open
            swapped = False

            def racing_open(path: Path, *args, **kwargs):
                nonlocal swapped
                handle = real_open(path, *args, **kwargs)
                mode = args[0] if args else kwargs.get("mode", "r")
                if path == target and mode == "rb" and not swapped:
                    os.replace(replacement, target)
                    swapped = True
                return handle

            with patch.object(Path, "open", new=racing_open):
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "changed while being read",
                ):
                    preflight._validate_windows_pe_executable(
                        target,
                        label="test runtime",
                        expected_machine=0x8664,
                    )
            self.assertTrue(swapped)


if __name__ == "__main__":
    unittest.main()
