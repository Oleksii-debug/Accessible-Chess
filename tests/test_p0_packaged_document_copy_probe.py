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
