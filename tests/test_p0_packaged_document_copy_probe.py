from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "p0_packaged_document_copy_probe.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "p0-packaged-document-copy-probe-contract.yml"


class PackagedDocumentCopyProbeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = PROBE.read_text(encoding="utf-8")

    def test_contract_resolves_textpattern_endpoint_enum_at_runtime_on_windows(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Resolve UIAutomation TextPattern endpoint enum on Windows", workflow)
        self.assertIn("if: runner.os == 'Windows'", workflow)
        self.assertIn("Add-Type -AssemblyName UIAutomationClient", workflow)
        self.assertIn("Add-Type -AssemblyName UIAutomationTypes", workflow)
        self.assertIn(
            "$start=[System.Windows.Automation.Text.TextPatternRangeEndpoint]::Start",
            workflow,
        )
        self.assertIn(
            "$end=[System.Windows.Automation.Text.TextPatternRangeEndpoint]::End",
            workflow,
        )
        self.assertIn("UIAUTOMATION_TEXTPATTERN_RANGE_ENDPOINT_RUNTIME=PASS", workflow)
        self.assertNotIn(
            "$start=[System.Windows.Automation.TextPatternRangeEndpoint]::Start",
            workflow,
        )

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
        self.assertEqual(1, self.text.count("AssertExactPackageBinding $root $ProductSha $exe"))
        self.assertEqual(
            1,
            self.text.count("$process=Start-Process -FilePath $exe -WorkingDirectory $root -PassThru"),
        )
        self.assertEqual(1, self.text.count("manifest_product_sha_verified=$true"))
        self.assertEqual(1, self.text.count("executable_checksum_verified=$true"))
        self.assertNotIn("40}  $focused=", self.text)

    def test_probe_uses_retained_provider_roots_not_desktop_document_search(self) -> None:
        self.assertIn("ProviderRoots($Report)", self.text)
        self.assertIn("AutomationElement]::FromHandle", self.text)
        self.assertIn("ControlViewWalker", self.text)
        self.assertIn("source_root_connected", self.text)
        self.assertIn("provider_subtree_seen", self.text)
        self.assertNotIn("RootElement]::FindAll", self.text)
        self.assertNotIn("$desktop.FindAll", self.text)

    def test_probe_requires_one_usable_connected_document_not_just_the_first(self) -> None:
        self.assertIn("$usableDocuments=@()", self.text)
        self.assertIn("foreach($candidate in $documents)", self.text)
        self.assertIn("$candidate.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)", self.text)
        self.assertIn("$candidatePattern.SupportedTextSelection", self.text)
        self.assertIn("$candidateElements=ControlElements @($candidate)", self.text)
        self.assertIn("foreach($phrase in @('Розділи','Sections','Accessible Chess','Інформація про гру','Game information','Список ходів'))", self.text)
        self.assertLess(
            self.text.index("'Розділи','Sections'"),
            self.text.index("'Accessible Chess','Інформація про гру'"),
        )
        self.assertIn("$name -ceq $phrase", self.text)
        self.assertIn("$type -eq 'ControlType.Header'", self.text)
        self.assertIn("$type -eq 'ControlType.Text'", self.text)
        self.assertIn("$isOnscreen=-not [bool]$_.Current.IsOffscreen", self.text)
        self.assertIn("$isOnscreen -and", self.text)
        self.assertIn("[double]$bounds.Width -gt 0", self.text)
        self.assertIn("[double]$bounds.Height -gt 0", self.text)
        self.assertIn("if($namedTargets.Count -ne 1){continue}", self.text)
        self.assertIn("$probeRange=$candidatePattern.RangeFromChild($namedTargets[0])", self.text)
        self.assertIn("$probeText=[string]$probeRange.GetText(-1)", self.text)
        self.assertIn("if($probeText -cne $phrase){continue}", self.text)
        self.assertIn('if($probeText.Contains("`r") -or $probeText.Contains("`n")){continue}', self.text)
        self.assertIn("target_phrase=$candidatePhrase", self.text)
        self.assertIn("target_control_type=$candidateTargetType", self.text)
        self.assertIn("none exposes selectable stable static text", self.text)
        self.assertIn("if($usableDocuments.Count -ne 1)", self.text)
        self.assertIn("Ambiguous selectable Accessible Chess Documents", self.text)
        self.assertIn("expected exactly one stable packaged document provider", self.text)
        self.assertIn(
            "document_provider_cardinality='exactly one selectable Accessible Chess document containing one exact visible static UIA child target'",
            self.text,
        )
        self.assertIn(
            "static_document_range_source='TextPattern.RangeFromChild exact named visible static UIA child'",
            self.text,
        )
        self.assertNotIn(".FindText(", self.text)
        self.assertNotIn("$document=$documents[0]", self.text)
        self.assertNotIn("$document=$candidate", self.text)

    def test_native_document_home_navigation_precedes_static_range_discovery(self) -> None:
        # Startup brings Move Input onscreen. Only a real document-key gesture
        # may restore the upper static headings before choosing a copy target.
        self.assertIn("$navigationDocument=$documents[0]", self.text)
        self.assertIn("$navigationRuntime=RuntimeId $navigationDocument", self.text)
        self.assertIn("$navigationDocument.SetFocus()", self.text)
        self.assertIn("AssertProviderFocus $roots 'native document Ctrl+Home'", self.text)
        self.assertIn("Native document Ctrl+Home focus landed in an edit control", self.text)
        self.assertIn("AssertProductForeground $process 'native document Ctrl+Home'", self.text)
        self.assertIn("[AccessibleChessCopyKeys]::Ctrl([byte]0x24)", self.text)
        self.assertIn("$navigationWatch.ElapsedMilliseconds -lt 3500", self.text)
        self.assertIn("Connected document identity changed during native Ctrl+Home navigation", self.text)
        self.assertIn("$navigationPhrases -ccontains $name", self.text)
        self.assertIn("P0_NATIVE_DOCUMENT_HOME_NAVIGATION=NO_VISIBLE_EXACT_STATIC_TARGET", self.text)
        self.assertIn("$documents=$currentDocuments", self.text)
        self.assertLess(
            self.text.index("[AccessibleChessCopyKeys]::Ctrl([byte]0x24)"),
            self.text.index("$usableDocuments=@()"),
        )
        self.assertLess(
            self.text.index("$documents=$currentDocuments"),
            self.text.index("$probeRange=$candidatePattern.RangeFromChild($namedTargets[0])"),
        )
        self.assertLess(
            self.text.index("$isOnscreen=-not [bool]$_.Current.IsOffscreen"),
            self.text.index("$probeRange=$candidatePattern.RangeFromChild($namedTargets[0])"),
        )
        self.assertLess(
            self.text.index("$target.Select()"),
            self.text.index("[AccessibleChessCopyKeys]::Ctrl([byte]0x43)"),
        )

    def test_static_target_discovery_rejects_offscreen_before_range_selection(self) -> None:
        # An off-route heading can retain nonzero bounds but never become visible
        # through ScrollIntoView; prefer a currently onscreen exact static target.
        self.assertIn("$isOnscreen=-not [bool]$_.Current.IsOffscreen", self.text)
        self.assertIn("$isOnscreen -and", self.text)
        self.assertLess(
            self.text.index("$isOnscreen=-not [bool]$_.Current.IsOffscreen"),
            self.text.index("$probeRange=$candidatePattern.RangeFromChild($namedTargets[0])"),
        )
        self.assertIn("P0_STATIC_SELECTED_TARGET phrase_code_units=", self.text)
        self.assertIn("foreach($diagnosticLine in @($staticTargetDiagnostics))", self.text)
        self.assertIn("if($usableDocuments.Count -eq 0)", self.text)
        self.assertIn("if($usableDocuments.Count -ne 1)", self.text)
        self.assertIn("$visibilityEvidence=AssertVisibleTextRange $target $usableDocuments[0].target_element", self.text)
        self.assertLess(
            self.text.index("$visibilityEvidence=AssertVisibleTextRange $target $usableDocuments[0].target_element"),
            self.text.index("$target.Select()"),
        )

    def test_probe_retains_real_textpattern_selection_and_native_copy(self) -> None:
        self.assertIn("TextPattern]::Pattern", self.text)
        self.assertIn("function AssertVisibleTextRange", self.text)
        self.assertIn("$Range.GetBoundingRectangles()", self.text)
        self.assertIn("$Range.GetEnclosingElement()", self.text)
        self.assertIn("function AssertVisibleTextRange($Range,$TargetElement)", self.text)
        self.assertNotIn("System.Collections.Generic.List[object]", self.text)
        self.assertIn("$enclosing=$null", self.text)
        self.assertIn("$enclosing=$Range.GetEnclosingElement()", self.text)
        self.assertIn("$enclosing.Current.IsOffscreen", self.text)
        self.assertIn("$enclosing.Current.BoundingRectangle", self.text)
        self.assertIn("$TargetElement.Current.IsOffscreen", self.text)
        self.assertIn("$TargetElement.Current.BoundingRectangle", self.text)
        self.assertIn("return 'text-range'", self.text)
        self.assertIn("return 'enclosing-element'", self.text)
        self.assertIn("return 'target-element'", self.text)
        self.assertIn("$target.ScrollIntoView($true)", self.text)
        self.assertIn("$visibilityEvidence=AssertVisibleTextRange $target $usableDocuments[0].target_element", self.text)
        self.assertIn("static_text_visible_rectangle=($visibilityEvidence -eq 'text-range')", self.text)
        self.assertIn("static_text_visibility_evidence=$visibilityEvidence", self.text)
        self.assertLess(
            self.text.index("$visibilityEvidence=AssertVisibleTextRange $target $usableDocuments[0].target_element"),
            self.text.index("$target.Select()"),
        )
        self.assertIn("$target.Select()", self.text)
        self.assertIn("$textPattern.GetSelection()", self.text)
        self.assertIn("$activeSelection.CompareEndpoints(", self.text)
        self.assertIn(
            "[System.Windows.Automation.Text.TextPatternRangeEndpoint]::Start",
            self.text,
        )
        self.assertIn(
            "[System.Windows.Automation.Text.TextPatternRangeEndpoint]::End",
            self.text,
        )
        self.assertNotIn(
            "[System.Windows.Automation.TextPatternRangeEndpoint]",
            self.text,
        )
        self.assertIn("textpattern_target_selected=$true", self.text)
        self.assertIn(
            "textpattern_selection_equality='UIA exact range endpoints and case-sensitive text equality'",
            self.text,
        )
        self.assertLess(
            self.text.index("$target.Select()"),
            self.text.index("$textPattern.GetSelection()"),
        )
        self.assertLess(
            self.text.index("$textPattern.GetSelection()"),
            self.text.index("Set-Clipboard -Value 'P0_COPY_STATIC_SENTINEL'"),
        )
        self.assertIn("AccessibleChessCopyKeys]::Ctrl([byte]0x43)", self.text)
        self.assertIn("WaitClipboard $selected", self.text)
        self.assertIn("move-input", self.text)
        self.assertIn("ValuePattern]::Pattern", self.text)
        self.assertIn("WaitClipboard 'e2e4'", self.text)

    def test_visibility_fallback_keeps_provider_geometry_fail_closed(self) -> None:
        self.assertIn("catch {$rectangles=@()}", self.text)
        self.assertIn("target_element=$namedTargets[0]", self.text)
        self.assertNotIn("System.Collections.Generic.List[object]", self.text)
        self.assertIn("try {$enclosing=$Range.GetEnclosingElement()} catch {$enclosing=$null}", self.text)
        self.assertIn("if($null -ne $enclosing)", self.text)
        self.assertIn("if(-not [bool]$enclosing.Current.IsOffscreen)", self.text)
        self.assertIn("$bounds=$enclosing.Current.BoundingRectangle", self.text)
        self.assertIn("if($null -ne $TargetElement)", self.text)
        self.assertIn("if(-not [bool]$TargetElement.Current.IsOffscreen)", self.text)
        self.assertIn("$bounds=$TargetElement.Current.BoundingRectangle", self.text)
        self.assertIn("if($width -gt 0 -and $height -gt 0)", self.text)
        self.assertIn("return 'target-element'", self.text)
        self.assertIn("no onscreen positive-area UIA element", self.text)
        self.assertLess(
            self.text.index("$visibilityEvidence=AssertVisibleTextRange $target $usableDocuments[0].target_element"),
            self.text.index("$target.Select()"),
        )
        self.assertIn("$activeSelection.CompareEndpoints(", self.text)
        self.assertIn("WaitClipboard $selected", self.text)

    def test_visibility_settling_is_bounded_and_keeps_exact_target_identity(self) -> None:
        self.assertIn("$targetRuntime=RuntimeId $usableDocuments[0].target_element", self.text)
        self.assertIn("if(-not $targetRuntime)", self.text)
        self.assertIn("$visibilityWatch=[System.Diagnostics.Stopwatch]::StartNew()", self.text)
        self.assertIn("$visibilityWatch.ElapsedMilliseconds -ge 2500", self.text)
        self.assertIn("Start-Sleep -Milliseconds 100", self.text)
        self.assertIn("(RuntimeId $usableDocuments[0].target_element) -cne $targetRuntime", self.text)
        self.assertIn("[string]$target.GetText(-1) -cne $selected", self.text)
        self.assertIn("$visibilityEvidence=AssertVisibleTextRange $target $usableDocuments[0].target_element", self.text)
        self.assertIn("P0_STATIC_VISIBILITY_FAILURE range_coordinate_count=", self.text)
        self.assertIn("target_initial_offscreen=", self.text)
        self.assertIn("target_final_offscreen=", self.text)
        self.assertIn("enclosing_offscreen=", self.text)
        self.assertIn("throw", self.text)
        self.assertLess(self.text.index("$target.ScrollIntoView($true)"),
                        self.text.index("$visibilityWatch=[System.Diagnostics.Stopwatch]::StartNew()"))
        self.assertLess(self.text.index("$visibilityWatch=[System.Diagnostics.Stopwatch]::StartNew()"),
                        self.text.index("$target.Select()"))
        self.assertIn("WaitClipboard $selected", self.text)

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

    def test_final_static_copy_stays_on_exact_connected_document_focus(self) -> None:
        self.assertIn(
            "$staticDispatchFocus=AssertProviderFocus $roots 'static document copy dispatch'",
            self.text,
        )
        self.assertIn(
            "(RuntimeId $staticDispatchFocus) -cne $navigationRuntime",
            self.text,
        )
        self.assertIn(
            "Static document copy dispatch focus is not the connected document",
            self.text,
        )
        self.assertIn(
            "$staticPostCopyFocus=AssertProviderFocus $roots 'static document copy post-dispatch'",
            self.text,
        )
        self.assertIn(
            "(RuntimeId $staticPostCopyFocus) -cne $navigationRuntime",
            self.text,
        )
        self.assertIn(
            "Static document copy focus changed during native Ctrl+C",
            self.text,
        )
        dispatch = self.text.index(
            "$staticDispatchFocus=AssertProviderFocus $roots 'static document copy dispatch'"
        )
        copy = self.text.index("[AccessibleChessCopyKeys]::Ctrl([byte]0x43)", dispatch)
        post = self.text.index(
            "$staticPostCopyFocus=AssertProviderFocus $roots 'static document copy post-dispatch'",
            copy,
        )
        verify = self.text.index("WaitClipboard $selected", post)
        self.assertLess(dispatch, copy)
        self.assertLess(copy, post)
        self.assertLess(post, verify)

    def test_native_copy_is_bound_to_foreground_packaged_process(self) -> None:
        self.assertIn("GetForegroundWindow", self.text)
        self.assertIn("GetWindowThreadProcessId", self.text)
        self.assertIn("function ActivateProduct($Shell,$Process,[string]$Phase)", self.text)
        self.assertIn("if(-not $Shell.AppActivate($Process.Id))", self.text)
        self.assertIn("function AssertProductForeground($Process,[string]$Phase)", self.text)
        self.assertIn("foreground_product_verified=$true", self.text)
        self.assertNotIn("$null=$shell.AppActivate($process.Id)", self.text)

        static_assert = self.text.index("AssertProductForeground $process 'static document copy dispatch'")
        # A failure-only diagnostic copy may precede the accepted path. Bind
        # the foreground assertion to the accepted path's *own* native Ctrl+C.
        static_copy = self.text.index("[AccessibleChessCopyKeys]::Ctrl([byte]0x43)", static_assert)
        self.assertLess(static_assert, static_copy)

        edit_assert = self.text.index("AssertProductForeground $process 'move input copy dispatch'")
        edit_select = self.text.index("[AccessibleChessCopyKeys]::Ctrl([byte]0x41)")
        edit_reassert = self.text.index("AssertProductForeground $process 'move input copy dispatch after Ctrl+A'")
        edit_focus_reassert = self.text.index(
            "AssertProviderFocus $roots 'move input copy dispatch after Ctrl+A' 'move-input'"
        )
        edit_copy = self.text.index("[AccessibleChessCopyKeys]::Ctrl([byte]0x43)", static_copy + 1)
        self.assertLess(edit_assert, edit_select)
        self.assertLess(edit_select, edit_reassert)
        self.assertLess(edit_reassert, edit_focus_reassert)
        self.assertLess(edit_focus_reassert, edit_copy)

    def test_probe_requires_exact_single_line_static_target_before_native_copy(self) -> None:
        self.assertIn("$targetPhrase=[string]$usableDocuments[0].target_phrase", self.text)
        self.assertIn("if($selected -cne $targetPhrase)", self.text)
        self.assertIn('if($selected.Contains("`r") -or $selected.Contains("`n"))', self.text)
        self.assertIn("static_document_target_phrase=$targetPhrase", self.text)
        self.assertNotIn("Replace(\"`r`n\", \"`n\")", self.text)
        self.assertNotIn(".Trim() -eq", self.text)

    def test_probe_preserves_exact_textpattern_range_whitespace_for_native_copy(self) -> None:
        self.assertIn("$selected=[string]$target.GetText(-1)", self.text)
        self.assertIn("if(-not $selected.Trim()){throw 'Static TextPattern target is empty'}", self.text)
        self.assertNotIn("$selected=([string]$target.GetText(-1)).Trim()", self.text)
        self.assertIn("$targetText=[string]$target.GetText(-1)", self.text)
        self.assertIn("if($activeSelectedText -cne $targetText)", self.text)
        self.assertIn("WaitClipboard $selected", self.text)
        self.assertLess(
            self.text.index("$selected=[string]$target.GetText(-1)"),
            self.text.index("$target.Select()"),
        )
        self.assertLess(
            self.text.index("$target.Select()"),
            self.text.index("WaitClipboard $selected"),
        )

    def test_probe_requires_case_sensitive_exact_clipboard_equality(self) -> None:
        self.assertIn("if($last -ceq $Expected){return $last}", self.text)
        self.assertNotIn("$last.Trim() -eq $Expected.Trim()", self.text)
        self.assertIn("clipboard_equality='case-sensitive exact string equality'", self.text)

    def test_exact_clipboard_failure_reports_utf16_mismatch_without_weakening_equality(self) -> None:
        self.assertIn("function ClipboardCodeUnits", self.text)
        self.assertIn("expected_length=$($Expected.Length)", self.text)
        self.assertIn("actual_length=$($last.Length)", self.text)
        self.assertIn("first_mismatch_index=$mismatch", self.text)
        self.assertIn("expected_code_units='$expectedUnits'", self.text)
        self.assertIn("actual_code_units='$actualUnits'", self.text)
        self.assertIn("if([int][char]$Expected[$index] -ne [int][char]$last[$index])", self.text)
        self.assertIn("if($last -ceq $Expected){return $last}", self.text)
        self.assertNotIn("$last.Trim() -eq $Expected.Trim()", self.text)

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


    def test_endpoint_failure_differential_keeps_native_copy_gate_fail_closed(self) -> None:
        # Distinguish stale RangeFromChild projections from UIA provider
        # selection normalization without accepting either as an exact match.
        self.assertIn("function RangeEndpointDiagnostic($Left,$Right)", self.text)
        self.assertIn("$preSelectClone=$target.Clone()", self.text)
        self.assertIn("$preSelectCloneDelta=RangeEndpointDiagnostic $target $preSelectClone", self.text)
        self.assertIn("$freshRange=$textPattern.RangeFromChild($targetElement)", self.text)
        self.assertIn("$postTargetRuntime -ceq $targetRuntime", self.text)
        self.assertIn("$postDocumentRuntime -ceq $navigationRuntime", self.text)
        self.assertIn("P0_STATIC_ENDPOINT_DIFFERENTIAL", self.text)
        self.assertIn("old_active_start={0} old_active_end={1}", self.text)
        self.assertIn("active_fresh={6}", self.text)
        self.assertIn("fresh_status={7}", self.text)
        self.assertIn("focus_before={14} focus_after={15}", self.text)
        self.assertIn("target_before={20} target_after={21}", self.text)
        self.assertIn("ClipboardCodeUnits $freshText 48", self.text)
        self.assertIn('throw "Static TextPattern active selection endpoints differ from target range"', self.text)
        self.assertLess(
            self.text.index("if($startDelta -ne 0 -or $endDelta -ne 0)"),
            self.text.index("Set-Clipboard -Value 'P0_COPY_STATIC_SENTINEL'"),
        )
        self.assertNotIn("if($activeSelectedText -ceq $freshText)", self.text)
        self.assertNotIn("if($startDelta -ne 0 -or $endDelta -ne 0){continue}", self.text)


    def test_provider_normalized_end_acceptance_requires_stable_ranges_and_real_double_copy(self) -> None:
        self.assertIn("$selectionEndpointMode='identical-start-and-end'", self.text)
        self.assertIn("P0_STATIC_ENDPOINT_DIFFERENTIAL", self.text)
        self.assertIn("P0_STATIC_MISMATCH_NATIVE_CTRL_C_DIAGNOSTIC", self.text)
        self.assertIn("$startDelta -eq 0 -and $endDelta -gt 0", self.text)
        self.assertIn("$preSelectCloneDelta -ceq '0,0'", self.text)
        self.assertIn("(RangeEndpointDiagnostic $target $freshRange) -ceq '0,0'", self.text)
        self.assertIn("$freshStatus -ceq 'same-text'", self.text)
        self.assertIn("$postTargetRuntime -ceq $targetRuntime", self.text)
        self.assertIn("$preSelectFocusRuntime -ceq $navigationRuntime", self.text)
        self.assertIn("$focusAfterRuntime -ceq $navigationRuntime", self.text)
        self.assertIn("$copyAttempted -and $copyDiagnosticStatus -ceq 'exact'", self.text)
        self.assertIn("$copyActual -ceq $selected", self.text)
        self.assertIn("if(-not $normalizedProviderEnd)", self.text)
        self.assertIn("AssertProductForeground $process 'normalized static selection post-copy'", self.text)
        self.assertIn("AssertProviderFocus $roots 'normalized static selection post-copy'", self.text)
        self.assertIn("$postCopySelections=@($textPattern.GetSelection())", self.text)
        self.assertIn("normalized copy target no longer visible", self.text)
        self.assertIn("normalized copy selection changed after native Ctrl+C", self.text)
        self.assertIn("$selectionEndpointMode='provider-end-normalized-double-native-copy'", self.text)
        self.assertIn("static_selection_endpoint_mode=$selectionEndpointMode", self.text)
        self.assertIn("P0_STATIC_SELECTION_PROVIDER_NORMALIZED_NATIVE_COPY=PASS", self.text)
        self.assertIn('throw "Static TextPattern active selection endpoints differ from target range"', self.text)
        first_copy = self.text.index("[AccessibleChessCopyKeys]::Ctrl([byte]0x43)")
        normal_sentinel = self.text.index("Set-Clipboard -Value 'P0_COPY_STATIC_SENTINEL'")
        normal_copy = self.text.index("[AccessibleChessCopyKeys]::Ctrl([byte]0x43)", normal_sentinel)
        normal_verify = self.text.index("WaitClipboard $selected", normal_copy)
        self.assertLess(first_copy, normal_sentinel)
        self.assertLess(normal_sentinel, normal_copy)
        self.assertLess(normal_copy, normal_verify)
        self.assertNotIn("$copyDiagnosticStatus -ne 'exact' -or $normalizedProviderEnd", self.text)
        self.assertNotIn("Trim() -eq", self.text)


if __name__ == "__main__":
    unittest.main()
