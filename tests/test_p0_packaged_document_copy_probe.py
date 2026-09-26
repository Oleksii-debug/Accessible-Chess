from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "p0_packaged_document_copy_probe.ps1"


class PackagedDocumentCopyProbeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = PROBE.read_text(encoding="utf-8")

    def test_probe_uses_retained_provider_roots_not_desktop_document_search(self) -> None:
        self.assertIn("ProviderRoots($Report)", self.text)
        self.assertIn("AutomationElement]::FromHandle", self.text)
        self.assertIn("ControlViewWalker", self.text)
        self.assertIn("source_root_connected", self.text)
        self.assertIn("provider_subtree_seen", self.text)
        self.assertNotIn("RootElement]::FindAll", self.text)
        self.assertNotIn("$desktop.FindAll", self.text)

    def test_probe_selects_a_usable_connected_document_not_just_the_first(self) -> None:
        self.assertIn("foreach($candidate in $documents)", self.text)
        self.assertIn("$candidate.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)", self.text)
        self.assertIn("$candidatePattern.SupportedTextSelection", self.text)
        self.assertIn("$candidateRange.FindText('Інформація про гру'", self.text)
        self.assertIn("$candidateRange.FindText('Game information'", self.text)
        self.assertIn("none exposes selectable stable static text", self.text)
        self.assertNotIn("$document=$documents[0]", self.text)

    def test_probe_retains_real_textpattern_selection_and_native_copy(self) -> None:
        self.assertIn("TextPattern]::Pattern", self.text)
        self.assertIn("$target.Select()", self.text)
        self.assertIn("AccessibleChessCopyKeys]::Ctrl([byte]0x43)", self.text)
        self.assertIn("WaitClipboard $selected", self.text)
        self.assertIn("move-input", self.text)
        self.assertIn("ValuePattern]::Pattern", self.text)
        self.assertIn("WaitClipboard 'e2e4'", self.text)

    def test_probe_fails_closed_if_native_copy_focus_leaves_connected_provider_roots(self) -> None:
        self.assertIn("function AssertProviderFocus", self.text)
        self.assertIn("AutomationElement]::FocusedElement", self.text)
        self.assertIn("$focusedRuntime=RuntimeId $focused", self.text)
        self.assertIn("focused element has no stable UIA runtime identity", self.text)
        self.assertIn("foreach($candidate in @(ControlElements $Roots))", self.text)
        self.assertIn("native keyboard focus escaped connected packaged provider roots", self.text)
        self.assertIn("Accessible Chess Document could not receive focus for native Ctrl+C", self.text)
        self.assertIn("Static document copy focus landed in an edit control", self.text)
        self.assertIn("AssertProviderFocus $roots 'static document copy'", self.text)
        self.assertIn("AssertProviderFocus $roots 'static document copy dispatch'", self.text)
        self.assertIn("AssertProviderFocus $roots 'move input copy' 'move-input'", self.text)
        self.assertIn("AssertProviderFocus $roots 'move input copy dispatch' 'move-input'", self.text)
        self.assertIn("native_copy_focus_verified=$true", self.text)
        self.assertIn("move_input_focus_verified=$true", self.text)
        self.assertIn("focus_ownership='focused UIA runtime identity must belong to retained connected provider-root ControlView'", self.text)
        self.assertNotIn("function AssertAppFocus", self.text)
        self.assertNotIn("[int]$focused.Current.ProcessId -ne [int]$Process.Id", self.text)
        self.assertNotIn("try {$document.SetFocus()} catch {}", self.text)

    def test_probe_requires_case_sensitive_exact_clipboard_equality(self) -> None:
        self.assertIn("if($last -ceq $Expected){return $last}", self.text)
        self.assertNotIn("$last.Trim() -eq $Expected.Trim()", self.text)
        self.assertIn("clipboard_equality='case-sensitive exact string equality'", self.text)

    def test_probe_records_document_provider_identity_without_claiming_nvda(self) -> None:
        self.assertIn("document_process_id=[int]$document.Current.ProcessId", self.text)
        self.assertIn("launched_process_id=$process.Id", self.text)
        self.assertIn("human_tested=$false", self.text)
        self.assertIn("nvda_verified=$false", self.text)

    def test_probe_is_bounded_and_rejects_local_paths(self) -> None:
        self.assertIn("TimeoutSeconds = 45", self.text)
        self.assertIn("packaged-v2-document-copy-summary.json", self.text)
        self.assertIn("Local path leaked into document-copy evidence", self.text)
        self.assertIn("$bounded.Contains(':\\')", self.text)
        self.assertIn("(?i)/home/|/Users/|/tmp/", self.text)
        self.assertNotIn("[A-Z]:\\\\", self.text)


if __name__ == "__main__":
    unittest.main()
