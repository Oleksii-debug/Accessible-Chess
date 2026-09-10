from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest
import wave

from acs.version2_package_preflight import Version2PackagePreflightError
from tests.test_version2_package_preflight import (
    _make_tree,
    _validate_tree,
    _write_checksums,
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
                "THIRD_PARTY_NOTICES/Stockfish-18-source.zip",
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
            "AccessibleChess/engines/stockfish/stockfish.exe",
            "AccessibleChess/assets/sounds/manifest.json",
            "AccessibleChess/assets/sounds/move.wav",
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

    def test_preflight_rejects_duplicate_sound_asset_mapping(self):
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
                "distinct WAV",
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

    def test_preflight_rejects_non_16_bit_pcm_sound_asset(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._package(td)
            sound = root / "AccessibleChess/assets/sounds/move.wav"
            with wave.open(str(sound), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(1)
                writer.setframerate(8000)
                writer.writeframes(b"\x00" * 16)
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "16-bit PCM",
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
