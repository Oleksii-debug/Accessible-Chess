param(
  [Parameter(Mandatory=$true)][int]$AppPid,
  [string]$ProductRoot='.'
)

$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

function Get-RuntimeIdText($Element) {
  try { return (($Element.GetRuntimeId() | ForEach-Object { [string]$_ }) -join '.') } catch { return '' }
}

function Get-ElementKey($Element) {
  $rid=Get-RuntimeIdText $Element
  if($rid){ return 'rid:'+ $rid }
  try { return 'obj:'+([string]$Element.GetHashCode()) } catch { return '' }
}

function Convert-HexHwnd([string]$Value) {
  if([string]::IsNullOrWhiteSpace($Value)){ throw 'Empty HWND value' }
  $text=$Value.Trim()
  if($text.StartsWith('0x',[System.StringComparison]::OrdinalIgnoreCase)){
    return [IntPtr]([Convert]::ToInt64($text.Substring(2),16))
  }
  return [IntPtr]([int64]$text)
}

function Get-ProviderRootElements($Report) {
  $roots=New-Object System.Collections.Generic.List[object]
  foreach($row in @($Report.root_attempts)){
    if(-not $row.connected_to_app -or -not $row.from_handle_success -or -not $row.provider_subtree_seen){ continue }
    $hwnd=Convert-HexHwnd ([string]$row.hwnd)
    $ae=[System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
    if($null -eq $ae){ throw "AutomationElement.FromHandle returned null for retained provider root $($row.hwnd)" }
    $roots.Add($ae)
  }
  if($roots.Count -eq 0){ throw 'No retained connected provider-bearing roots are available for packaged interaction' }
  return @($roots)
}

function Get-ControlViewElements($Roots) {
  $walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
  $stack=New-Object System.Collections.Stack
  foreach($r in @($Roots)){ $stack.Push($r) }
  $seen=New-Object 'System.Collections.Generic.HashSet[string]'
  $items=New-Object System.Collections.Generic.List[object]
  $cap=20000
  while($stack.Count -gt 0){
    if($items.Count -ge $cap){ throw "Strict interaction traversal cap reached at $cap elements" }
    $e=$stack.Pop()
    $key=Get-ElementKey $e
    if($key -and -not $seen.Add($key)){ continue }
    $items.Add($e)
    try {
      $kids=New-Object System.Collections.Generic.List[object]
      $child=$walker.GetFirstChild($e)
      while($null -ne $child){
        $kids.Add($child)
        $child=$walker.GetNextSibling($child)
      }
      for($i=$kids.Count-1;$i -ge 0;$i--){ $stack.Push($kids[$i]) }
    } catch {
      $rid=Get-RuntimeIdText $e
      throw "Strict ControlView child enumeration failed at runtime_id=${rid}: $($_.Exception.GetType().FullName): $($_.Exception.Message)"
    }
  }
  return @($items)
}

function Find-ByRuntimeId($Elements,[string]$RuntimeId) {
  foreach($e in @($Elements)){
    if((Get-RuntimeIdText $e) -eq $RuntimeId){ return $e }
  }
  return $null
}

function Find-ByAutomationIdOrName($Elements,[string]$AutomationId,[string]$NameRegex,[string]$ControlTypeName='') {
  foreach($e in @($Elements)){
    try {
      $ct=[string]$e.Current.ControlType.ProgrammaticName
      if($ControlTypeName -and $ct -ne $ControlTypeName){ continue }
      $id=[string]$e.Current.AutomationId
      $name=[string]$e.Current.Name
      if(($AutomationId -and $id -eq $AutomationId) -or ($NameRegex -and $name -match $NameRegex)){ return $e }
    } catch { continue }
  }
  return $null
}

function Get-ValuePattern($Element,[string]$Label) {
  try {
    $p=$Element.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    if($null -eq $p){ throw 'null ValuePattern' }
    return $p
  } catch {
    throw "$Label does not expose ValuePattern: $($_.Exception.Message)"
  }
}

function Assert-MoveElementStrict($Move,[string]$ExpectedRuntimeId) {
  if($null -eq $Move){ throw 'Original Move Edit runtime identity could not be reacquired from connected provider roots' }
  $rid=Get-RuntimeIdText $Move
  if($rid -ne $ExpectedRuntimeId){ throw "Move runtime identity drift: expected '$ExpectedRuntimeId' got '$rid'" }
  $name=[string]$Move.Current.Name
  if($name -notmatch '^(Хід|Move)$'){ throw "Move accessible name is not concise Хід/Move: '$name'" }
  if(-not [bool]$Move.Current.IsEnabled){ throw 'Move Edit is disabled' }
  if(-not [bool]$Move.Current.IsKeyboardFocusable){ throw 'Move Edit is not keyboard-focusable' }
  if([bool]$Move.Current.IsOffscreen){ throw 'Move Edit is offscreen in strict packaged gate' }
  $rect=$Move.Current.BoundingRectangle
  if($rect.Width -le 0 -or $rect.Height -le 0){ throw "Move Edit has non-positive bounds: $rect" }
  $null=Get-ValuePattern $Move 'Move Edit'
}

function Rewalk-ConnectedUi($Report) {
  $roots=Get-ProviderRootElements $Report
  return @(Get-ControlViewElements $roots)
}

function Get-FenValue($Elements) {
  $fen=Find-ByAutomationIdOrName $Elements 'fen-input' '^FEN( позиції)?$' 'ControlType.Edit'
  if($null -eq $fen){ throw 'FEN Edit not found through connected provider roots' }
  $vp=Get-ValuePattern $fen 'FEN Edit'
  return [string]$vp.Current.Value
}

function Assert-E4HistoryVisible($Elements) {
  foreach($e in @($Elements)){
    try {
      $ct=[string]$e.Current.ControlType.ProgrammaticName
      if($ct -in @('ControlType.DataItem','ControlType.Custom','ControlType.Edit')){ continue }
      $name=[string]$e.Current.Name
      if($name -match '(?<![A-Za-z0-9])e\s*4(?![A-Za-z0-9])'){ return }
    } catch { continue }
  }
  throw 'Packaged accessible move/history surface does not expose e4 after legal submission'
}

function Get-SquareName($Element) {
  try {
    $id=[string]$Element.Current.AutomationId
    if($id -match '^sq-([a-h][1-8])$'){ return $matches[1] }
    $name=[string]$Element.Current.Name
    if($name -match '(?<![A-Za-z0-9])([a-h][1-8])(?![A-Za-z0-9])'){ return $matches[1] }
  } catch {}
  return ''
}

function Get-SemanticSquares($Elements) {
  $bySquare=@{}
  foreach($e in @($Elements)){
    $sq=Get-SquareName $e
    if($sq -and -not $bySquare.ContainsKey($sq)){ $bySquare[$sq]=$e }
  }
  return $bySquare
}

function Assert-NoRawExceptionNoise($Elements) {
  foreach($e in @($Elements)){
    try {
      $name=[string]$e.Current.Name
      if($name -match 'Traceback|ValueError|binding must contain a non-modifier key'){ throw "Raw exception/developer error leaked into packaged accessibility tree: '$name'" }
    } catch {
      if($_.Exception.Message -match '^Raw exception/developer error leaked'){ throw }
    }
  }
}

$helperPath=Join-Path $PSScriptRoot 'stage1_uia_topology_v5.ps1'
$classifierPath=Join-Path $PSScriptRoot 'stage1_uia_topology_classify.py'
if(-not (Test-Path $helperPath)){ throw "Topology helper missing: $helperPath" }
if(-not (Test-Path $classifierPath)){ throw "Topology classifier missing: $classifierPath" }

& $helperPath -AppPid $AppPid
if($LASTEXITCODE -ne 0){ throw 'Cross-process UIA topology helper failed' }
if(-not (Test-Path 'uia-topology-report-v5.json')){ throw 'Topology helper did not retain uia-topology-report-v5.json' }
Copy-Item 'uia-topology-report-v5.json' 'uia-topology-strict-raw.json' -Force
Copy-Item 'uia-topology-report-v5.json' 'uia-topology-strict.json' -Force
python $classifierPath 'uia-topology-strict.json' --product-root $ProductRoot
if($LASTEXITCODE -ne 0){ throw 'Fail-closed topology classifier failed in strict release' }

$report=Get-Content 'uia-topology-strict.json' -Raw | ConvertFrom-Json
if([string]$report.classification -ne 'A' -or -not [bool]$report.evidence_complete){
  $reasons=@($report.classification_reasons) -join ' | '
  throw "Strict packaged UIA did not prove one original valid Move Edit. classification=$($report.classification) complete=$($report.evidence_complete) reasons=$reasons"
}
$moveEvals=@($report.move_edit_evaluations)
if($moveEvals.Count -ne 1 -or -not [bool]$moveEvals[0].strict_valid -or -not [bool]$moveEvals[0].proven_original){
  throw "Strict packaged UIA Move identity is ambiguous or invalid: count=$($moveEvals.Count)"
}
$moveRid=[string]$moveEvals[0].best_occurrence.runtime_id
if([string]::IsNullOrWhiteSpace($moveRid)){ throw 'Strict valid Move identity has no runtime ID' }

$summary=[ordered]@{
  product_sha=$env:SOURCE_INTEGRATION_SHA
  app_pid=$AppPid
  classification=[string]$report.classification
  evidence_complete=[bool]$report.evidence_complete
  move_runtime_id=$moveRid
  move_occurrence_count=[int]$moveEvals[0].occurrence_count
  e4_fen=''
  invalid_e9_fen_unchanged=$false
  clipboard=''
  semantic_square_count=0
  board_focus_continuity=$false
  raw_exception_noise=$false
}

try {
  $elements=Rewalk-ConnectedUi $report
  $move=Find-ByRuntimeId $elements $moveRid
  Assert-MoveElementStrict $move $moveRid
  Assert-NoRawExceptionNoise $elements

  $submit=Find-ByAutomationIdOrName $elements 'move-submit' '^(Зробити хід|Make move)$' 'ControlType.Button'
  $boardLauncher=Find-ByAutomationIdOrName $elements 'board-launcher' '^(Увійти на дошку|Enter board)$' 'ControlType.Button'
  if($null -eq $submit -or $null -eq $boardLauncher){ throw 'Move submit button or board launcher not found through connected provider roots' }

  $ws=New-Object -ComObject WScript.Shell
  $null=$ws.AppActivate($AppPid)
  $move.SetFocus()
  Start-Sleep -Milliseconds 300
  $ws.SendKeys('e4')
  $ws.SendKeys('{ENTER}')
  Start-Sleep -Seconds 2

  $elements=Rewalk-ConnectedUi $report
  $move=Find-ByRuntimeId $elements $moveRid
  Assert-MoveElementStrict $move $moveRid
  $moveVp=Get-ValuePattern $move 'Move Edit after e4'
  if([string]$moveVp.Current.Value -ne ''){ throw "Legal e4 did not clear input: '$($moveVp.Current.Value)'" }
  $focused=[System.Windows.Automation.AutomationElement]::FocusedElement
  $focusedRid=if($focused){Get-RuntimeIdText $focused}else{''}
  if($focusedRid -ne $moveRid){ throw "Focus did not return to the original Move Edit after e4: focused runtime_id='$focusedRid'" }

  $fenAfterE4=Get-FenValue $elements
  if($fenAfterE4 -notmatch '^rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1$'){
    throw "Legal e4 did not produce the canonical packaged FEN: '$fenAfterE4'"
  }
  $summary.e4_fen=$fenAfterE4
  Assert-E4HistoryVisible $elements

  $ws.SendKeys('e9')
  $ws.SendKeys('{ENTER}')
  Start-Sleep -Milliseconds 900
  $elements=Rewalk-ConnectedUi $report
  $move=Find-ByRuntimeId $elements $moveRid
  Assert-MoveElementStrict $move $moveRid
  $moveVp=Get-ValuePattern $move 'Move Edit after invalid e9'
  if([string]$moveVp.Current.Value -ne 'e9'){ throw "Invalid move text was not preserved: '$($moveVp.Current.Value)'" }
  $fenAfterInvalid=Get-FenValue $elements
  if($fenAfterInvalid -ne $fenAfterE4){ throw "Invalid e9 mutated canonical FEN: before='$fenAfterE4' after='$fenAfterInvalid'" }
  $summary.invalid_e9_fen_unchanged=$true
  Assert-NoRawExceptionNoise $elements

  Set-Clipboard -Value '__accessible_chess_clipboard_sentinel__'
  $move.SetFocus()
  $ws.SendKeys('^a')
  $ws.SendKeys('^c')
  Start-Sleep -Milliseconds 400
  $clip=([string](Get-Clipboard -Raw)).Trim()
  if($clip -ne 'e9'){ throw "Native Ctrl+A/Ctrl+C did not copy the Move input value: clipboard='$clip'" }
  $summary.clipboard=$clip

  $moveVp.SetValue('')
  $elements=Rewalk-ConnectedUi $report
  $boardLauncher=Find-ByAutomationIdOrName $elements 'board-launcher' '^(Увійти на дошку|Enter board)$' 'ControlType.Button'
  if($null -eq $boardLauncher){ throw 'Board launcher disappeared before board-focus gate' }
  $boardLauncher.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
  Start-Sleep -Milliseconds 600

  $elements=Rewalk-ConnectedUi $report
  $squares=Get-SemanticSquares $elements
  $summary.semantic_square_count=$squares.Count
  if($squares.Count -ne 64){ throw "Packaged board does not expose exactly 64 unique semantic squares: $($squares.Count)" }
  if(-not $squares.ContainsKey('a3')){ throw 'Semantic board square a3 not found' }
  if(-not $squares.ContainsKey('e4')){ throw 'Semantic board square e4 not found after legal e4' }
  $e4Name=[string]$squares['e4'].Current.Name
  if([string]::IsNullOrWhiteSpace($e4Name)){ throw 'Semantic board square e4 has no accessible name' }

  $target=$squares['a3']
  $targetId=[string]$target.Current.AutomationId
  $targetName=[string]$target.Current.Name
  $target.SetFocus()
  Start-Sleep -Milliseconds 250

  $elements=Rewalk-ConnectedUi $report
  $move=Find-ByRuntimeId $elements $moveRid
  Assert-MoveElementStrict $move $moveRid
  $moveVp=Get-ValuePattern $move 'Move Edit before board rerender'
  $moveVp.SetValue('e5')
  $submit=Find-ByAutomationIdOrName $elements 'move-submit' '^(Зробити хід|Make move)$' 'ControlType.Button'
  if($null -eq $submit){ throw 'Move submit button disappeared before board rerender' }
  $submit.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
  Start-Sleep -Seconds 2

  $afterFocus=[System.Windows.Automation.AutomationElement]::FocusedElement
  if($null -eq $afterFocus){ throw 'No focused element after state-driven board rerender' }
  $afterId=[string]$afterFocus.Current.AutomationId
  $afterName=[string]$afterFocus.Current.Name
  $sameSemantic=(($targetId -and $afterId -eq $targetId) -or ($targetName -and $afterName -eq $targetName))
  if(-not $sameSemantic){ throw "Board focus continuity failed: before id='$targetId' name='$targetName'; after id='$afterId' name='$afterName'" }
  $summary.board_focus_continuity=$true

  $elements=Rewalk-ConnectedUi $report
  Assert-NoRawExceptionNoise $elements
  $summary.raw_exception_noise=$false
  $summary|ConvertTo-Json -Depth 8|Set-Content -Encoding UTF8 'packaged-uia-strict-summary.json'
  Write-Output "STRICT PACKAGED CROSS-PROCESS UIA + e4/e9/CLIPBOARD/64-SQUARE/FOCUS PASS move_rid=$moveRid squares=$($squares.Count)"
} finally {
  $proc=Get-Process -Id $AppPid -ErrorAction SilentlyContinue
  if($proc){ Stop-Process -Id $AppPid -Force -ErrorAction SilentlyContinue }
}
