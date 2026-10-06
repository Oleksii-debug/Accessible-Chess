from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_p0_packaged_acceptance.ps1"


class P0PackagedAcceptanceOrchestratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_orchestrator_uses_exact_product_and_shared_topology_inputs(self) -> None:
        self.assertIn("[Parameter(Mandatory=$true)][string]$ProductRoot", self.text)
        self.assertIn("[Parameter(Mandatory=$true)][string]$ProductSha", self.text)
        self.assertIn("stage1_uia_topology_v5.ps1", self.text)
        self.assertIn("ProductSha must be one exact 40-hex integration commit", self.text)

    def test_copy_binding_precedes_starter_and_hotkey_acceptance(self) -> None:
        copy_probe = self.text.index("P0_PACKAGED_ACCEPTANCE_PHASE=COPY_PROBE")
        copy_verify = self.text.index("P0_PACKAGED_ACCEPTANCE_PHASE=COPY_VERIFY")
        starter = self.text.index("P0_PACKAGED_ACCEPTANCE_PHASE=STARTER_DIAGNOSTIC")
        hotkey_probe = self.text.index("P0_PACKAGED_ACCEPTANCE_PHASE=HOTKEY_PROBE")
        hotkey_verify = self.text.index("P0_PACKAGED_ACCEPTANCE_PHASE=HOTKEY_VERIFY")
        final_reverify = self.text.index("P0_PACKAGED_ACCEPTANCE_PHASE=FINAL_REVERIFY")
        final_pass = self.text.index(
            "P0 PACKAGED ACCEPTANCE VERIFIED: COPY + STARTER + HOTKEY RESULTS"
        )
        self.assertLess(copy_probe, copy_verify)
        self.assertLess(copy_verify, starter)
        self.assertLess(starter, hotkey_probe)
        self.assertLess(hotkey_probe, hotkey_verify)
        self.assertLess(hotkey_verify, final_reverify)
        self.assertLess(final_reverify, final_pass)

    def test_starter_reachability_uses_packaged_executable_diagnostic(self) -> None:
        self.assertIn("Join-Path $product 'AccessibleChess.exe'", self.text)
        self.assertIn("Join-Path $product 'release-content\\w2-starter'", self.text)
        self.assertIn("@(& $exe --diagnostic 2>&1)", self.text)
        self.assertIn("if($diagnosticExit -ne 0)", self.text)
        self.assertIn("P0-F PACKAGED W2 LIBRARY DIAGNOSTIC PASS", self.text)
        self.assertIn("P0_PACKAGED_STARTER_REACHABILITY=VERIFIED", self.text)
        self.assertIn("Packaged P0-F W2 starter root is missing", self.text)
        self.assertIn(
            "Packaged P0-F diagnostic did not prove W2 Library reachability",
            self.text,
        )

    def test_orchestrator_reuses_incumbent_probes_and_verifiers(self) -> None:
        for path in (
            "scripts/p0_packaged_document_copy_probe.ps1",
            "scripts/p0g_packaged_hotkey_result_probe.ps1",
            "scripts/verify_p0_packaged_document_copy_evidence.py",
            "scripts/verify_p0g_packaged_hotkey_result_evidence.py",
        ):
            self.assertIn(path, self.text)
            self.assertTrue((ROOT / path).is_file(), path)

    def test_probe_scripts_rely_on_terminating_errors_not_native_last_exit_code(self) -> None:
        copy_start = self.text.index("& $copyProbe")
        copy_evidence = self.text.index(
            "if(-not (Test-Path -LiteralPath $copyEvidence", copy_start
        )
        self.assertNotIn("LASTEXITCODE", self.text[copy_start:copy_evidence])
        hotkey_start = self.text.index("& $hotkeyProbe")
        hotkey_evidence = self.text.index(
            "if(-not (Test-Path -LiteralPath $hotkeyEvidence", hotkey_start
        )
        self.assertNotIn("LASTEXITCODE", self.text[hotkey_start:hotkey_evidence])
        self.assertIn("if($LASTEXITCODE -ne 0)", self.text)

    def test_final_reverification_rechecks_both_evidence_files_and_shas(self) -> None:
        final_reverify = self.text.index("P0_PACKAGED_ACCEPTANCE_PHASE=FINAL_REVERIFY")
        final_pass = self.text.index(
            "P0 PACKAGED ACCEPTANCE VERIFIED: COPY + STARTER + HOTKEY RESULTS"
        )
        tail = self.text[final_reverify:final_pass]
        self.assertIn(
            "Invoke-PythonVerifier $copyVerifier $copyEvidence $product $ProductSha",
            tail,
        )
        self.assertIn(
            "Invoke-PythonVerifier $hotkeyVerifier $hotkeyEvidence $product $ProductSha",
            tail,
        )
        self.assertIn("$copy.product_sha", tail)
        self.assertIn("$hotkey.product_sha", tail)
        self.assertIn("Document-copy evidence SHA changed", tail)
        self.assertIn("P0-G evidence SHA changed", tail)

    def test_machine_acceptance_flags_are_required_exact_false_booleans(self) -> None:
        self.assertIn("function Assert-NoMachineHumanClaim", self.text)
        self.assertIn("$Evidence.PSObject.Properties[$name]", self.text)
        self.assertIn("$null -eq $property", self.text)
        self.assertIn("$property.Value -isnot [bool]", self.text)
        self.assertIn("$property.Value -ne $false", self.text)
        self.assertIn("machine evidence must explicitly declare $name=false", self.text)
        self.assertNotIn("$copy.human_tested", self.text)
        self.assertNotIn("$copy.nvda_verified", self.text)

    def test_stale_evidence_is_removed_before_run(self) -> None:
        self.assertIn("Remove-Item -LiteralPath $copyEvidence,$hotkeyEvidence", self.text)
        self.assertIn("semantic document-copy evidence was not produced", self.text)
        self.assertIn("P0-G hotkey-result evidence was not produced", self.text)


if __name__ == "__main__":
    unittest.main()
