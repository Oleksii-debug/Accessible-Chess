from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "p0_packaged_document_copy_probe.ps1"


class PackagedDocumentCopyProbeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = PROBE.read_text(encoding="utf-8")

    def test_native_copy_is_bound_to_foreground_packaged_process(self) -> None:
        self.assertIn("GetForegroundWindow", self.text)
        self.assertIn("GetWindowThreadProcessId", self.text)
        self.assertIn("function ActivateProduct($Shell,$Process,[string]$Phase)", self.text)
        self.assertIn("if(-not $Shell.AppActivate($Process.Id))", self.text)
        self.assertIn("function AssertProductForeground($Process,[string]$Phase)", self.text)
        self.assertIn("foreground_product_verified=$true", self.text)
        self.assertNotIn("$null=$shell.AppActivate($process.Id)", self.text)

        static_assert = self.text.index("AssertProductForeground $process 'static document copy dispatch'")
        static_copy = self.text.index("[AccessibleChessCopyKeys]::Ctrl([byte]0x43)")
        self.assertLess(static_assert, static_copy)

        edit_assert = self.text.index("AssertProductForeground $process 'move input copy dispatch'")
        edit_select = self.text.index("[AccessibleChessCopyKeys]::Ctrl([byte]0x41)")
        edit_reassert = self.text.index("AssertProductForeground $process 'move input copy dispatch after Ctrl+A'")
        edit_copy = self.text.index("[AccessibleChessCopyKeys]::Ctrl([byte]0x43)", static_copy + 1)
        self.assertLess(edit_assert, edit_select)
        self.assertLess(edit_select, edit_reassert)
        self.assertLess(edit_reassert, edit_copy)

    def test_existing_document_selection_and_exact_clipboard_proof_remains_required(self) -> None:
        self.assertIn("TextPattern]::Pattern", self.text)
        self.assertIn("expected exactly one stable packaged document provider", self.text)
        self.assertIn("$target.Select()", self.text)
        self.assertIn("if($last -ceq $Expected){return $last}", self.text)
        self.assertIn("native_copy_focus_verified=$true", self.text)
        self.assertIn("ctrl_c_exact_clipboard=$true", self.text)
        self.assertIn("human_tested=$false", self.text)
        self.assertIn("nvda_verified=$false", self.text)


if __name__ == "__main__":
    unittest.main()
