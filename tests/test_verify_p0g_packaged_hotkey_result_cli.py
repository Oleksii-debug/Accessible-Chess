from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_p0g_packaged_hotkey_result_evidence.py"
SHA = "e" * 40


def _evidence() -> dict[str, object]:
    return {
        "product_sha": SHA,
        "discovery": "connected provider-root ControlView",
        "hotkey_focus_path": "board-launcher outside role=application",
        "board_application_entered": False,
        "engine_enable_state": "enabled-by-probe",
        "native_keyboard_dispatch": True,
        "foreground_product_verified": True,
        "manifest_product_sha_verified": True,
        "executable_checksum_verified": True,
        "alt_1_precondition_selected_state": "Variant 2. depth 10 eval +0.1",
        "alt_1_action_occurred": True,
        "alt_1_selected_state": "Variant 1. depth 10 eval +0.2",
        "alt_1_accessible_result_exposed": True,
        "alt_1_result": "Variant 1. depth 10, eval +0.2",
        "alt_2_precondition_selected_state": "Variant 1. depth 10 eval +0.2",
        "alt_2_action_occurred": True,
        "alt_2_selected_state": "Variant 2. depth 10 eval +0.1",
        "alt_2_accessible_result_exposed": True,
        "alt_2_result": "Variant 2. depth 10, eval +0.1",
        "raw_uci_or_debug_exposed": False,
        "human_tested": False,
        "nvda_verified": False,
    }


class VerifyP0GPackagedHotkeyResultCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.package = Path(self.temp.name)
        self.product = self.package / "AccessibleChess"
        self.product.mkdir()
        self.exe = self.product / "AccessibleChess.exe"
        self.exe.write_bytes(b"p0g-cli")
        digest = hashlib.sha256(self.exe.read_bytes()).hexdigest()
        (self.package / "RELEASE_MANIFEST.json").write_text(json.dumps({"integration_sha": SHA, "human_tested": False, "nvda_verified": False}), encoding="utf-8")
        (self.package / "SHA256SUMS.txt").write_text(
            f"{digest}  AccessibleChess/AccessibleChess.exe\n", encoding="utf-8"
        )
        self.evidence = self.package / "p0g.json"
        self.evidence.write_text(json.dumps(_evidence()), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--evidence", str(self.evidence), "--product-root", str(self.product), "--product-sha", SHA],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def test_cli_emits_exact_verified_marker(self) -> None:
        result = self._run()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("P0-G PACKAGED HOTKEY RESULT EVIDENCE VERIFIED", result.stdout.strip())
        self.assertEqual("", result.stderr)

    def test_cli_fails_if_package_changes_after_evidence(self) -> None:
        self.exe.write_bytes(b"tampered")
        result = self._run()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("P0-G PACKAGED HOTKEY RESULT EVIDENCE FAIL:", result.stdout)
        self.assertNotIn("VERIFIED", result.stdout)


if __name__ == "__main__":
    unittest.main()
