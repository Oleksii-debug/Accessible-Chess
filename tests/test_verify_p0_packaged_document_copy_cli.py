from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_p0_packaged_document_copy_evidence.py"
SHA = "b" * 40


class VerifyP0PackagedDocumentCopyCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.package = Path(self.temp.name)
        self.product = self.package / "AccessibleChess"
        self.product.mkdir()
        self.exe = self.product / "AccessibleChess.exe"
        self.exe.write_bytes(b"cli-fixture")
        digest = hashlib.sha256(self.exe.read_bytes()).hexdigest()
        (self.package / "RELEASE_MANIFEST.json").write_text(
            json.dumps({"integration_sha": SHA, "human_tested": False, "nvda_verified": False}), encoding="utf-8"
        )
        (self.package / "SHA256SUMS.txt").write_text(
            f"{digest}  AccessibleChess/AccessibleChess.exe\n", encoding="utf-8"
        )
        self.evidence = self.package / "copy-evidence.json"
        self.evidence.write_text(
            json.dumps(
                {
                    "product_sha": SHA,
                    "static_document_text": "Game information",
                    "static_document_outside_edit": True,
                    "static_text_visible_rectangle": True,
                    "native_copy_focus_verified": True,
                    "foreground_product_verified": True,
                    "manifest_product_sha_verified": True,
                    "executable_checksum_verified": True,
                    "textpattern_selection_supported": True,
                    "textpattern_target_selected": True,
                    "textpattern_selection_equality": "UIA exact range endpoints and case-sensitive text equality",
                    "clipboard_equality": "case-sensitive exact string equality",
                    "ctrl_c_exact_clipboard": True,
                    "move_input_focus_verified": True,
                    "move_input_native_ctrl_a_ctrl_c": True,
                    "human_tested": False,
                    "nvda_verified": False,
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--evidence",
                str(self.evidence),
                "--product-root",
                str(self.product),
                "--product-sha",
                SHA,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def test_cli_emits_single_release_pass_marker(self) -> None:
        result = self._run()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("P0 PACKAGED DOCUMENT COPY EVIDENCE VERIFIED", result.stdout.strip())
        self.assertEqual("", result.stderr)

    def test_cli_fails_after_package_binary_tamper(self) -> None:
        self.exe.write_bytes(b"tampered-after-inventory")
        result = self._run()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("P0 PACKAGED DOCUMENT COPY EVIDENCE FAIL:", result.stdout)
        self.assertNotIn("VERIFIED", result.stdout)


if __name__ == "__main__":
    unittest.main()
