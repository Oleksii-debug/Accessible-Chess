param(
  [Parameter(Mandatory=$true)][string]$ProductRoot,
  [Parameter(Mandatory=$true)][string]$ProductSha,
  [string]$TopologyScript = '.v2-uia-evidence\stage1_uia_topology_v5.ps1',
  [string]$OutputPath = 'packaged-v2-document-copy-summary.json',
  [int]$TimeoutSeconds = 45
)

$ErrorActionPreference='Stop'
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--force-renderer-accessibility'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

if(-not ('AccessibleChessCopyKeys' -as [type])){
  Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class AccessibleChessCopyKeys {
  [DllImport("user32.dll")]
  private static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
  [DllImport("user32.dll")]
  private static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")]
  private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
  private const uint KEYEVENTF_KEYUP = 0x0002;
  public static void Ctrl(byte key) {
    keybd_event(0x11, 0, 0, UIntPtr.Zero);
    keybd_event(key, 0, 0, UIntPtr.Zero);
    keybd_event(key, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
    keybd_event(0x11, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
  }
  public static int ForegroundProcessId() {
    IntPtr hwnd = GetForegroundWindow();
    if (hwnd == IntPtr.Zero) return 0;
    uint pid;
    GetWindowThreadProcessId(hwnd, out pid);
    return unchecked((int)pid);
  }
}
"@
}

function Hwnd([string]$Value) {
  $text=$Value.Trim()
  if($text.StartsWith('0x',[StringComparison]::OrdinalIgnoreCase)){
    return [IntPtr]([Convert]::ToInt64($text.Substring(2),16))
  }
  return [IntPtr]([int64]$text)
}

function RuntimeId($Element) {
  try { return (($Element.GetRuntimeId() | ForEach-Object {[string]$_}) -join '.') }
  catch { return '' }
}

function ElementKey($Element) {
  $runtime=RuntimeId $Element
  if($runtime){return 'rid:'+$runtime}
  try {return 'obj:'+([string]$Element.GetHashCode())} catch {return ''}
}

function ProviderRoots($Report) {
  $roots=@()
  foreach($row in @($Report.root_attempts)){
    if(-not $row.connected_to_app -or -not $row.from_handle_success -or -not $row.provider_subtree_seen){continue}
    $element=[System.Windows.Automation.AutomationElement]::FromHandle((Hwnd ([string]$row.hwnd)))
    if($null -eq $element){throw "FromHandle returned null for retained provider root $($row.hwnd)"}
    $roots += ,$element
  }
  if($roots.Count -eq 0){throw 'No connected provider-bearing roots available'}
  return $roots
}

function ControlElements($Roots) {
  $walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
  $stack=New-Object System.Collections.Stack
  foreach($root in $Roots){$stack.Push($root)}
  $seen=New-Object 'System.Collections.Generic.HashSet[string]'
  $elements=@()
  while($stack.Count -gt 0){
    if($elements.Count -ge 20000){throw 'Provider-root traversal cap reached'}
    $element=$stack.Pop()
    $key=ElementKey $element
    if($key -and -not $seen.Add($key)){continue}
    $elements += ,$element
    $children=@()
    try {
      $child=$walker.GetFirstChild($element)
      while($null -ne $child){
        $children += ,$child
        $child=$walker.GetNextSibling($child)
      }
    } catch {
      throw "Provider-root ControlView traversal failed: $($_.Exception.Message)"
    }
    for($index=$children.Count-1;$index -ge 0;$index--){$stack.Push($children[$index])}
  }
  return $elements
}

function ReadTopology($Process,[int]$TimeoutMs) {
  $topology=(Resolve-Path -LiteralPath $TopologyScript).Path
  $watch=[System.Diagnostics.Stopwatch]::StartNew()
  $last='not attempted'
  while($watch.ElapsedMilliseconds -lt $TimeoutMs){
    if($Process.HasExited){throw "Packaged process exited before document-copy topology readiness with code $($Process.ExitCode)"}
    try {
      Remove-Item -LiteralPath 'uia-topology-report-v5.json' -Force -ErrorAction SilentlyContinue
      & $topology -AppPid $Process.Id *> $null
      if(Test-Path -LiteralPath 'uia-topology-report-v5.json'){
        $report=Get-Content -LiteralPath 'uia-topology-report-v5.json' -Raw | ConvertFrom-Json
        $documents=@($report.nodes | Where-Object {
          [string]$_.control_type -eq 'ControlType.Document' -and
          [bool]$_.source_root_connected -and
          [string]$_.name -eq 'Accessible Chess'
        })
        if($documents.Count -gt 0){return $report}
        $last='topology report exists but Accessible Chess Document is not connected yet'
      } else {
        $last='topology helper returned without a report'
      }
    } catch {
      $last=$_.Exception.Message
    }
    Start-Sleep -Milliseconds 400
  }
  throw "Packaged document-copy topology did not become ready within $TimeoutMs ms; last=$last"
}

function FindControl($Elements,[string]$AutomationId,[string]$ControlType='') {
  foreach($element in @($Elements)){
    try {
      if($AutomationId -and [string]$element.Current.AutomationId -ne $AutomationId){continue}
      if($ControlType -and [string]$element.Current.ControlType.ProgrammaticName -ne $ControlType){continue}
      return $element
    } catch {}
  }
  return $null
}

function WaitFor($Script,[int]$TimeoutMs,[string]$Failure) {
  $watch=[System.Diagnostics.Stopwatch]::StartNew()
  while($watch.ElapsedMilliseconds -lt $TimeoutMs){
    $value=& $Script
    if($value){return $value}
    Start-Sleep -Milliseconds 50
  }
  throw $Failure
}

function ActivateProduct($Shell,$Process,[string]$Phase) {
  if(-not $Shell.AppActivate($Process.Id)){
    throw "${Phase}: could not activate packaged AccessibleChess process $($Process.Id)"
  }
  $null=WaitFor {
    if([AccessibleChessCopyKeys]::ForegroundProcessId() -eq $Process.Id){return $true}
    return $null
  } 2000 "${Phase}: AccessibleChess.exe did not become the foreground native-key target"
}

function AssertProductForeground($Process,[string]$Phase) {
  $foreground=[AccessibleChessCopyKeys]::ForegroundProcessId()
  if($foreground -ne $Process.Id){
    throw "${Phase}: native copy target is not AccessibleChess.exe: foreground_pid=$foreground expected=$($Process.Id)"
  }
}

function AssertExactPackageBinding([string]$ProductRootPath,[string]$ExpectedSha,[string]$ExePath) {
  if($ExpectedSha -notmatch '^[0-9A-Fa-f]{40}$'){
    throw 'ProductSha must be one exact 40-hex integration commit'
  }
  $expected=$ExpectedSha.ToLowerInvariant()
  $packageRoot=(Resolve-Path -LiteralPath (Join-Path $ProductRootPath '..')).Path
  $manifestPath=Join-Path $packageRoot 'RELEASE_MANIFEST.json'
  $checksumsPath=Join-Path $packageRoot 'SHA256SUMS.txt'
  if(-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)){
    throw 'Canonical RELEASE_MANIFEST.json is missing beside packaged product root'
  }
  if(-not (Test-Path -LiteralPath $checksumsPath -PathType Leaf)){
    throw 'Canonical SHA256SUMS.txt is missing beside packaged product root'
  }

  $manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
  $manifestSha=([string]$manifest.integration_sha).ToLowerInvariant()
  if($manifestSha -cne $expected){
    throw "Packaged release manifest integration_sha mismatch: manifest=$manifestSha expected=$expected"
  }

  $checksum=$null
  $checksumMatchCount=0
  foreach($line in @(Get-Content -LiteralPath $checksumsPath -Encoding UTF8)){
    if($line -cmatch '^(?<digest>[0-9A-Fa-f]{64})  AccessibleChess/AccessibleChess\.exe$'){
      $checksumMatchCount++
      $checksum=$Matches['digest'].ToLowerInvariant()
    }
  }
  if($checksumMatchCount -ne 1 -or -not $checksum){
    throw 'SHA256SUMS.txt must contain exactly one canonical checksum for AccessibleChess/AccessibleChess.exe'
  }
  $actual=(Get-FileHash -LiteralPath $ExePath -Algorithm SHA256).Hash.ToLowerInvariant()
  if($actual -cne $checksum){
    throw 'Packaged AccessibleChess.exe SHA-256 does not match canonical checksum inventory'
  }
}

function AssertProviderFocus($Roots,[string]$Phase,[string]$ExpectedAutomationId='') {
  $focused=[System.Windows.Automation.AutomationElement]::FocusedElement
  if($null -eq $focused){throw "${Phase}: UIA focused element unavailable"}
  $focusedRuntime=RuntimeId $focused
  if(-not $focusedRuntime){throw "${Phase}: focused element has no stable UIA runtime identity"}
  $insideProvider=$false
  foreach($candidate in @(ControlElements $Roots)){
    if((RuntimeId $candidate) -eq $focusedRuntime){$insideProvider=$true;break}
  }
  if(-not $insideProvider){
    throw "${Phase}: native keyboard focus escaped connected packaged provider roots"
  }
  if($ExpectedAutomationId -and [string]$focused.Current.AutomationId -ne $ExpectedAutomationId){
    throw "${Phase}: wrong focused control; expected='$ExpectedAutomationId' actual='$([string]$focused.Current.AutomationId)'"
  }
  return $focused
}

function ClipboardCodeUnits([string]$Value,[int]$Limit=96) {
  $units=@()
  $count=[Math]::Min($Value.Length,$Limit)
  for($index=0;$index -lt $count;$index++){
    $units += ('U+{0:X4}' -f [int][char]$Value[$index])
  }
  if($Value.Length -gt $Limit){$units += '...'}
  return ($units -join ',')
}

function WaitClipboard([string]$Expected,[int]$TimeoutMs=5000) {
  $watch=[System.Diagnostics.Stopwatch]::StartNew()
  $last=''
  while($watch.ElapsedMilliseconds -lt $TimeoutMs){
    try {$last=[string](Get-Clipboard -Raw -ErrorAction Stop)} catch {$last=''}
    if($last -ceq $Expected){return $last}
    Start-Sleep -Milliseconds 100
  }
  $mismatch=-1
  $common=[Math]::Min($Expected.Length,$last.Length)
  for($index=0;$index -lt $common;$index++){
    if([int][char]$Expected[$index] -ne [int][char]$last[$index]){
      $mismatch=$index
      break
    }
  }
  if($mismatch -lt 0 -and $Expected.Length -ne $last.Length){$mismatch=$common}
  $expectedUnits=ClipboardCodeUnits $Expected
  $actualUnits=ClipboardCodeUnits $last
  throw "Clipboard did not receive exact selected text; expected_length=$($Expected.Length) actual_length=$($last.Length) first_mismatch_index=$mismatch expected_code_units='$expectedUnits' actual_code_units='$actualUnits' expected='$Expected' actual='$last'"
}

function AssertVisibleTextRange($Range,$TargetElement) {
  $rectangles=@()
  try {$rectangles=@($Range.GetBoundingRectangles())}
  catch {$rectangles=@()}

  if($rectangles.Count -ge 4 -and ($rectangles.Count % 4) -eq 0){
    for($index=0;$index -lt $rectangles.Count;$index+=4){
      $width=[double]$rectangles[$index+2]
      $height=[double]$rectangles[$index+3]
      if($width -gt 0 -and $height -gt 0){return 'text-range'}
    }
  }

  # WebView2 can expose a fully selectable TextPattern range while omitting
  # per-range rectangles. Keep the visibility requirement fail-closed by
  # requiring the range's enclosing UIA element to be onscreen with positive
  # geometry after ScrollIntoView. Selection endpoints and native clipboard
  # equality remain independently decisive below.
  $enclosing=$null
  try {$enclosing=$Range.GetEnclosingElement()} catch {$enclosing=$null}
  if($null -ne $enclosing){
    try {
      if(-not [bool]$enclosing.Current.IsOffscreen){
        $bounds=$enclosing.Current.BoundingRectangle
        $width=[double]$bounds.Width
        $height=[double]$bounds.Height
        if($width -gt 0 -and $height -gt 0){return 'enclosing-element'}
      }
    } catch {}
  }

  if($null -ne $TargetElement){
    try {
      if(-not [bool]$TargetElement.Current.IsOffscreen){
        $bounds=$TargetElement.Current.BoundingRectangle
        $width=[double]$bounds.Width
        $height=[double]$bounds.Height
        if($width -gt 0 -and $height -gt 0){return 'target-element'}
      }
    } catch {}
  }

  throw "Static TextPattern target has no onscreen positive-area UIA element for visibility proof"
}

function AddStaticCandidateDiagnostic($Element,$Pattern,[string]$Phrase,[string]$Source,$Lines) {
  if($Lines.Count -ge 24){return}
  try {
    $type=[string]$Element.Current.ControlType.ProgrammaticName
    $automationId=[string]$Element.Current.AutomationId
    $bounds=$Element.Current.BoundingRectangle
    $isContent=[bool]$Element.Current.IsContentElement
    $isControl=[bool]$Element.Current.IsControlElement
    $keyboardFocusable=[bool]$Element.Current.IsKeyboardFocusable
    $offscreen=[bool]$Element.Current.IsOffscreen
    $rangeState='unavailable'
    $rangeLength=-1
    $rangeExact=$false
    $rangeSingleLine=$false
    try {
      $diagnosticRange=$Pattern.RangeFromChild($Element)
      if($null -eq $diagnosticRange){
        $rangeState='null'
      } else {
        $diagnosticText=[string]$diagnosticRange.GetText(-1)
        $rangeState='available'
        $rangeLength=$diagnosticText.Length
        $rangeExact=($diagnosticText -ceq $Phrase)
        $rangeSingleLine=(-not $diagnosticText.Contains("`r") -and -not $diagnosticText.Contains("`n"))
      }
    } catch {
      $rangeState='error'
    }
    $line=("P0_STATIC_TARGET_CANDIDATE source={0} phrase_code_units='{1}' type={2} automation_id={3} content={4} control={5} keyboard_focusable={6} offscreen={7} width={8} height={9} range={10} range_length={11} exact_text={12} single_line={13}" -f $Source,(ClipboardCodeUnits $Phrase 48),$type,$automationId,$isContent,$isControl,$keyboardFocusable,$offscreen,[Math]::Round([double]$bounds.Width,2),[Math]::Round([double]$bounds.Height,2),$rangeState,$rangeLength,$rangeExact,$rangeSingleLine)
    [void]$Lines.Add($line)
  } catch {
    if($Lines.Count -lt 24){[void]$Lines.Add("P0_STATIC_TARGET_CANDIDATE source=$Source diagnostic=property-read-error")}
  }
}

$root=(Resolve-Path -LiteralPath $ProductRoot).Path
$exe=(Resolve-Path -LiteralPath (Join-Path $root 'AccessibleChess.exe')).Path
AssertExactPackageBinding $root $ProductSha $exe
$process=Start-Process -FilePath $exe -WorkingDirectory $root -PassThru
try {
  $report=ReadTopology $process ($TimeoutSeconds*1000)
  $roots=ProviderRoots $report
  $elements=ControlElements $roots
  $documents=@($elements | Where-Object {
    try {
      [string]$_.Current.ControlType.ProgrammaticName -eq 'ControlType.Document' -and
      [string]$_.Current.Name -eq 'Accessible Chess'
    } catch {$false}
  })
  if($documents.Count -lt 1){throw 'Accessible Chess Document missing from connected provider-root ControlView'}

  $usableDocuments=@()
  $staticTargetDiagnostics=New-Object 'System.Collections.Generic.List[string]'
  foreach($candidate in $documents){
    try {
      $candidatePattern=$candidate.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
      if($null -eq $candidatePattern){continue}
      if(([string]$candidatePattern.SupportedTextSelection) -match 'None$'){continue}
      $candidateElements=ControlElements @($candidate)
      $candidateTarget=$null
      $candidatePhrase=''
      $candidateTargetType=''
      foreach($phrase in @('Розділи','Sections','Accessible Chess','Інформація про гру','Game information','Список ходів')){
        $controlViewPhraseMatches=@($candidateElements | Where-Object {
          try {[string]$_.Current.Name -ceq $phrase} catch {$false}
        })
        foreach($observed in $controlViewPhraseMatches){
          AddStaticCandidateDiagnostic $observed $candidatePattern $phrase 'control-view-name' $staticTargetDiagnostics
        }
        try {
          $nameCondition=[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty,$phrase)
          $rawPhraseMatches=@($candidate.FindAll([System.Windows.Automation.TreeScope]::Descendants,$nameCondition))
          foreach($observed in $rawPhraseMatches){
            AddStaticCandidateDiagnostic $observed $candidatePattern $phrase 'raw-name' $staticTargetDiagnostics
          }
        } catch {
          if($staticTargetDiagnostics.Count -lt 24){[void]$staticTargetDiagnostics.Add("P0_STATIC_TARGET_DIAGNOSTIC_ERROR source=raw-name")}
        }
        $namedTargets=@($candidateElements | Where-Object {
          try {
            $type=[string]$_.Current.ControlType.ProgrammaticName
            $name=[string]$_.Current.Name
            $bounds=$_.Current.BoundingRectangle
            $isOnscreen=-not [bool]$_.Current.IsOffscreen
            $name -ceq $phrase -and
            ($type -eq 'ControlType.Header' -or $type -eq 'ControlType.Text') -and
            $isOnscreen -and
            [double]$bounds.Width -gt 0 -and
            [double]$bounds.Height -gt 0
          } catch {$false}
        })
        if($namedTargets.Count -ne 1){continue}
        try {$probeRange=$candidatePattern.RangeFromChild($namedTargets[0])}
        catch {continue}
        if($null -eq $probeRange){continue}
        $probeText=[string]$probeRange.GetText(-1)
        if($probeText -cne $phrase){continue}
        if($probeText.Contains("`r") -or $probeText.Contains("`n")){continue}
        $candidateTarget=$probeRange
        $candidatePhrase=$phrase
        $candidateTargetType=[string]$namedTargets[0].Current.ControlType.ProgrammaticName
        break
      }
      try {
        $idCondition=[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::AutomationIdProperty,'v2-navigation-heading')
        $rawHeadingMatches=@($candidate.FindAll([System.Windows.Automation.TreeScope]::Descendants,$idCondition))
        foreach($observed in $rawHeadingMatches){
          AddStaticCandidateDiagnostic $observed $candidatePattern 'Розділи' 'raw-automation-id-v2-navigation-heading' $staticTargetDiagnostics
        }
      } catch {
        if($staticTargetDiagnostics.Count -lt 24){[void]$staticTargetDiagnostics.Add('P0_STATIC_TARGET_DIAGNOSTIC_ERROR source=raw-automation-id-v2-navigation-heading')}
      }
      if($null -eq $candidateTarget){continue}
      $usableDocuments += ,[pscustomobject]@{
        document=$candidate
        text_pattern=$candidatePattern
        target=$candidateTarget
        target_element=$namedTargets[0]
        target_phrase=$candidatePhrase
        target_control_type=$candidateTargetType
      }
    } catch {
      continue
    }
  }
  if($usableDocuments.Count -eq 0){
    foreach($diagnosticLine in @($staticTargetDiagnostics)){Write-Host $diagnosticLine}
    throw "Connected Accessible Chess Documents found=$($documents.Count), but none exposes selectable stable static text; diagnostic_candidates=$($staticTargetDiagnostics.Count)"
  }
  if($usableDocuments.Count -ne 1){
    throw "Ambiguous selectable Accessible Chess Documents found=$($usableDocuments.Count); expected exactly one stable packaged document provider"
  }
  $document=$usableDocuments[0].document
  $textPattern=$usableDocuments[0].text_pattern
  $target=$usableDocuments[0].target
  $targetPhrase=[string]$usableDocuments[0].target_phrase
  $targetControlType=[string]$usableDocuments[0].target_control_type

  $selected=[string]$target.GetText(-1)
  if(-not $selected.Trim()){throw 'Static TextPattern target is empty'}
  if($selected -cne $targetPhrase){throw 'Static TextPattern target drifted from exact single-line phrase'}
  if($selected.Contains("`r") -or $selected.Contains("`n")){throw 'Static TextPattern exact-copy target must be single-line'}
  $enclosing=$target.GetEnclosingElement()
  if($null -ne $enclosing -and [string]$enclosing.Current.ControlType.ProgrammaticName -eq 'ControlType.Edit'){
    throw 'Static text proof accidentally targeted an edit control'
  }

  $shell=New-Object -ComObject WScript.Shell
  ActivateProduct $shell $process 'static document copy'
  try {$document.SetFocus()} catch {throw "Accessible Chess Document could not receive focus for native Ctrl+C: $($_.Exception.Message)"}
  Start-Sleep -Milliseconds 100
  $focused=AssertProviderFocus $roots 'static document copy'
  if([string]$focused.Current.ControlType.ProgrammaticName -eq 'ControlType.Edit'){
    throw 'Static document copy focus landed in an edit control'
  }
  $targetRuntime=RuntimeId $usableDocuments[0].target_element
  if(-not $targetRuntime){throw 'Static target lost stable UIA runtime identity before scroll'}
  $beforeBounds=$usableDocuments[0].target_element.Current.BoundingRectangle
  $beforeWidth=[Math]::Round([double]$beforeBounds.Width,2)
  $beforeHeight=[Math]::Round([double]$beforeBounds.Height,2)
  $beforeOffscreen=[bool]$usableDocuments[0].target_element.Current.IsOffscreen
  try {$target.ScrollIntoView($true)}
  catch {throw "Static TextPattern target could not be scrolled into view: $($_.Exception.Message)"}
  # WebView2's UIA geometry can settle after ScrollIntoView has returned.
  # Wait only for the SAME exact target and text, never an arbitrary visible range.
  $visibilityEvidence=$null
  $visibilityWatch=[System.Diagnostics.Stopwatch]::StartNew()
  do {
    if((RuntimeId $usableDocuments[0].target_element) -cne $targetRuntime){
      throw 'Static target UIA runtime identity changed while waiting for visible geometry'
    }
    if([string]$target.GetText(-1) -cne $selected){
      throw 'Static target exact text changed while waiting for visible geometry'
    }
    try {
      $visibilityEvidence=AssertVisibleTextRange $target $usableDocuments[0].target_element
    } catch {
      if($visibilityWatch.ElapsedMilliseconds -ge 2500){
        $rangeRectangles=@()
        try {$rangeRectangles=@($target.GetBoundingRectangles())} catch {}
        $afterOffscreen='unavailable'
        $afterWidth='unavailable'
        $afterHeight='unavailable'
        try {
          $afterOffscreen=[bool]$usableDocuments[0].target_element.Current.IsOffscreen
          $afterBounds=$usableDocuments[0].target_element.Current.BoundingRectangle
          $afterWidth=[Math]::Round([double]$afterBounds.Width,2)
          $afterHeight=[Math]::Round([double]$afterBounds.Height,2)
        } catch {}
        $enclosingOffscreen='unavailable'
        $enclosingWidth='unavailable'
        $enclosingHeight='unavailable'
        try {
          $visibleEnclosing=$target.GetEnclosingElement()
          if($null -ne $visibleEnclosing){
            $enclosingOffscreen=[bool]$visibleEnclosing.Current.IsOffscreen
            $enclosingBounds=$visibleEnclosing.Current.BoundingRectangle
            $enclosingWidth=[Math]::Round([double]$enclosingBounds.Width,2)
            $enclosingHeight=[Math]::Round([double]$enclosingBounds.Height,2)
          }
        } catch {}
        $chosenAutomationId='unavailable'
        try {
          $chosenAutomationId=([string]$usableDocuments[0].target_element.Current.AutomationId -replace '[^A-Za-z0-9_-]','_')
          if($chosenAutomationId.Length -gt 64){$chosenAutomationId=$chosenAutomationId.Substring(0,64)}
        } catch {}
        Write-Host ("P0_STATIC_SELECTED_TARGET phrase_code_units='{0}' type={1} automation_id={2} target_runtime={3}" -f (ClipboardCodeUnits $targetPhrase 48),$targetControlType,$chosenAutomationId,$targetRuntime)
        foreach($diagnosticLine in @($staticTargetDiagnostics)){Write-Host $diagnosticLine}
        Write-Host ("P0_STATIC_VISIBILITY_FAILURE range_coordinate_count={0} target_initial_offscreen={1} target_initial_size={2}x{3} target_final_offscreen={4} target_final_size={5}x{6} enclosing_offscreen={7} enclosing_size={8}x{9} settled_ms={10}" -f $rangeRectangles.Count,$beforeOffscreen,$beforeWidth,$beforeHeight,$afterOffscreen,$afterWidth,$afterHeight,$enclosingOffscreen,$enclosingWidth,$enclosingHeight,$visibilityWatch.ElapsedMilliseconds)
        throw
      }
      Start-Sleep -Milliseconds 100
    }
  } while(-not $visibilityEvidence)
  $null=AssertProviderFocus $roots 'static document visibility proof'
  $target.Select()
  Start-Sleep -Milliseconds 100
  $activeSelections=@($textPattern.GetSelection())
  if($activeSelections.Count -ne 1){
    throw "Static TextPattern selection cardinality mismatch after Select(): $($activeSelections.Count)"
  }
  $activeSelection=$activeSelections[0]
  $activeSelectedText=[string]$activeSelection.GetText(-1)
  $targetText=[string]$target.GetText(-1)
  if($activeSelectedText -cne $targetText){
    throw "Static TextPattern active selection text differs from target range"
  }
  $startDelta=$activeSelection.CompareEndpoints(
    [System.Windows.Automation.Text.TextPatternRangeEndpoint]::Start,
    $target,
    [System.Windows.Automation.Text.TextPatternRangeEndpoint]::Start
  )
  $endDelta=$activeSelection.CompareEndpoints(
    [System.Windows.Automation.Text.TextPatternRangeEndpoint]::End,
    $target,
    [System.Windows.Automation.Text.TextPatternRangeEndpoint]::End
  )
  if($startDelta -ne 0 -or $endDelta -ne 0){
    throw "Static TextPattern active selection endpoints differ from target range"
  }
  Set-Clipboard -Value 'P0_COPY_STATIC_SENTINEL'
  Start-Sleep -Milliseconds 150
  $null=AssertProviderFocus $roots 'static document copy dispatch'
  AssertProductForeground $process 'static document copy dispatch'
  [AccessibleChessCopyKeys]::Ctrl([byte]0x43)
  $null=WaitClipboard $selected
  Write-Host "PACKAGED_STATIC_DOCUMENT_SELECTION_COPY=PASS text='$selected' document_pid=$([int]$document.Current.ProcessId)"

  $elements=ControlElements $roots
  $move=FindControl $elements 'move-input' 'ControlType.Edit'
  if($null -eq $move){throw 'Move Input UIA element not found from connected provider roots'}
  try {$value=$move.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)}
  catch {throw "Move Input lacks ValuePattern: $($_.Exception.Message)"}
  if($null -eq $value){throw 'Move Input lacks ValuePattern'}
  $value.SetValue('e2e4')
  ActivateProduct $shell $process 'move input copy'
  $move.SetFocus()
  Start-Sleep -Milliseconds 100
  $null=AssertProviderFocus $roots 'move input copy' 'move-input'
  Set-Clipboard -Value 'P0_COPY_EDIT_SENTINEL'
  Start-Sleep -Milliseconds 100
  $null=AssertProviderFocus $roots 'move input copy dispatch' 'move-input'
  AssertProductForeground $process 'move input copy dispatch'
  [AccessibleChessCopyKeys]::Ctrl([byte]0x41)
  AssertProductForeground $process 'move input copy dispatch after Ctrl+A'
  $null=AssertProviderFocus $roots 'move input copy dispatch after Ctrl+A' 'move-input'
  [AccessibleChessCopyKeys]::Ctrl([byte]0x43)
  $null=WaitClipboard 'e2e4'
  $value.SetValue('')
  Write-Host 'PACKAGED_MOVE_INPUT_NATIVE_CTRL_A_CTRL_C=PASS'

  $summary=[ordered]@{
    product_sha=$ProductSha
    discovery='connected provider-root ControlView from retained topology handles'
    document_provider_cardinality='exactly one selectable Accessible Chess document containing one exact visible static UIA child target'
    focus_ownership='focused UIA runtime identity must belong to retained connected provider-root ControlView'
    static_document_text=$selected
    static_document_target_phrase=$targetPhrase
    static_document_target_control_type=$targetControlType
    static_document_range_source='TextPattern.RangeFromChild exact named visible static UIA child'
    static_document_outside_edit=$true
    static_text_visible_rectangle=($visibilityEvidence -eq 'text-range')
    static_text_visibility_evidence=$visibilityEvidence
    native_copy_focus_verified=$true
    foreground_product_verified=$true
    manifest_product_sha_verified=$true
    executable_checksum_verified=$true
    textpattern_selection_supported=$true
    textpattern_target_selected=$true
    textpattern_selection_equality='UIA exact range endpoints and case-sensitive text equality'
    clipboard_equality='case-sensitive exact string equality'
    ctrl_c_exact_clipboard=$true
    move_input_focus_verified=$true
    move_input_native_ctrl_a_ctrl_c=$true
    document_process_id=[int]$document.Current.ProcessId
    launched_process_id=$process.Id
    human_tested=$false
    nvda_verified=$false
  }
  $summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
}
finally {
  $live=Get-Process -Id $process.Id -ErrorAction SilentlyContinue
  if($live){Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue}
}

if(-not (Test-Path -LiteralPath $OutputPath -PathType Leaf)){throw 'Packaged document-copy evidence missing'}
$bounded=Get-Content -LiteralPath $OutputPath -Raw
if($bounded.Contains(':\') -or $bounded -match '(?i)/home/|/Users/|/tmp/'){throw 'Local path leaked into document-copy evidence'}