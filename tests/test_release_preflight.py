from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import wave
import zipfile

from acs.release_preflight import ReleasePreflightError, inspect_release_package


EVENTS = ("move", "capture", "check", "castle", "promotion", "illegal", "start", "end", "tick")


class ReleasePreflightTests(unittest.TestCase):
    def make_package(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name) / "пакет з пробілом"
        product = root / "AccessibleChess"
        sounds = product / "assets" / "sounds"
        engine = product / "engines" / "stockfish"
        notices = root / "THIRD_PARTY_NOTICES"
        sounds.mkdir(parents=True); engine.mkdir(parents=True); notices.mkdir(parents=True)
        (product / "AccessibleChess.exe").write_bytes(b"MZ-accessible-chess")
        (engine / "stockfish.exe").write_bytes(b"MZ-stockfish-18")
        for index, event in enumerate(EVENTS, start=1):
            with wave.open(str(sounds / f"{event}.wav"), "wb") as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000)
                wav.writeframes((index.to_bytes(2, "little", signed=True)) * 80)
        (sounds / "manifest.json").write_text(json.dumps({"schema_version": 1, "files": {e: f"{e}.wav" for e in EVENTS}}), encoding="utf-8")
        with zipfile.ZipFile(notices / "Stockfish-18-source.zip", "w") as archive:
            archive.writestr("Stockfish-sf_18/Copying.txt", "GPLv3")
        (notices / "NOTICE.txt").write_text("Stockfish 18 GPLv3", encoding="utf-8")
        (notices / "README.txt").write_text("Source included", encoding="utf-8")
        (root / "native-menu-self-diagnostic.json").write_text("{}", encoding="utf-8")
        (root / "packaged-uia-strict-summary.json").write_text("{}", encoding="utf-8")
        (root / "nuitka-compilation-report.xml").write_text("<report/>", encoding="utf-8")
        (root / "RELEASE_MANIFEST.json").write_text(json.dumps({
            "product": "Accessible Chess", "integration_sha": "1" * 40, "qa_commit": "2" * 40,
            "nvda_verified": False, "strict_cross_process_uia": "PASS",
            "packaged_e4_e9_clipboard_board_focus": "PASS", "packaged_sound": "PASS",
            "stockfish_runtime_lifecycle": "PASS", "native_menu_automated_self_diagnostic": "PASS",
        }), encoding="utf-8")
        self.rewrite_checksums(root)
        return root

    def rewrite_checksums(self, root: Path) -> None:
        files = sorted((p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"), key=lambda p: p.relative_to(root).as_posix().casefold())
        rows = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}" for p in files]
        (root / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")

    def rejected(self, root: Path, fragment: str) -> None:
        with self.assertRaises(ReleasePreflightError) as caught:
            inspect_release_package(root)
        self.assertIn(fragment, str(caught.exception))

    def test_unicode_space_tree_and_inventory_are_deterministic(self) -> None:
        root = self.make_package(); first = inspect_release_package(root); second = inspect_release_package(root)
        self.assertEqual(first, second); self.assertEqual(first.checksums_verified, len(first.inventory) - 1)
        self.assertIn("AccessibleChess/assets/sounds/manifest.json", first.inventory)

    def test_checksum_traversal_is_rejected(self) -> None:
        root = self.make_package(); sums = root / "SHA256SUMS.txt"; digest = sums.read_text().split("  ", 1)[0]
        sums.write_text(f"{digest}  ../outside.bin\n", encoding="utf-8"); self.rejected(root, "unsafe path components")

    def test_sound_manifest_traversal_and_extra_event_are_rejected(self) -> None:
        root = self.make_package(); path = root / "AccessibleChess/assets/sounds/manifest.json"; data = json.loads(path.read_text())
        data["files"]["move"] = "../move.wav"; path.write_text(json.dumps(data)); self.rewrite_checksums(root); self.rejected(root, "sound package is invalid")
        root = self.make_package(); path = root / "AccessibleChess/assets/sounds/manifest.json"; data = json.loads(path.read_text())
        data["files"]["debug"] = "move.wav"; path.write_text(json.dumps(data)); self.rewrite_checksums(root); self.rejected(root, "exactly the nine")

    def test_source_stale_tree_and_double_nesting_are_rejected(self) -> None:
        root = self.make_package(); leak = root / "AccessibleChess/acs/secret.py"; leak.parent.mkdir(); leak.write_text("TOKEN='x'"); self.rewrite_checksums(root); self.rejected(root, "raw product source")
        root = self.make_package(); stale = root / "AccessibleChess/build/stale.bin"; stale.parent.mkdir(); stale.write_bytes(b"x"); self.rewrite_checksums(root); self.rejected(root, "stale/build/source")
        root = self.make_package(); nested = root / "AccessibleChess/AccessibleChess/AccessibleChess.exe"; nested.parent.mkdir(); nested.write_bytes(b"x"); self.rewrite_checksums(root); self.rejected(root, "double AccessibleChess")

    def test_manifest_nvda_true_is_rejected(self) -> None:
        root = self.make_package(); path = root / "RELEASE_MANIFEST.json"; data = json.loads(path.read_text()); data["nvda_verified"] = True
        path.write_text(json.dumps(data)); self.rewrite_checksums(root); self.rejected(root, "nvda_verified=false")

    def test_extra_unchecksummed_file_and_tamper_are_rejected(self) -> None:
        root = self.make_package(); (root / "AccessibleChess/unexpected.dll").write_bytes(b"x"); self.rejected(root, "inventory mismatch")
        root = self.make_package(); (root / "AccessibleChess/AccessibleChess.exe").write_bytes(b"tampered"); self.rejected(root, "checksum mismatch")

    def test_corrupt_stockfish_source_and_unexpected_top_file_are_rejected(self) -> None:
        root = self.make_package(); source = root / "THIRD_PARTY_NOTICES/Stockfish-18-source.zip"; source.write_bytes(b"bad"); self.rewrite_checksums(root); self.rejected(root, "valid ZIP")
        root = self.make_package(); (root / "debug.log").write_text("C:\\secret"); self.rewrite_checksums(root); self.rejected(root, "unexpected top-level files")

    def test_symlink_escape_is_rejected_when_supported(self) -> None:
        root = self.make_package(); outside = root.parent / "outside.bin"; outside.write_bytes(b"outside"); link = root / "AccessibleChess/escape.dll"
        try: link.symlink_to(outside)
        except (OSError, NotImplementedError): self.skipTest("symlink unavailable")
        self.rewrite_checksums(root); self.rejected(root, "symbolic link")


if __name__ == "__main__":
    unittest.main()
