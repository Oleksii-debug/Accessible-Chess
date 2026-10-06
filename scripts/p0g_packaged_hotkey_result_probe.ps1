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
  [DllImport("user32.dll")]
  private static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")]
  private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
  private const uint KEYEVENTF_KEYUP = 0x0002;
  private const byte VK_MENU = 0x12;
  private const byte VK_RETURN = 0x0D;
  public static void Enter() {
    keybd_event(VK_RETURN, 0, 0, UIntPtr.Zero);
    keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
  }
  public static void Alt(byte key) {
    keybd_event(VK_MENU, 0, 0, UIntPtr.Zero);
    keybd_event(key, 0, 0, UIntPtr.Zero);
    keybd_event(key, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
    keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
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

function SemanticTexts($Element) {
  # Read only the SAME live region and its connected RawView subtree.
  # WebView2 may expose aria-live text through a Text child instead of
  # the role=status parent's Name or TextPattern. No other region, DOM,
  # button name or application API is an announcement oracle.
  $items=New-Object 'System.Collections.Generic.List[string]'
  if($null -eq $Element){return $items.ToArray()}
  try {
    $name=([string]$Element.Current.Name).Trim()
    if($name){[void]$items.Add($name)}
  } catch {}
  try {
    $pattern=$null
    if($Element.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern,[ref]$pattern) -and
       $null -ne $pattern){
      $body=([string]$pattern.DocumentRange.GetText(-1)).Trim()
      if($body){[void]$items.Add($body)}
    }
  } catch {}
  $walker=[System.Windows.Automation.TreeWalker]::RawViewWalker
  $pending=New-Object System.Collections.Queue
  $pending.Enqueue(@{element=$Element; depth=0})
  $visited=New-Object 'System.Collections.Generic.HashSet[string]'
  $traversed=0
  while($pending.Count -gt 0 -and $traversed -lt 32){
    $node=$pending.Dequeue()
    if($node.depth -ge 3){continue}
    $child=$null
    try {$child=$walker.GetFirstChild($node.element)} catch {}
    while($null -ne $child -and $traversed -lt 32){
      $traversed++
      $id=RuntimeId $child
      if(-not $id -or $visited.Add($id)){
        try {
          $type=[string]$child.Current.ControlType.ProgrammaticName
          if($type -eq 'ControlType.Text'){
            $value=([string]$child.Current.Name).Trim()
            if($value){[void]$items.Add($value)}
          }
        } catch {}
        $pending.Enqueue(@{element=$child; depth=($node.depth+1)})
      }
      try {$child=$walker.GetNextSibling($child)} catch {$child=$null}
    }
  }
  return $items.ToArray()
}

function BoundedTextUnits([string]$Value) {
  $units=@()
  for($i=0;$i -lt [Math]::Min($Value.Length,48);$i++){
    $units+=('U+{0:X4}' -f [int][char]$Value[$i])
  }
  return ($units -join ',')
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

function ActivateProduct($Shell,$Process) {
  if(-not $Shell.AppActivate($Process.Id)){
    throw "Could not activate packaged AccessibleChess process $($Process.Id)"
  }
  $null=WaitFor {
    if([AccessibleChessP0GKeys]::ForegroundProcessId() -eq $Process.Id){return $true}
    return $null
  } 2000 'AccessibleChess.exe did not become the foreground native-key target'
}

function AssertProductForeground($Process) {
  $foreground=[AccessibleChessP0GKeys]::ForegroundProcessId()
  if($foreground -ne $Process.Id){
    throw "Native analysis hotkey target is not AccessibleChess.exe: foreground_pid=$foreground expected=$($Process.Id)"
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

  $relative='AccessibleChess/AccessibleChess.exe'
  $checksum=$null
  $checksumMatchCount=0
  foreach($line in @(Get-Content -LiteralPath $checksumsPath -Encoding UTF8)){
    if($line -cmatch '^(?<digest>[0-9A-Fa-f]{64})  AccessibleChess/AccessibleChess\.exe$'){
      $checksumMatchCount++
      $checksum=$Matches['digest'].ToLowerInvariant()
    }
  }
  if($checksumMatchCount -ne 1 -or -not $checksum){
    throw "SHA256SUMS.txt must contain exactly one canonical checksum for $relative"
  }
  $actual=(Get-FileHash -LiteralPath $ExePath -Algorithm SHA256).Hash.ToLowerInvariant()
  if($actual -cne $checksum){
    throw 'Packaged AccessibleChess.exe SHA-256 does not match canonical checksum inventory'
  }
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


function ActivateVariationPrecondition($Roots,$Button,[int]$Index,$Shell,$Process) {
  if($null -eq $Button){throw "analysis variation $Index precondition is missing"}
  $name=([string]$Button.Current.Name).Trim()
  $expected="^(Варіант|Variant)\s+$Index\."
  if([string]$Button.Current.ControlType.ProgrammaticName -ne 'ControlType.Button' -or
     $name -notmatch $expected){
    throw "analysis variation $Index precondition is not the named UIA Button"
  }
  if(-not [bool]$Button.Current.IsEnabled){
    throw "analysis variation $Index precondition is disabled"
  }
  $targetRuntime=RuntimeId $Button
  if(-not $targetRuntime){throw "analysis variation $Index has no stable UIA runtime identity"}
  $invokePattern=$null
  $hasInvoke=$false
  try {
    $hasInvoke=$Button.TryGetCurrentPattern(
      [System.Windows.Automation.InvokePattern]::Pattern,[ref]$invokePattern
    )
  } catch {
    throw "analysis variation $Index InvokePattern availability could not be read"
  }
  if($hasInvoke -and $null -ne $invokePattern){
    $invokePattern.Invoke()
    return 'uia-invoke'
  }
  # Chromium/WebView2 can expose an enabled HTML button through ControlView
  # without offering InvokePattern. Use the user's native focus + Enter path,
  # never a scripted DOM click or application API shortcut.
  if(-not [bool]$Button.Current.IsKeyboardFocusable){
    throw "analysis variation $Index lacks InvokePattern and keyboard focus"
  }
  ActivateProduct $Shell $Process
  AssertProductForeground $Process
  $Button.SetFocus()
  $null=WaitFor {
    $focus=[System.Windows.Automation.AutomationElement]::FocusedElement
    if($null -ne $focus -and (RuntimeId $focus) -ceq $targetRuntime -and
       [string]$focus.Current.ControlType.ProgrammaticName -eq 'ControlType.Button'){
      return $true
    }
    return $null
  } 2500 "analysis variation $Index could not receive exact native keyboard focus"
  if(-not [bool]$Button.Current.IsEnabled -or (RuntimeId $Button) -cne $targetRuntime){
    throw "analysis variation $Index identity/enabled state changed before Enter"
  }
  AssertProductForeground $Process
  [AccessibleChessP0GKeys]::Enter()
  return 'native-enter'
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
AssertExactPackageBinding $root $ProductSha $exe
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
  $liveRuntime=RuntimeId $live
  if(-not $liveRuntime){throw 'Accessible status live region lacks stable UIA identity'}

  $shell=New-Object -ComObject WScript.Shell
  ActivateProduct $shell $process
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
  $preconditionModes=@()
  $selectedStates=@()
  $announcements=@()
  foreach($case in @(@{index=1; key=0x31},@{index=2; key=0x32})){
    $index=[int]$case.index
    $opposite=if($index -eq 1){2}else{1}
    $preconditionButton=WaitFor {
      $candidate=FindVariationButton $roots $opposite
      if($null -ne $candidate -and [bool]$candidate.Current.IsEnabled){return $candidate}
      return $null
    } 12000 "Could not find enabled opposite variation $opposite for Alt+$index causal precondition"
    $preconditionMode=ActivateVariationPrecondition $roots $preconditionButton $opposite $shell $process
    $precondition=WaitFor {
      SelectedVariation $roots $opposite
    } 5000 "Could not establish opposite variation $opposite before Alt+$index"

    ActivateProduct $shell $process
    AssertLauncherFocus $launcher
    AssertProductForeground $process
    if((RuntimeId $live) -cne $liveRuntime -or
       [string]$live.Current.AutomationId -cne 'live'){
      throw 'Accessible status live region identity changed before hotkey'
    }
    $priorLiveTexts=@(SemanticTexts $live)
    [AccessibleChessP0GKeys]::Alt([byte]$case.key)
    $selected=WaitFor {
      SelectedVariation $roots $index
    } 5000 "Alt+$index did not change packaged selected state from variation $opposite to variation $index"
    $observations=@{texts=@()}
    try {
      $text=WaitFor {
        if((RuntimeId $live) -cne $liveRuntime -or
           [string]$live.Current.AutomationId -cne 'live'){
          throw 'Accessible status live region identity changed after hotkey'
        }
        $observations.texts=@(SemanticTexts $live)
        foreach($value in $observations.texts){
          if($value -and $value -cnotin $priorLiveTexts -and
             $value.ToLowerInvariant() -match "варіант\s+$index|variant\s+$index"){
            return $value
          }
        }
        return $null
      } 12000 "Alt+$index did not expose a matching live-region result"
    } catch {
      $snapshots=@($observations.texts | Select-Object -First 5 | ForEach-Object {
        "len=$($_.Length) units=$(BoundedTextUnits ([string]$_))"
      })
      Write-Host ("P0G_LIVE_REGION_FAILURE index={0} same_runtime={1} observed_count={2} observed='{3}'" -f $index,((RuntimeId $live) -ceq $liveRuntime),$observations.texts.Count,($snapshots -join ';'))
      throw
    }
    AssertCleanAnnouncement $text $index
    $preconditionStates += $precondition
    $preconditionModes += $preconditionMode
    $selectedStates += $selected
    $announcements += $text
    Write-Host "PACKAGED_P0G_ALT_${index}=PASS precondition='$precondition' activation=$preconditionMode selected='$selected' result='$text'"
  }

  if($preconditionStates.Count -ne 2 -or $preconditionModes.Count -ne 2 -or $selectedStates.Count -ne 2 -or $announcements.Count -ne 2 -or $announcements[0] -eq $announcements[1]){
    throw 'Alt+1 and Alt+2 did not prove causal selected-state transitions and distinct accessible results'
  }

  $summary=[ordered]@{
    product_sha=$ProductSha
    discovery='connected provider-root ControlView from retained topology handles'
    hotkey_focus_path='board-launcher SetFocus outside role=application so global analysis context receives native keys'
    board_application_entered=$false
    engine_enable_state=$engineState
    native_keyboard_dispatch=$true
    foreground_product_verified=$true
    manifest_product_sha_verified=$true
    executable_checksum_verified=$true
    alt_1_precondition_selected_state=$preconditionStates[0]
    alt_1_precondition_activation=$preconditionModes[0]
    alt_1_action_occurred=$true
    alt_1_selected_state=$selectedStates[0]
    alt_1_accessible_result_exposed=$true
    alt_1_result=$announcements[0]
    alt_2_precondition_selected_state=$preconditionStates[1]
    alt_2_precondition_activation=$preconditionModes[1]
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