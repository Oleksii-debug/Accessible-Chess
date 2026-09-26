param(
  [Parameter(Mandatory=$true)][string]$ProductRoot,
  [Parameter(Mandatory=$true)][string]$ProductSha,
  [string]$TopologyScript = '.v2-uia-evidence\stage1_uia_topology_v5.ps1',
  [string]$OutputPath = 'packaged-p0g-hotkey-result-summary.json',
  [int]$TimeoutSeconds = 60
)

$ErrorActionPreference='Stop'
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--force-renderer-accessibility'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

if(-not ('AccessibleChessP0GKeys' -as [type])){
  Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class AccessibleChessP0GKeys {
  [DllImport("user32.dll")]
  private static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
  private const uint KEYEVENTF_KEYUP = 0x0002;
  private const byte VK_MENU = 0x12;
  public static void Alt(byte key) {
    keybd_event(VK_MENU, 0, 0, UIntPtr.Zero);
    keybd_event(key, 0, 0, UIntPtr.Zero);
    keybd_event(key, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
    keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
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
    if($null -ne $element){$roots += ,$element}
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
    $child=$walker.GetFirstChild($element)
    while($null -ne $child){$children += ,$child; $child=$walker.GetNextSibling($child)}
    for($index=$children.Count-1;$index -ge 0;$index--){$stack.Push($children[$index])}
  }
  return $elements
}

function ReadTopology($Process,[int]$TimeoutMs) {
  $topology=(Resolve-Path -LiteralPath $TopologyScript).Path
  $watch=[System.Diagnostics.Stopwatch]::StartNew()
  $last='not attempted'
  while($watch.ElapsedMilliseconds -lt $TimeoutMs){
    if($Process.HasExited){throw "Packaged process exited before P0-G readiness with code $($Process.ExitCode)"}
    try {
      Remove-Item -LiteralPath 'uia-topology-report-v5.json' -Force -ErrorAction SilentlyContinue
      & $topology -AppPid $Process.Id *> $null
      if(Test-Path -LiteralPath 'uia-topology-report-v5.json'){
        $report=Get-Content -LiteralPath 'uia-topology-report-v5.json' -Raw | ConvertFrom-Json
        if(@($report.root_attempts | Where-Object {$_.connected_to_app -and $_.provider_subtree_seen}).Count -gt 0){return $report}
        $last='no connected provider subtree yet'
      }
    } catch {$last=$_.Exception.Message}
    Start-Sleep -Milliseconds 400
  }
  throw "Packaged P0-G topology did not become ready within $TimeoutMs ms; last=$last"
}

function FindById($Elements,[string]$AutomationId) {
  foreach($element in @($Elements)){
    try { if([string]$element.Current.AutomationId -eq $AutomationId){return $element} } catch {}
  }
  return $null
}

function Invoke($Element,[string]$Name) {
  if($null -eq $Element){throw "$Name is missing from connected provider roots"}
  try {$pattern=$Element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)}
  catch {throw "$Name lacks InvokePattern: $($_.Exception.Message)"}
  if($null -eq $pattern){throw "$Name lacks InvokePattern"}
  $pattern.Invoke()
}

function EnsureEngineEnabled($EngineToggle) {
  if($null -eq $EngineToggle){throw 'engine-toggle missing from connected provider roots'}
  $name=([string]$EngineToggle.Current.Name).Trim()
  if($name -match '^(Увімкнути Stockfish|Enable Stockfish)$'){
    Invoke $EngineToggle 'engine-toggle'
    return 'enabled-by-probe'
  }
  if($name -match '^(Вимкнути Stockfish|Disable Stockfish)$'){
    return 'already-enabled'
  }
  throw "Unrecognized engine-toggle accessible state: '$name'"
}

function SemanticText($Element) {
  if($null -eq $Element){return ''}
  try {
    $name=([string]$Element.Current.Name).Trim()
    if($name){return $name}
  } catch {}
  try {
    $pattern=$Element.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
    if($null -ne $pattern){return ([string]$pattern.DocumentRange.GetText(-1)).Trim()}
  } catch {}
  return ''
}

function WaitFor($Script,[int]$TimeoutMs,[string]$Failure) {
  $watch=[System.Diagnostics.Stopwatch]::StartNew()
  while($watch.ElapsedMilliseconds -lt $TimeoutMs){
    $value=& $Script
    if($value){return $value}
    Start-Sleep -Milliseconds 100
  }
  throw $Failure
}

function AssertLauncherFocus($Launcher) {
  if($null -eq $Launcher){throw 'board-launcher is missing from connected provider roots'}
  $Launcher.SetFocus()
  Start-Sleep -Milliseconds 80
  $focused=[System.Windows.Automation.AutomationElement]::FocusedElement
  if($null -eq $focused){throw 'UIA focused element unavailable before analysis hotkey dispatch'}
  if([string]$focused.Current.AutomationId -ne 'board-launcher'){
    throw "Analysis hotkey focus escaped document context: id='$([string]$focused.Current.AutomationId)'"
  }
}

function FindVariationButton($Roots,[int]$Index) {
  $expected="^(Варіант|Variant)\s+$Index\."
  foreach($element in @(ControlElements $Roots)){
    try {
      if([string]$element.Current.ControlType.ProgrammaticName -ne 'ControlType.Button'){continue}
      $name=([string]$element.Current.Name).Trim()
      if($name -match $expected){return $element}
    } catch {}
  }
  return $null
}

function SelectedVariation($Roots,[int]$Index) {
  $button=FindVariationButton $Roots $Index
  if($null -eq $button){return $null}
  try {
    $toggle=$button.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
    if($null -ne $toggle -and $toggle.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On){
      return ([string]$button.Current.Name).Trim()
    }
  } catch {}
  return $null
}

function AssertCleanAnnouncement([string]$Text,[int]$Index) {
  if(-not $Text.Trim()){throw "Alt+$Index produced no accessible result"}
  $lower=$Text.ToLowerInvariant()
  if($lower -match '\b[a-h][1-8][a-h][1-8][qrbn]?\b' -or $lower -match 'uci|debug|traceback'){
    throw "Alt+$Index exposed raw provider/debug text: $Text"
  }
  if($lower -notmatch "варіант\s+$Index|variant\s+$Index"){
    throw "Alt+$Index result does not identify the selected variation: $Text"
  }
  if($lower -notmatch 'глибин|depth'){throw "Alt+$Index result omits analysis depth: $Text"}
  if($lower -notmatch 'оцін|eval'){throw "Alt+$Index result omits evaluation: $Text"}
}

$root=(Resolve-Path -LiteralPath $ProductRoot).Path
$exe=(Resolve-Path -LiteralPath (Join-Path $root 'AccessibleChess.exe')).Path
$process=Start-Process -FilePath $exe -WorkingDirectory $root -PassThru
try {
  $report=ReadTopology $process ($TimeoutSeconds*1000)
  $roots=ProviderRoots $report
  $elements=ControlElements $roots
  $launcher=FindById $elements 'board-launcher'
  $engineToggle=FindById $elements 'engine-toggle'
  $live=FindById $elements 'live'
  if($null -eq $launcher){throw 'board-launcher missing from connected provider roots'}
  if($null -eq $live){throw 'Accessible status live region #live missing from connected provider roots'}

  $shell=New-Object -ComObject WScript.Shell
  $null=$shell.AppActivate($process.Id)
  $engineState=EnsureEngineEnabled $engineToggle

  $null=WaitFor {
    $fresh=ControlElements $roots
    $buttons=@($fresh | Where-Object {
      try {
        [string]$_.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and
        ([string]$_.Current.Name -match 'Варіант\s+[12]|Variant\s+[12]')
      } catch {$false}
    })
    if($buttons.Count -ge 2){return $buttons}
    return $null
  } ([Math]::Min($TimeoutSeconds*1000,30000)) 'Packaged Stockfish did not expose two analysis variations in time'

  $preconditionStates=@()
  $selectedStates=@()
  $announcements=@()
  foreach($case in @(@{index=1; key=0x31},@{index=2; key=0x32})){
    $index=[int]$case.index
    $opposite=if($index -eq 1){2}else{1}
    $preconditionButton=WaitFor {
      FindVariationButton $roots $opposite
    } 5000 "Could not find opposite variation $opposite for Alt+$index causal precondition"
    Invoke $preconditionButton "analysis variation $opposite precondition"
    $precondition=WaitFor {
      SelectedVariation $roots $opposite
    } 5000 "Could not establish opposite variation $opposite before Alt+$index"

    $null=$shell.AppActivate($process.Id)
    AssertLauncherFocus $launcher
    [AccessibleChessP0GKeys]::Alt([byte]$case.key)
    $selected=WaitFor {
      SelectedVariation $roots $index
    } 5000 "Alt+$index did not change packaged selected state from variation $opposite to variation $index"
    $text=WaitFor {
      $value=SemanticText $live
      if($value -and $value.ToLowerInvariant() -match "варіант\s+$index|variant\s+$index"){return $value}
      return $null
    } 5000 "Alt+$index did not expose a matching live-region result"
    AssertCleanAnnouncement $text $index
    $preconditionStates += $precondition
    $selectedStates += $selected
    $announcements += $text
    Write-Host "PACKAGED_P0G_ALT_${index}=PASS precondition='$precondition' selected='$selected' result='$text'"
  }

  if($preconditionStates.Count -ne 2 -or $selectedStates.Count -ne 2 -or $announcements.Count -ne 2 -or $announcements[0] -eq $announcements[1]){
    throw 'Alt+1 and Alt+2 did not prove causal selected-state transitions and distinct accessible results'
  }

  $summary=[ordered]@{
    product_sha=$ProductSha
    discovery='connected provider-root ControlView from retained topology handles'
    hotkey_focus_path='board-launcher SetFocus outside role=application so global analysis context receives native keys'
    board_application_entered=$false
    engine_enable_state=$engineState
    native_keyboard_dispatch=$true
    alt_1_precondition_selected_state=$preconditionStates[0]
    alt_1_action_occurred=$true
    alt_1_selected_state=$selectedStates[0]
    alt_1_accessible_result_exposed=$true
    alt_1_result=$announcements[0]
    alt_2_precondition_selected_state=$preconditionStates[1]
    alt_2_action_occurred=$true
    alt_2_selected_state=$selectedStates[1]
    alt_2_accessible_result_exposed=$true
    alt_2_result=$announcements[1]
    raw_uci_or_debug_exposed=$false
    human_tested=$false
    nvda_verified=$false
  }
  $summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
}
finally {
  $liveProcess=Get-Process -Id $process.Id -ErrorAction SilentlyContinue
  if($liveProcess){Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue}
}

if(-not (Test-Path -LiteralPath $OutputPath -PathType Leaf)){throw 'Packaged P0-G evidence missing'}
$bounded=Get-Content -LiteralPath $OutputPath -Raw
if($bounded -match '(?i)[A-Z]:\\\\|/home/|/Users/|/tmp/'){throw 'Local path leaked into P0-G evidence'}