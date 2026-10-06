from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "p0g_packaged_hotkey_result_probe.ps1"
WEB = ROOT / "web" / "index.html"
KEYMAP = ROOT / "web" / "keybindings.json"


class PackagedP0GHotkeyResultProbeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = PROBE.read_text(encoding="utf-8")
        cls.web = WEB.read_text(encoding="utf-8")
        cls.keymap = json.loads(KEYMAP.read_text(encoding="utf-8"))

    def test_probe_binds_claimed_sha_to_release_manifest_and_launched_exe_checksum(self) -> None:
        self.assertIn("function AssertExactPackageBinding", self.text)
        self.assertIn("RELEASE_MANIFEST.json", self.text)
        self.assertIn("SHA256SUMS.txt", self.text)
        self.assertIn("integration_sha mismatch", self.text)
        self.assertIn("AccessibleChess/AccessibleChess\\.exe", self.text)
        self.assertIn("Get-FileHash -LiteralPath $ExePath -Algorithm SHA256", self.text)
        self.assertIn("AssertExactPackageBinding $root $ProductSha $exe", self.text)
        self.assertIn("manifest_product_sha_verified=$true", self.text)
        self.assertIn("executable_checksum_verified=$true", self.text)
        self.assertLess(
            self.text.index("AssertExactPackageBinding $root $ProductSha $exe"),
            self.text.index("Start-Process -FilePath $exe"),
        )

    def test_checksum_counter_does_not_collide_with_powershell_matches_automatic_variable(self) -> None:
        # PowerShell variable names are case-insensitive. The -cmatch operator
        # writes the automatic $Matches hashtable, so a local $matches counter
        # becomes a Hashtable and $matches++ crashes the real packaged probe.
        self.assertIn("$checksumMatchCount=0", self.text)
        self.assertIn("$checksumMatchCount++", self.text)
        self.assertIn("if($checksumMatchCount -ne 1 -or -not $checksum)", self.text)
        self.assertNotIn("$matches=0", self.text.lower())
        self.assertNotIn("$matches++", self.text.lower())

    def test_probe_has_one_package_binding_and_one_executable_control_flow(self) -> None:
        self.assertEqual(1, self.text.count("function AssertExactPackageBinding"))
        self.assertEqual(1, self.text.count("function AssertLauncherFocus"))
        self.assertEqual(
            1,
            self.text.count("$process=Start-Process -FilePath $exe -WorkingDirectory $root -PassThru"),
        )
        self.assertEqual(1, self.text.count("AssertExactPackageBinding $root $ProductSha $exe"))
        self.assertEqual(1, self.text.count("manifest_product_sha_verified=$true"))
        self.assertEqual(1, self.text.count("executable_checksum_verified=$true"))

    def test_probe_launches_real_extracted_exe_and_uses_connected_provider_roots(self) -> None:
        self.assertIn("AccessibleChess.exe", self.text)
        self.assertIn("Start-Process -FilePath $exe", self.text)
        self.assertIn("ProviderRoots($Report)", self.text)
        self.assertIn("AutomationElement]::FromHandle", self.text)
        self.assertIn("ControlViewWalker", self.text)
        self.assertIn("provider_subtree_seen", self.text)
        self.assertNotIn("RootElement]::FindAll", self.text)
        self.assertNotIn("$desktop.FindAll", self.text)

    def test_probe_keeps_focus_outside_board_application_and_sends_native_alt_1_and_alt_2(self) -> None:
        self.assertIn("board-launcher", self.text)
        self.assertIn("AssertLauncherFocus $launcher", self.text)
        self.assertIn("AutomationElement]::FocusedElement", self.text)
        self.assertIn("hotkey_focus_path='board-launcher SetFocus outside role=application", self.text)
        self.assertIn("board_application_entered=$false", self.text)
        self.assertNotIn("Invoke $launcher", self.text)
        self.assertIn("AccessibleChessP0GKeys]::Alt", self.text)
        self.assertIn("@{index=1; key=0x31}", self.text)
        self.assertIn("@{index=2; key=0x32}", self.text)
        self.assertNotIn("dispatch_action", self.text)
        self.assertNotIn("keymap_resolve_binding", self.text)

    def test_probe_proves_packaged_process_is_foreground_native_key_target(self) -> None:
        self.assertIn("GetForegroundWindow", self.text)
        self.assertIn("GetWindowThreadProcessId", self.text)
        self.assertIn("ForegroundProcessId", self.text)
        self.assertIn("function ActivateProduct($Shell,$Process)", self.text)
        self.assertIn("if(-not $Shell.AppActivate($Process.Id))", self.text)
        self.assertIn("AccessibleChess.exe did not become the foreground native-key target", self.text)
        self.assertIn("function AssertProductForeground($Process)", self.text)
        self.assertIn("AssertProductForeground $process", self.text)
        self.assertIn("foreground_product_verified=$true", self.text)
        self.assertNotIn("$null=$shell.AppActivate($process.Id)", self.text)
        self.assertLess(
            self.text.index("AssertProductForeground $process"),
            self.text.index("[AccessibleChessP0GKeys]::Alt([byte]$case.key)"),
        )

    def test_probe_enables_stockfish_idempotently(self) -> None:
        self.assertIn("function EnsureEngineEnabled($EngineToggle)", self.text)
        self.assertIn("^(Увімкнути Stockfish|Enable Stockfish)$", self.text)
        self.assertIn("^(Вимкнути Stockfish|Disable Stockfish)$", self.text)
        self.assertIn("return 'enabled-by-probe'", self.text)
        self.assertIn("return 'already-enabled'", self.text)
        self.assertIn("$engineState=EnsureEngineEnabled $engineToggle", self.text)
        self.assertIn("engine_enable_state=$engineState", self.text)
        self.assertNotIn("Invoke $engineToggle 'engine-toggle'\n\n", self.text)

    def test_shipping_routes_alt_variations_only_through_analysis_context_outside_board(self) -> None:
        actions = {item["id"]: item for item in self.keymap["actions"]}
        self.assertEqual(actions["analysis.pv1"]["binding"], "Alt+1")
        self.assertEqual(actions["analysis.pv1"]["registryContext"], "analysis")
        self.assertEqual(actions["analysis.pv2"]["binding"], "Alt+2")
        self.assertEqual(actions["analysis.pv2"]["registryContext"], "analysis")
        self.assertIn("if(e.target.closest('#board-application'))return", self.web)
        self.assertIn("resolveBinding(eventChord(e),'board','board')", self.web)
        self.assertIn("resolveBinding(chord,'analysis','analysis')", self.web)

    def test_probe_proves_causal_action_state_separately_from_accessible_result(self) -> None:
        self.assertIn("function FindVariationButton($Roots,[int]$Index)", self.text)
        self.assertIn("function SelectedVariation($Roots,[int]$Index)", self.text)
        self.assertIn("TogglePattern]::Pattern", self.text)
        self.assertIn("ToggleState]::On", self.text)
        self.assertIn("$opposite=if($index -eq 1){2}else{1}", self.text)
        self.assertIn(
            "$preconditionMode=ActivateVariationPrecondition $roots $preconditionButton $opposite $shell $process",
            self.text,
        )
        self.assertIn("Could not establish opposite variation $opposite before Alt+$index", self.text)
        self.assertIn("Alt+$index did not change packaged selected state from variation $opposite", self.text)
        self.assertIn("$preconditionStates += $precondition", self.text)
        self.assertIn("$selectedStates += $selected", self.text)
        self.assertIn("alt_1_precondition_selected_state=$preconditionStates[0]", self.text)
        self.assertIn("alt_2_precondition_selected_state=$preconditionStates[1]", self.text)
        self.assertIn("alt_1_selected_state=$selectedStates[0]", self.text)
        self.assertIn("alt_2_selected_state=$selectedStates[1]", self.text)
        self.assertLess(
            self.text.index("$preconditionMode=ActivateVariationPrecondition"),
            self.text.index("[AccessibleChessP0GKeys]::Alt([byte]$case.key)"),
        )
        self.assertLess(
            self.text.index("SelectedVariation $roots $index"),
            self.text.index("Alt+$index did not expose a matching live-region result"),
        )


    def test_variation_precondition_falls_back_only_to_real_native_enter_when_invoke_unsupported(self) -> None:
        self.assertIn("function ActivateVariationPrecondition($Roots,$Button,[int]$Index,$Shell,$Process)", self.text)
        self.assertIn("$name -notmatch $expected", self.text)
        self.assertIn(r'$expected="^(Варіант|Variant)\s+$Index\."', self.text)
        self.assertNotIn(r'(Варіант|Variant)\\s+', self.text)
        self.assertIn("if(-not [bool]$Button.Current.IsEnabled)", self.text)
        self.assertIn("$targetRuntime=RuntimeId $Button", self.text)
        self.assertIn("$Button.TryGetCurrentPattern(", self.text)
        self.assertIn("[System.Windows.Automation.InvokePattern]::Pattern,[ref]$invokePattern", self.text)
        self.assertIn("if($hasInvoke -and $null -ne $invokePattern)", self.text)
        self.assertIn("$invokePattern.Invoke()", self.text)
        self.assertIn("return 'uia-invoke'", self.text)
        self.assertIn("if(-not [bool]$Button.Current.IsKeyboardFocusable)", self.text)
        self.assertIn("$Button.SetFocus()", self.text)
        self.assertIn("(RuntimeId $focus) -ceq $targetRuntime", self.text)
        self.assertIn("2500 \"analysis variation $Index could not receive exact native keyboard focus\"", self.text)
        self.assertIn("AssertProductForeground $Process", self.text)
        self.assertIn("[AccessibleChessP0GKeys]::Enter()", self.text)
        self.assertIn("return 'native-enter'", self.text)
        self.assertLess(
            self.text.index("if(-not [bool]$Button.Current.IsEnabled)"),
            self.text.index("[AccessibleChessP0GKeys]::Enter()"),
        )
        self.assertLess(
            self.text.index("$Button.SetFocus()"),
            self.text.index("[AccessibleChessP0GKeys]::Enter()"),
        )
        self.assertIn("Could not find enabled opposite variation", self.text)
        self.assertIn("SelectedVariation $roots $opposite", self.text)
        self.assertLess(
            self.text.index("$preconditionMode=ActivateVariationPrecondition"),
            self.text.index("SelectedVariation $roots $opposite"),
        )
        self.assertIn("alt_1_precondition_activation=$preconditionModes[0]", self.text)
        self.assertIn("alt_2_precondition_activation=$preconditionModes[1]", self.text)
        self.assertNotIn("dispatch_action", self.text)
        self.assertNotIn(".click()", self.text)

    def test_shipping_live_region_retains_status_and_atomic_polite_semantics(self) -> None:
        self.assertIn(
            '<div id="live" role="status" aria-live="polite" '
            'aria-atomic="true" aria-relevant="text"></div>',
            self.web,
        )

    def test_probe_requires_accessible_result_semantics_not_handler_execution_only(self) -> None:
        self.assertIn("Accessible status live region #live", self.text)
        self.assertIn("Alt+$index did not expose a matching live-region result", self.text)
        self.assertIn("result does not identify the selected variation", self.text)
        self.assertIn("result omits analysis depth", self.text)
        self.assertIn("result omits evaluation", self.text)
        self.assertIn("raw provider/debug text", self.text)
        self.assertIn("alt_1_action_occurred=$true", self.text)
        self.assertIn("alt_1_accessible_result_exposed=$true", self.text)
        self.assertIn("alt_2_action_occurred=$true", self.text)
        self.assertIn("alt_2_accessible_result_exposed=$true", self.text)


    def test_live_region_readback_scopes_raw_text_to_same_status_root(self) -> None:
        self.assertIn("function SemanticTexts($Element)", self.text)
        self.assertIn("TreeWalker]::RawViewWalker", self.text)
        self.assertIn("$pending.Enqueue(@{element=$Element; depth=0})", self.text)
        self.assertIn("$traversed -lt 32", self.text)
        self.assertIn("if($node.depth -ge 3)", self.text)
        self.assertIn("if($type -eq 'ControlType.Text')", self.text)
        self.assertIn("$liveRuntime=RuntimeId $live", self.text)
        self.assertIn("Accessible status live region identity changed before hotkey", self.text)
        self.assertIn("Accessible status live region identity changed after hotkey", self.text)
        self.assertIn("$priorLiveTexts=@(SemanticTexts $live)", self.text)
        self.assertIn("$value -cnotin $priorLiveTexts", self.text)
        self.assertIn('12000 "Alt+$index did not expose a matching live-region result"', self.text)
        self.assertIn("P0G_LIVE_REGION_FAILURE", self.text)
        self.assertIn("function BoundedTextUnits([string]$Value)", self.text)
        self.assertIn("AssertCleanAnnouncement $text $index", self.text)
        self.assertNotIn("SemanticText $engine-status", self.text)
        self.assertNotIn("dispatch_action", self.text)

    def test_probe_is_bounded_and_does_not_claim_human_nvda_acceptance(self) -> None:
        self.assertIn("TimeoutSeconds = 60", self.text)
        self.assertIn("Provider-root traversal cap reached", self.text)
        self.assertIn("human_tested=$false", self.text)
        self.assertIn("nvda_verified=$false", self.text)
        self.assertIn("packaged-p0g-hotkey-result-summary.json", self.text)
        self.assertIn("Local path leaked into P0-G evidence", self.text)


if __name__ == "__main__":
    unittest.main()
