from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
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


def _with_dll_characteristic(payload: bytes) -> bytes:
    data = bytearray(payload)
    pe_offset = int.from_bytes(data[0x3C:0x40], "little")
    characteristics = pe_offset + 4 + 18
    value = int.from_bytes(data[characteristics:characteristics + 2], "little")
    data[characteristics:characteristics + 2] = (value | 0x2000).to_bytes(2, "little")
    return bytes(data)


def _snapshot(*, dev, ino, size: int = 4096, mtime_ns: int = 123456789):
    return SimpleNamespace(
        st_dev=dev,
        st_ino=ino,
        st_size=size,
        st_mtime_ns=mtime_ns,
    )


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

    def test_product_executable_rejects_dll_image_characteristic(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            executable = root / "AccessibleChess" / "AccessibleChess.exe"
            executable.write_bytes(
                _with_dll_characteristic(_minimal_windows_pe(machine=0x8664))
            )
            _write_checksums(root)

            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                r"image kind DLL; expected EXE",
            ):
                _validate_tree(root)

    def test_stockfish_executable_rejects_dll_image_characteristic(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            stockfish = root.joinpath(*preflight._REQUIRED_STOCKFISH.split("/"))
            stockfish.write_bytes(
                _with_dll_characteristic(_minimal_windows_pe(machine=0x8664))
            )
            _write_checksums(root)

            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                r"image kind DLL; expected EXE",
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

    def test_native_pe_rejects_section_raw_extent_beyond_file(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "runtime.dll"
            payload = bytearray(_minimal_windows_pe(machine=0x8664))
            pe_offset = int.from_bytes(payload[0x3C:0x40], "little")
            coff = pe_offset + 4
            optional_size = int.from_bytes(
                payload[coff + 16:coff + 18],
                "little",
            )
            section = coff + 20 + optional_size
            payload[section + 16:section + 20] = (0x1000).to_bytes(4, "little")
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

    def test_native_pe_rejects_image_without_file_backed_section(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "runtime.dll"
            payload = bytearray(_minimal_windows_pe(machine=0x8664))
            pe_offset = int.from_bytes(payload[0x3C:0x40], "little")
            coff = pe_offset + 4
            optional_size = int.from_bytes(
                payload[coff + 16:coff + 18],
                "little",
            )
            section = coff + 20 + optional_size
            payload[section + 16:section + 20] = (0).to_bytes(4, "little")
            payload[section + 20:section + 24] = (0).to_bytes(4, "little")
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

    def test_snapshot_fallback_rejects_unavailable_file_identity(self):
        unknown_pairs = (
            (_snapshot(dev=None, ino=None), _snapshot(dev=None, ino=None)),
            (_snapshot(dev=0, ino=0), _snapshot(dev=0, ino=0)),
            (_snapshot(dev=5, ino=0), _snapshot(dev=5, ino=0)),
            (_snapshot(dev=0, ino=19), _snapshot(dev=0, ino=19)),
        )
        with patch.object(preflight.os.path, "samestat", side_effect=OSError("unavailable")):
            for left, right in unknown_pairs:
                with self.subTest(left=left, right=right):
                    self.assertFalse(preflight._same_file_snapshot(left, right))

    def test_snapshot_fallback_accepts_only_matching_nonzero_file_identity(self):
        left = _snapshot(dev=5, ino=19)
        same = _snapshot(dev=5, ino=19)
        different_inode = _snapshot(dev=5, ino=20)
        different_size = _snapshot(dev=5, ino=19, size=4097)
        with patch.object(preflight.os.path, "samestat", side_effect=AttributeError("unavailable")):
            self.assertTrue(preflight._same_file_snapshot(left, same))
            self.assertFalse(preflight._same_file_snapshot(left, different_inode))
            self.assertFalse(preflight._same_file_snapshot(left, different_size))

    def test_snapshot_rejects_missing_or_noninteger_mtime_metadata(self):
        valid = _snapshot(dev=5, ino=19)
        missing = SimpleNamespace(st_dev=5, st_ino=19, st_size=4096)
        unavailable = _snapshot(dev=5, ino=19, mtime_ns=None)
        boolean = _snapshot(dev=5, ino=19, mtime_ns=True)
        text = _snapshot(dev=5, ino=19, mtime_ns="123456789")

        with patch.object(preflight.os.path, "samestat", return_value=True):
            self.assertFalse(preflight._same_file_snapshot(missing, missing))
            self.assertFalse(preflight._same_file_snapshot(valid, unavailable))
            self.assertFalse(preflight._same_file_snapshot(boolean, boolean))
            self.assertFalse(preflight._same_file_snapshot(text, text))

    def test_snapshot_rejects_missing_invalid_or_changed_size_metadata(self):
        valid = _snapshot(dev=5, ino=19)
        missing = SimpleNamespace(
            st_dev=5,
            st_ino=19,
            st_mtime_ns=123456789,
        )
        boolean = SimpleNamespace(
            st_dev=5,
            st_ino=19,
            st_size=True,
            st_mtime_ns=123456789,
        )
        negative = _snapshot(dev=5, ino=19, size=-1)
        changed = _snapshot(dev=5, ino=19, size=4097)

        with patch.object(preflight.os.path, "samestat", return_value=True):
            self.assertFalse(preflight._same_file_snapshot(missing, missing))
            self.assertFalse(preflight._same_file_snapshot(boolean, boolean))
            self.assertFalse(preflight._same_file_snapshot(negative, negative))
            self.assertFalse(preflight._same_file_snapshot(valid, changed))

    def test_snapshot_rejects_negative_or_changed_mtime_metadata(self):
        valid = _snapshot(dev=5, ino=19)
        negative = _snapshot(dev=5, ino=19, mtime_ns=-1)
        changed = _snapshot(dev=5, ino=19, mtime_ns=123456790)

        with patch.object(preflight.os.path, "samestat", return_value=True):
            self.assertFalse(preflight._same_file_snapshot(negative, negative))
            self.assertFalse(preflight._same_file_snapshot(valid, changed))

    def test_checksum_inventory_is_parsed_from_one_stable_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            real_snapshot = preflight._snapshot_regular_file

            with patch.object(
                preflight,
                "_snapshot_regular_file",
                wraps=real_snapshot,
            ) as snapshots:
                report = _validate_tree(root)

            checksum_calls = [
                call
                for call in snapshots.call_args_list
                if Path(call.args[0]).name == preflight.CHECKSUMS_NAME
            ]
            self.assertEqual(len(checksum_calls), 1)
            self.assertEqual(
                checksum_calls[0].kwargs["label"],
                "checksum inventory",
            )
            self.assertEqual(report.integration_sha, "a" * 40)

    def test_checksum_inventory_snapshot_failure_is_authoritative(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            real_snapshot = preflight._snapshot_regular_file

            def snapshot_or_fail(path: Path, *args, **kwargs):
                if Path(path).name == preflight.CHECKSUMS_NAME:
                    raise Version2PackagePreflightError(
                        "checksum inventory changed while being read"
                    )
                return real_snapshot(path, *args, **kwargs)

            with patch.object(
                preflight,
                "_snapshot_regular_file",
                side_effect=snapshot_or_fail,
            ):
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "checksum inventory changed while being read",
                ):
                    _validate_tree(root)

    def test_sha256_reads_one_stable_file_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "payload.bin"
            payload = b"stable-package-payload"
            target.write_bytes(payload)
            real_open = Path.open
            read_opens = 0

            def counting_open(path: Path, *args, **kwargs):
                nonlocal read_opens
                mode = args[0] if args else kwargs.get("mode", "r")
                if path == target and mode == "rb":
                    read_opens += 1
                return real_open(path, *args, **kwargs)

            with patch.object(Path, "open", new=counting_open):
                digest = preflight._sha256(target)

            self.assertEqual(
                digest,
                preflight.hashlib.sha256(payload).hexdigest(),
            )
            self.assertEqual(read_opens, 1)

    def test_sha256_rejects_identity_change_while_opening(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "payload.bin"
            target.write_bytes(b"stable-package-payload")

            with patch.object(preflight, "_same_file_snapshot", return_value=False):
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "package file changed while being opened",
                ):
                    preflight._sha256(target)

    def test_sha256_rejects_handle_change_after_read(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "payload.bin"
            target.write_bytes(b"stable-package-payload")

            with patch.object(
                preflight,
                "_same_file_snapshot",
                side_effect=(True, False),
            ):
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "package file changed while being read",
                ):
                    preflight._sha256(target)

    def test_sha256_rejects_path_change_after_read(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "payload.bin"
            target.write_bytes(b"stable-package-payload")

            with patch.object(
                preflight,
                "_same_file_snapshot",
                side_effect=(True, True, False),
            ):
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "package file changed while being read",
                ):
                    preflight._sha256(target)

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
