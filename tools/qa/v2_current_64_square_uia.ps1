param(
  [Parameter(Mandatory=$true)][int]$AppPid,
  [Parameter(Mandatory=$true)][string]$ReportPath,
  [Parameter(Mandatory=$true)][string]$ProductSha
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class V2SquareKeys {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  public static void Tap(byte vk) {
    keybd_event(vk, 0, 0, UIntPtr.Zero);
    System.Threading.Thread.Sleep(70);
    keybd_event(vk, 0, 2, UIntPtr.Zero);
    System.Threading.Thread.Sleep(120);
  }
  public static void Chord(byte modifier, byte vk) {
    keybd_event(modifier, 0, 0, UIntPtr.Zero);
    System.Threading.Thread.Sleep(50);
    Tap(vk);
    keybd_event(modifier, 0, 2, UIntPtr.Zero);
    System.Threading.Thread.Sleep(180);
  }
}
'@

$failures = New-Object System.Collections.Generic.List[string]
$checkpoints = New-Object System.Collections.Generic.List[object]
$coverage = [ordered]@{
  initial_load = $false
  white_orientation = $false
  black_orientation = $false
  move = $false
  undo = $false
  pgn_review = $false
  book_review = $false
  rerender = $false
  return = $false
}

function Fail([string]$message) {
  $script:failures.Add($message)
  Write-Host "FAIL: $message"
}
function SafeName($e) { try { return [string]$e.Current.Name } catch { return '' } }
function SafeId($e) { try { return [string]$e.Current.AutomationId } catch { return '' } }
function SafeType($e) { try { return [string]$e.Current.ControlType.ProgrammaticName } catch { return '' } }
function SafeOffscreen($e) { try { return [bool]$e.Current.IsOffscreen } catch { return $true } }
function SafeFocus($e) { try { return [bool]$e.Current.HasKeyboardFocus } catch { return $false } }
function SafeBounds($e) {
  try {
    $b = $e.Current.BoundingRectangle
    return @([double]$b.Left,[double]$b.Top,[double]$b.Width,[double]$b.Height)
  } catch { return $null }
}
function RuntimeId($e) { try { return (($e.GetRuntimeId() | ForEach-Object { [string]$_ }) -join '.') } catch { return '' } }

$proc = Get-Process -Id $AppPid -ErrorAction Stop
$watch = [Diagnostics.Stopwatch]::StartNew()
while($watch.ElapsedMilliseconds -lt 30000 -and $proc.MainWindowHandle -eq 0) {
  if($proc.HasExited) { throw "V2 process exited before UIA attach: $($proc.ExitCode)" }
  Start-Sleep -Milliseconds 250
  $proc.Refresh()
}
if($proc.MainWindowHandle -eq 0) { throw 'V2 main window handle was not available' }
[V2SquareKeys]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
Start-Sleep -Seconds 2
$root = [System.Windows.Automation.AutomationElement]::FromHandle($proc.MainWindowHandle)
if($null -eq $root) { throw 'UIAutomationElement.FromHandle returned null for V2 window' }

function AllElements {
  return @($script:root.FindAll(
    [System.Windows.Automation.TreeScope]::Subtree,
    [System.Windows.Automation.Condition]::TrueCondition
  ))
}

function CoordFor($e) {
  $id = SafeId $e
  if($id -match '^sq-([a-h][1-8])$') { return $Matches[1].ToLowerInvariant() }
  $name = SafeName $e
  $type = SafeType $e
  if($type -match 'DataItem|Custom' -and $name -match '^([a-h][1-8])(?:$|[\s,;:–—-])') {
    return $Matches[1].ToLowerInvariant()
  }
  return $null
}

function FindByIdOrName([string]$id, [string]$namePattern, [string]$typePattern='') {
  foreach($e in (AllElements)) {
    $eid = SafeId $e; $name = SafeName $e; $type = SafeType $e
    if($typePattern -and $type -notmatch $typePattern) { continue }
    if(($id -and $eid -eq $id) -or ($namePattern -and $name -match $namePattern)) { return $e }
  }
  return $null
}

function InvokeElement($e, [string]$description) {
  if($null -eq $e) { Fail "$description element not found"; return $false }
  try {
    $p = $e.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    if($null -eq $p) { Fail "$description has no InvokePattern"; return $false }
    $p.Invoke(); Start-Sleep -Milliseconds 500; return $true
  } catch { Fail "$description invocation failed: $($_.Exception.Message)"; return $false }
}

function SquareElement([string]$coord) {
  $coord = $coord.ToLowerInvariant()
  $id = "sq-$coord"
  foreach($e in (AllElements)) { if((SafeId $e) -eq $id) { return $e } }
  foreach($e in (AllElements)) { if((CoordFor $e) -eq $coord) { return $e } }
  return $null
}

function FocusedCoord {
  foreach($e in (AllElements)) {
    if(SafeFocus $e) {
      $c = CoordFor $e
      if($c) { return $c }
    }
  }
  return ''
}

function FocusSquare([string]$coord) {
  $e = SquareElement $coord
  if($null -eq $e) { Fail "square $coord not found for focus"; return $false }
  try { $e.SetFocus(); Start-Sleep -Milliseconds 180 } catch { Fail "SetFocus failed for $coord: $($_.Exception.Message)"; return $false }
  $focused = FocusedCoord
  if($focused -ne $coord) { Fail "focus expected $coord but UIA reported '$focused'"; return $false }
  return $true
}

function Snapshot([string]$label) {
  $raw = New-Object System.Collections.Generic.List[object]
  foreach($e in (AllElements)) {
    $coord = CoordFor $e
    if(-not $coord) { continue }
    $raw.Add([pscustomobject]@{
      coord=$coord
      automation_id=(SafeId $e)
      name=(SafeName $e)
      control_type=(SafeType $e)
      offscreen=(SafeOffscreen $e)
      focused=(SafeFocus $e)
      runtime_id=(RuntimeId $e)
      bounds=(SafeBounds $e)
    })
  }
  $groups = @($raw | Group-Object coord)
  $uniqueCoords = @($groups | ForEach-Object { $_.Name } | Sort-Object)
  $duplicateCoords = @($groups | Where-Object {$_.Count -ne 1} | ForEach-Object { "$($_.Name):$($_.Count)" })
  $nonEmptyIds = @($raw | Where-Object {$_.automation_id} | ForEach-Object {$_.automation_id})
  $duplicateIds = @($nonEmptyIds | Group-Object | Where-Object {$_.Count -gt 1} | ForEach-Object {$_.Name})
  $badNames = @($raw | Where-Object { $_.name -notmatch ('^' + [regex]::Escape($_.coord) + '(?:$|[\s,;:–—-])') } | ForEach-Object {$_.coord})
  $expected = @(); foreach($file in 'a','b','c','d','e','f','g','h'){foreach($rank in 1..8){$expected += "$file$rank"}}
  $missing = @($expected | Where-Object {$_ -notin $uniqueCoords})
  $canonicalIdCount = @($raw | Where-Object {$_.automation_id -eq ('sq-' + $_.coord)}).Count
  $pieceNamed = @($raw | Where-Object {$_.name -ne $_.coord}).Count
  $row = [pscustomobject]@{
    checkpoint=$label
    observed_square_nodes=$raw.Count
    unique_coordinate_count=$uniqueCoords.Count
    missing_coordinates=$missing
    duplicate_coordinates=$duplicateCoords
    duplicate_nonempty_automation_ids=$duplicateIds
    canonical_automation_id_count=$canonicalIdCount
    coordinate_name_failures=$badNames
    piece_named_square_count=$pieceNamed
    focused_coordinate=(FocusedCoord)
    squares=@($raw | Sort-Object coord)
  }
  $script:checkpoints.Add($row)
  if($raw.Count -ne 64) { Fail "${label}: expected exactly 64 connected semantic square nodes, got $($raw.Count)" }
  if($uniqueCoords.Count -ne 64 -or $missing.Count -gt 0) { Fail "${label}: expected all 64 canonical coordinates; missing=$($missing -join ',')" }
  if($duplicateCoords.Count -gt 0) { Fail "${label}: duplicate logical squares: $($duplicateCoords -join ',')" }
  if($duplicateIds.Count -gt 0) { Fail "${label}: duplicate non-empty AutomationId values: $($duplicateIds -join ',')" }
  if($badNames.Count -gt 0) { Fail "${label}: accessible names do not begin with canonical coordinate: $($badNames -join ',')" }
  if($pieceNamed -eq 0) { Fail "${label}: no square exposes coordinate plus piece information" }
  return $row
}

function WaitForName([string]$coord, [bool]$pieceExpected, [int]$timeoutMs=5000) {
  $sw=[Diagnostics.Stopwatch]::StartNew()
  while($sw.ElapsedMilliseconds -lt $timeoutMs) {
    $e=SquareElement $coord
    if($e){
      $n=SafeName $e
      $hasPiece=($n -ne $coord)
      if($hasPiece -eq $pieceExpected){return $true}
    }
    Start-Sleep -Milliseconds 150
  }
  return $false
}

$preCount = @((AllElements) | Where-Object {(CoordFor $_)}).Count
if($preCount -ne 0) { Fail "initial hidden board leaked $preCount semantic square nodes before board entry" }

$launcher = FindByIdOrName 'board-launcher' '(?i)(увійти.*дош|enter.*board|шахов.*дош)' 'Button'
if(InvokeElement $launcher 'board launcher') {
  Start-Sleep -Seconds 1
  $initial = Snapshot 'initial_load'
  $coverage.initial_load = ($initial.unique_coordinate_count -eq 64)
  $a1=SquareElement 'a1'; $h8=SquareElement 'h8'; $a1b=SafeBounds $a1; $h8b=SafeBounds $h8
  if($a1b -and $h8b -and $a1b[0] -lt $h8b[0] -and $a1b[1] -gt $h8b[1]) {
    $coverage.white_orientation = $true
  } else {
    Fail 'initial board geometry did not prove white orientation (a1 left/below h8)'
  }
}

if(FocusSquare 'a1') {
  [V2SquareKeys]::Tap(0x25); if((FocusedCoord) -ne 'a1'){Fail 'white orientation ArrowLeft escaped a1 edge'}
  [V2SquareKeys]::Tap(0x28); if((FocusedCoord) -ne 'a1'){Fail 'white orientation ArrowDown escaped a1 edge'}
  [V2SquareKeys]::Tap(0x27); if((FocusedCoord) -ne 'b1'){Fail 'white orientation ArrowRight from a1 did not reach b1'}
  if(FocusSquare 'a1') {[V2SquareKeys]::Tap(0x26); if((FocusedCoord) -ne 'a2'){Fail 'white orientation ArrowUp from a1 did not reach a2'}}
}

if(FocusSquare 'e2') {
  [V2SquareKeys]::Tap(0x0D)
  Start-Sleep -Milliseconds 250
  if(FocusSquare 'e4') {
    [V2SquareKeys]::Tap(0x20)
    if(-not (WaitForName 'e2' $false)) { Fail 'Enter/Space activation did not vacate e2 after legal e2-e4' }
    if(-not (WaitForName 'e4' $true)) { Fail 'Enter/Space activation did not expose piece name on e4 after legal e2-e4' }
    $move = Snapshot 'move'
    $coverage.move = ($move.unique_coordinate_count -eq 64)
    if((FocusedCoord) -ne 'e4') { Fail "focus continuity after move expected e4, got '$(FocusedCoord)'" }
  }
}

if(FocusSquare 'e4') {
  [V2SquareKeys]::Chord(0x11,0x5A)
  if(-not (WaitForName 'e2' $true)) { Fail 'Ctrl+Z undo did not restore piece name on e2' }
  if(-not (WaitForName 'e4' $false)) { Fail 'Ctrl+Z undo did not clear e4 piece name' }
  $undo = Snapshot 'undo'
  $coverage.undo = ($undo.unique_coordinate_count -eq 64)
  if((FocusedCoord) -ne 'e4') { Fail "focus continuity after undo expected e4, got '$(FocusedCoord)'" }
}

if(FocusSquare 'e2') {
  [V2SquareKeys]::Tap(0x0D)
  if(FocusSquare 'e4') {[V2SquareKeys]::Tap(0x20); WaitForName 'e4' $true | Out-Null}
  if(FocusSquare 'e4') {[V2SquareKeys]::Chord(0x11,0x5A); WaitForName 'e2' $true | Out-Null}
  $rerender = Snapshot 'rerender'
  $coverage.rerender = ($rerender.unique_coordinate_count -eq 64)
  if((FocusedCoord) -ne 'e4') { Fail "focus continuity after explicit rerender cycle expected e4, got '$(FocusedCoord)'" }
}

# Probe only a WebView button on the current V2/game surface. Native Teacher/Classroom menu items are not main-board orientation.
$orientation = FindByIdOrName 'board-orientation' '(?i)(flip board|board orientation|перевернути дошку|орієнтац.*дош)' 'Button'
if($null -eq $orientation) {
  Fail 'MAIN_BOARD_ORIENTATION_CONTROL_MISSING: current V2 standalone exposes no main-board white/black orientation button through connected WebView2/UIA'
} elseif(InvokeElement $orientation 'main-board orientation') {
  Start-Sleep -Milliseconds 800
  $black = Snapshot 'black_orientation'
  $coverage.black_orientation = ($black.unique_coordinate_count -eq 64)
  if(FocusSquare 'a1') {
    $a1=SquareElement 'a1'; $b=(SafeBounds $a1)
    $h8=SquareElement 'h8'; $hb=(SafeBounds $h8)
    if($b -and $hb) {
      if($b[0] -gt $hb[0]) {[V2SquareKeys]::Tap(0x27)} else {[V2SquareKeys]::Tap(0x25)}
      if((FocusedCoord) -ne 'a1'){Fail 'black orientation horizontal outward arrow escaped a1 edge'}
      if($b[1] -lt $hb[1]) {[V2SquareKeys]::Tap(0x26)} else {[V2SquareKeys]::Tap(0x28)}
      if((FocusedCoord) -ne 'a1'){Fail 'black orientation vertical outward arrow escaped a1 edge'}
    }
  }
}

$report = [ordered]@{
  schema='accessible-chess-v2-current-64-square-uia-v1'
  product_sha=$ProductSha
  app_pid=$AppPid
  window_title=(SafeName $root)
  product_mutation='NONE'
  real_webview2_uia=$true
  identity_contract='DOM ids are sq-<coordinate>; connected UIA identity is coordinate-first accessible Name because WebView2 does not guarantee HTML id -> AutomationId projection.'
  coverage=$coverage
  checkpoints=@($checkpoints)
  failures=@($failures)
  acceptance_pass=($failures.Count -eq 0 -and @($coverage.Values | Where-Object {$_ -ne $true}).Count -eq 0)
  note='PGN review, Book review and Return are never inferred from static state. They remain false until exercised through the real current standalone. UIA RuntimeId may change on rerender. NVDA_VERIFIED=NO; HUMAN_TESTED=NO.'
}
$parent=Split-Path -Parent $ReportPath
if($parent -and -not (Test-Path $parent)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
$report | ConvertTo-Json -Depth 12 | Set-Content -Path $ReportPath -Encoding UTF8
$report | ConvertTo-Json -Depth 5 | Write-Host

if($failures.Count -gt 0) { exit 1 }
if(-not $report.acceptance_pass) { exit 2 }
exit 0
