from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest
import wave

from acs import version2_package_preflight as preflight
from acs.version2_package_preflight import Version2PackagePreflightError
from tests.test_version2_package_preflight import (
    _make_tree,
    _minimal_windows_pe,
    _validate_tree,
    _validate_zip,
    _write_checksums,
    _zip_tree,
)


class Version2PackageRequiredResourcesTests(unittest.TestCase):
    def _package(self, td: str) -> Path:
        root = Path(td) / "package"
        root.mkdir()
        _make_tree(root)
        return root

    def test_complete_release_resource_fixture_is_valid(self):
        with tempfile.TemporaryDirectory() as td:
            report = _validate_tree(self._package(td))
            self.assertIn(
                "AccessibleChess/engines/stockfish/stockfish.exe",
                report.inventory,
            )
            self.assertIn(
                "AccessibleChess/assets/sounds/manifest.json",
                report.inventory,
            )
            self.assertIn(
                "THIRD_PARTY_NOTICES/SOUND_PROVENANCE.json",
                report.inventory,
            )
            self.assertIn(
                "THIRD_PARTY_NOTICES/Stockfish-18-source.zip",
                report.inventory,
            )
            self.assertIn(
                "AccessibleChess/web/docs/ACCESSIBLE_CHESS_HOTKEYS_UK.txt",
                report.inventory,
            )
            self.assertIn(
                "AccessibleChess/web/docs/ACCESSIBLE_CHESS_CAPABILITIES_TESTING_UK.txt",
                report.inventory,
            )

    def test_preflight_rejects_package_without_release_critical_runtime_resources(self):
        removals = (
            "AccessibleChess/web",
            "AccessibleChess/engines",
            "AccessibleChess/assets/sounds",
            "THIRD_PARTY_NOTICES",
        )
        for relative in removals:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as td:
                root = self._package(td)
                shutil.rmtree(root / relative)
                _write_checksums(root)
                with self.assertRaises(Version2PackagePreflightError):
                    _validate_tree(root)

    def test_preflight_rejects_each_missing_required_file_family(self):
        removals = (
            "AccessibleChess/web/version2_release_bootstrap.js",
            "AccessibleChess/web/protection_locked.html",
            "AccessibleChess/web/protection_locked.js",
            "AccessibleChess/web/docs/ACCESSIBLE_CHESS_HOTKEYS_UK.txt",
            "AccessibleChess/web/docs/ACCESSIBLE_CHESS_CAPABILITIES_TESTING_UK.txt",
            "AccessibleChess/engines/stockfish/stockfish.exe",
            "AccessibleChess/assets/sounds/manifest.json",
            "AccessibleChess/assets/sounds/move.wav",
            "THIRD_PARTY_NOTICES/SOUND_PROVENANCE.json",
            "THIRD_PARTY_NOTICES/Stockfish-18-source.zip",
            "THIRD_PARTY_NOTICES/Stockfish-NOTICE.txt",
        )
        for relative in removals:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as td:
                root = self._package(td)
                (root / relative).unlink()
                _write_checksums(root)
                with self.assertRaises(Version2PackagePreflightError):
                    _validate_tree(root)

    def test_preflight_requires_exact_desktop_startup_runtime_closure(self):
        with tempfile.TemporaryDirectory() as td:
            report = _validate_tree(self._package(td))
            for relative in preflight._REQUIRED_DESKTOP_RUNTIME_FILES:
                with self.subTest(relative=relative):
                    self.assertIn(relative, report.inventory)

        for relative in preflight._REQUIRED_DESKTOP_RUNTIME_FILES:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as td:
                root = self._package(td)
                root.joinpath(*relative.split("/")).unlink()
                _write_checksums(root)
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "desktop runtime",
                ):
                    _validate_tree(root)

    def test_zip_readback_rejects_missing_desktop_startup_runtime(self):
        relative = "AccessibleChess/webview/lib/runtimes/win-x64/native/WebView2Loader.dll"
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = self._package(td)
            root.joinpath(*relative.split("/")).unlink()
            _write_checksums(root)
            archive = base / "missing-webview2-runtime.zip"
            _zip_tree(root, archive)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "desktop runtime",
            ):
                _validate_zip(archive)

    def test_preflight_rejects_non_windows_product_executable(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            (root / "AccessibleChess/AccessibleChess.exe").write_bytes(
                b"\x7fELF" + (b"\x00" * 124)
            )
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "packaged AccessibleChess executable is not a valid Windows PE executable",
            ):
                _validate_tree(root)

    def test_preflight_rejects_32_bit_product_executable(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            (root / "AccessibleChess/AccessibleChess.exe").write_bytes(
                _minimal_windows_pe(machine=0x014C)
            )
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "unexpected Windows PE machine 0x014c; expected 0x8664",
            ):
                _validate_tree(root)

    def test_preflight_rejects_mz_only_product_executable(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            (root / "AccessibleChess/AccessibleChess.exe").write_bytes(
                b"MZ" + (b"\x00" * 126)
            )
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "packaged AccessibleChess executable is not a valid Windows PE executable",
            ):
                _validate_tree(root)

    def test_preflight_rejects_32_bit_native_desktop_runtime(self):
        relative = "AccessibleChess/webview/lib/runtimes/win-x64/native/WebView2Loader.dll"
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            root.joinpath(*relative.split("/")).write_bytes(
                _minimal_windows_pe(machine=0x014C)
            )
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "unexpected Windows PE machine 0x014c; expected 0x8664",
            ):
                _validate_tree(root)

    def test_preflight_rejects_non_pe_desktop_startup_runtime(self):
        relative = "AccessibleChess/webview/lib/runtimes/win-x64/native/WebView2Loader.dll"
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            root.joinpath(*relative.split("/")).write_bytes(b"not-a-windows-runtime")
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "empty or invalid|Windows PE executable",
            ):
                _validate_tree(root)

    def test_preflight_rejects_native_pe_substituted_for_managed_runtime(self):
        for relative in preflight._REQUIRED_MANAGED_DESKTOP_RUNTIME_FILES:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as td:
                root = self._package(td)
                machine = (
                    0x014C
                    if relative in preflight._REQUIRED_I386_MANAGED_DESKTOP_RUNTIME_FILES
                    else 0x8664
                )
                root.joinpath(*relative.split("/")).write_bytes(
                    _minimal_windows_pe(machine=machine)
                )
                _write_checksums(root)
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "managed CLR assembly",
                ):
                    _validate_tree(root)

    def test_preflight_rejects_corrupt_file_backed_clr_metadata(self):
        relative = "AccessibleChess/pythonnet/runtime/Python.Runtime.dll"
        cases = (
            ("clr-header-size", 0x200, (0x47).to_bytes(4, "little")),
            ("metadata-span", 0x20C, (0x1000).to_bytes(4, "little")),
            ("metadata-signature", 0x280, b"NOPE"),
        )
        for label, offset, replacement in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as td:
                root = self._package(td)
                binary = bytearray(
                    _minimal_windows_pe(machine=0x014C, managed=True)
                )
                binary[offset:offset + len(replacement)] = replacement
                root.joinpath(*relative.split("/")).write_bytes(binary)
                _write_checksums(root)
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "managed CLR assembly",
                ):
                    _validate_tree(root)

    def test_preflight_rejects_wrong_pe_class_for_anycpu_runtime(self):
        relative = "AccessibleChess/pythonnet/runtime/Python.Runtime.dll"
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            binary = bytearray(_minimal_windows_pe(machine=0x014C, managed=True))
            pe_offset = int.from_bytes(binary[0x3C:0x40], "little")
            optional = pe_offset + 24
            binary[optional:optional + 2] = (0x20B).to_bytes(2, "little")
            root.joinpath(*relative.split("/")).write_bytes(binary)
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "unexpected Windows PE optional magic 0x020b; expected 0x010b",
            ):
                _validate_tree(root)

    def test_preflight_rejects_wrong_machine_for_managed_runtime(self):
        for relative in preflight._REQUIRED_MANAGED_DESKTOP_RUNTIME_FILES:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as td:
                root = self._package(td)
                machine = (
                    0x8664
                    if relative in preflight._REQUIRED_I386_MANAGED_DESKTOP_RUNTIME_FILES
                    else 0x014C
                )
                root.joinpath(*relative.split("/")).write_bytes(
                    _minimal_windows_pe(machine=machine, managed=True)
                )
                _write_checksums(root)
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "unexpected Windows PE machine",
                ):
                    _validate_tree(root)

    def test_zip_readback_rejects_native_pe_substituted_for_managed_runtime(self):
        relative = "AccessibleChess/pythonnet/runtime/Python.Runtime.dll"
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = self._package(td)
            root.joinpath(*relative.split("/")).write_bytes(
                _minimal_windows_pe(machine=0x014C)
            )
            _write_checksums(root)
            archive = base / "native-python-runtime.zip"
            _zip_tree(root, archive)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "managed CLR assembly",
            ):
                _validate_zip(archive)

    def test_preflight_rejects_non_windows_stockfish_binary(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            (root / "AccessibleChess/engines/stockfish/stockfish.exe").write_bytes(
                b"\x7fELF" + (b"\x00" * 124)
            )
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "Windows PE executable",
            ):
                _validate_tree(root)

    def test_preflight_rejects_32_bit_stockfish_binary(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            (root / "AccessibleChess/engines/stockfish/stockfish.exe").write_bytes(
                _minimal_windows_pe(machine=0x014C)
            )
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "unexpected Windows PE machine 0x014c; expected 0x8664",
            ):
                _validate_tree(root)

    def test_preflight_rejects_mz_only_stockfish_binary(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            (root / "AccessibleChess/engines/stockfish/stockfish.exe").write_bytes(
                b"MZ" + (b"\x00" * 126)
            )
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "Windows PE executable",
            ):
                _validate_tree(root)

    def test_preflight_rejects_incomplete_sound_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            manifest_path = root / "AccessibleChess/assets/sounds/manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            del manifest["files"]["tick"]
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "every semantic sound event",
            ):
                _validate_tree(root)

    def test_preflight_rejects_sound_alias_without_matching_event_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            manifest_path = root / "AccessibleChess/assets/sounds/manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["capture"] = manifest["files"]["move"]
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "sound provenance file does not match manifest: capture",
            ):
                _validate_tree(root)

    def test_preflight_rejects_corrupt_sound_asset(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            (root / "AccessibleChess/assets/sounds/move.wav").write_bytes(b"not-wave")
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "sound asset",
            ):
                _validate_tree(root)

    def test_semantic_sound_alias_with_matching_event_provenance_is_valid(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            manifest_path = root / "AccessibleChess/assets/sounds/manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["capture"] = manifest["files"]["move"]
            manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
            provenance_path = root / "THIRD_PARTY_NOTICES/SOUND_PROVENANCE.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance["events"]["capture"]["file"] = manifest["files"]["move"]
            provenance["events"]["capture"]["sha256"] = provenance["events"]["move"]["sha256"]
            provenance_path.write_text(json.dumps(provenance, sort_keys=True) + "\n", encoding="utf-8")
            _write_checksums(root)
            _validate_tree(root)

    def test_preflight_rejects_unsupported_24_bit_pcm_sound_asset(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            sound = root / "AccessibleChess/assets/sounds/move.wav"
            with wave.open(str(sound), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(3)
                writer.setframerate(8000)
                writer.writeframes(b"\x00\x00\x00" * 16)
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "8-bit/16-bit PCM",
            ):
                _validate_tree(root)

    def test_preflight_rejects_sound_provenance_not_bound_to_asset(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            provenance_path = root / "THIRD_PARTY_NOTICES/SOUND_PROVENANCE.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance["events"]["move"]["sha256"] = "0" * 64
            provenance_path.write_text(
                json.dumps(provenance, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "sound provenance SHA-256 mismatch",
            ):
                _validate_tree(root)

    def test_preflight_rejects_unresolved_or_local_sound_provenance_identity(self):
        cases = (
            ("license", "license_id", "unknown", "license identity is unresolved"),
            ("creator", "creator", "TBD", "creator identity is unresolved"),
            ("source", "source", r"C:\\private\\move.wav", "HTTPS URL or URN"),
            ("file", "file", "other.wav", "does not match manifest"),
        )
        for label, field, value, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as td:
                root = self._package(td)
                provenance_path = root / "THIRD_PARTY_NOTICES/SOUND_PROVENANCE.json"
                provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                provenance["events"]["move"][field] = value
                provenance_path.write_text(
                    json.dumps(provenance, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                )
                _write_checksums(root)
                with self.assertRaisesRegex(Version2PackagePreflightError, expected):
                    _validate_tree(root)

    def test_preflight_rejects_incomplete_sound_provenance_event_set(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            provenance_path = root / "THIRD_PARTY_NOTICES/SOUND_PROVENANCE.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            del provenance["events"]["tick"]
            provenance_path.write_text(
                json.dumps(provenance, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "every semantic sound event",
            ):
                _validate_tree(root)

    def test_preflight_rejects_invalid_or_non_source_stockfish_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            source = root / "THIRD_PARTY_NOTICES/Stockfish-18-source.zip"
            source.write_bytes(b"not-a-zip")
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "source archive is invalid",
            ):
                _validate_tree(root)

    def test_preflight_rejects_incomplete_stockfish_gpl_notice(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            notice = root / "THIRD_PARTY_NOTICES/Stockfish-NOTICE.txt"
            notice.write_text("Stockfish\n", encoding="utf-8")
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "GPL notice is incomplete",
            ):
                _validate_tree(root)


if __name__ == "__main__":
    unittest.main()
