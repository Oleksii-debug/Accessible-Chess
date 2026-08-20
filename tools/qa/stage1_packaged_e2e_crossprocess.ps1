param(
  [Parameter(Mandatory=$true)][int]$AppPid,
  [string]$ProductRoot='.'
)

$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

function RuntimeId($e) { try { (($e.GetRuntimeId() | ForEach-Object {[string]$_}) -join '.') } catch { '' } }
function ElementKey($e) { $r=RuntimeId $e; if($r){return 'rid:'+$r}; try{return 'obj:'+([string]$e.GetHashCode())}catch{return ''} }
function Hwnd([string]$v) { $t=$v.Trim(); if($t.StartsWith('0x',[StringComparison]::OrdinalIgnoreCase)){return [IntPtr]([Convert]::ToInt64($t.Substring(2),16))}; return [IntPtr]([int64]$t) }

function ProviderRoots($report) {
  $out=@()
  foreach($row in @($report.root_attempts)) {
    if(-not $row.connected_to_app -or -not $row.from_handle_success -or -not $row.provider_subtree_seen){continue}
    $e=[System.Windows.Automation.AutomationElement]::FromHandle((Hwnd ([string]$row.hwnd)))
    if($null -eq $e){throw "FromHandle returned null for retained provider root $($row.hwnd)"}
    $out += ,$e
  }
  if($out.Count -eq 0){throw 'No connected provider-bearing roots available'}
  return $out
}

function ControlElements($roots) {
  $walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
  $stack=New-Object System.Collections.Stack
  foreach($r in $roots){$stack.Push($r)}
  $seen=New-Object 'System.Collections.Generic.HashSet[string]'
  $out=@(); $cap=20000
  while($stack.Count -gt 0){
    if($out.Count -ge $cap){throw "Strict interaction traversal cap reached at $cap"}
    $e=$stack.Pop(); $k=ElementKey $e
    if($k -and -not $seen.Add($k)){continue}
    $out += ,$e
    try {
      $kids=@(); $c=$walker.GetFirstChild($e)
      while($null -ne $c){$kids += ,$c; $c=$walker.GetNextSibling($c)}
      for($i=$kids.Count-1;$i -ge 0;$i--){$stack.Push($kids[$i])}
    } catch {
      $rid=RuntimeId $e
      throw "ControlView enumeration failed at runtime_id=${rid}: $($_.Exception.GetType().FullName): $($_.Exception.Message)"
    }
  }
  return $out
}

function Rewalk($report){ ControlElements (ProviderRoots $report) }
function FindRuntime($els,[string]$rid){ foreach($e in @($els)){if((RuntimeId $e) -eq $rid){return $e}}; return $null }
function FindControl($els,[string]$id,[string]$nameRx,[string]$ct=''){
  foreach($e in @($els)){
    try{
      if($ct -and [string]$e.Current.ControlType.ProgrammaticName -ne $ct){continue}
      if(($id -and [string]$e.Current.AutomationId -eq $id) -or ($nameRx -and [string]$e.Current.Name -match $nameRx)){return $e}
    }catch{}
  }
  return $null
}
function ValuePattern($e,[string]$label){try{$p=$e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern);if($null -eq $p){throw 'null'};return $p}catch{throw "$label has no ValuePattern: $($_.Exception.Message)"}}
function Invoke($e,[string]$label){try{$p=$e.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern);if($null -eq $p){throw 'null'};$p.Invoke()}catch{throw "$label has no usable InvokePattern: $($_.Exception.Message)"}}

function AssertMoveStrict($move,[string]$rid){
  if($null -eq $move){throw 'Original Move Edit could not be reacquired'}
  if((RuntimeId $move) -ne $rid){throw 'Move runtime identity drift'}
  $n=[string]$move.Current.Name
  if($n -notmatch '^(Хід|Move)$'){throw "Move name drift: '$n'"}
  if(-not [bool]$move.Current.IsEnabled){throw 'Move Edit disabled'}
  if(-not [bool]$move.Current.IsKeyboardFocusable){throw 'Move Edit not keyboard-focusable'}
  if([bool]$move.Current.IsOffscreen){throw 'Move Edit offscreen in normal move-entry phase'}
  $r=$move.Current.BoundingRectangle
  if($r.Width -le 0 -or $r.Height -le 0){throw "Move Edit has non-positive bounds: $r"}
  $null=ValuePattern $move 'Move Edit'
}
function Fen($els){$e=FindControl $els 'fen-input' '^FEN( позиції)?$' 'ControlType.Edit';if($null -eq $e){throw 'FEN Edit not found'};[string](ValuePattern $e 'FEN Edit').Current.Value}
function SquareToken($e){try{$id=[string]$e.Current.AutomationId;if($id -match '^sq-([a-h][1-8])$'){return $matches[1]};$n=[string]$e.Current.Name;if($n -match '(?<![A-Za-z0-9])([a-h][1-8])(?![A-Za-z0-9])'){return $matches[1]}}catch{};''}
function Squares($els){$h=@{};foreach($e in @($els)){$s=SquareToken $e;if($s -and -not $h.ContainsKey($s)){$h[$s]=$e}};$h}
function SameSemanticFocus($target,$focused){if($null -eq $focused){return $false};$id=[string]$target.Current.AutomationId;$n=[string]$target.Current.Name;$fid=[string]$focused.Current.AutomationId;$fn=[string]$focused.Current.Name;return (($id -and $fid -eq $id) -or ($n -and $fn -eq $n))}
function FocusDescription($focused){
  if($null -eq $focused){return "runtime_id='' automation_id='' name='' control_type=''"}
  try{return "runtime_id='$(RuntimeId $focused)' automation_id='$([string]$focused.Current.AutomationId)' name='$([string]$focused.Current.Name)' control_type='$([string]$focused.Current.ControlType.ProgrammaticName)'"}catch{return "runtime_id='$(RuntimeId $focused)' automation_id='' name='' control_type=''"}
}
function AssertFocusedRuntimeEventually([string]$rid,[string]$label,[int]$timeoutMs=4000){
  $sw=[System.Diagnostics.Stopwatch]::StartNew(); $last=$null
  while($sw.ElapsedMilliseconds -lt $timeoutMs){
    try{$last=[System.Windows.Automation.AutomationElement]::FocusedElement;if((RuntimeId $last) -eq $rid){return}}catch{}
    Start-Sleep -Milliseconds 100
  }
  throw "$label focus did not converge to runtime_id='$rid'; final $(FocusDescription $last)"
}
function AssertSemanticFocusEventually($target,[string]$label,[int]$timeoutMs=4000){
  $sw=[System.Diagnostics.Stopwatch]::StartNew(); $last=$null
  while($sw.ElapsedMilliseconds -lt $timeoutMs){
    try{$last=[System.Windows.Automation.AutomationElement]::FocusedElement;if(SameSemanticFocus $target $last){return}}catch{}
    Start-Sleep -Milliseconds 100
  }
  throw "$label semantic focus did not converge; target automation_id='$([string]$target.Current.AutomationId)' name='$([string]$target.Current.Name)'; final $(FocusDescription $last)"
}
function NoRawError($els){foreach($e in @($els)){try{$n=[string]$e.Current.Name;if($n -match 'Traceback|ValueError|binding must contain a non-modifier key'){throw "Raw exception leaked: '$n'"}}catch{if($_.Exception.Message -match '^Raw exception leaked'){throw}}}}
function HasE4History($els){foreach($e in @($els)){try{$ct=[string]$e.Current.ControlType.ProgrammaticName;if($ct -in @('ControlType.DataItem','ControlType.Custom','ControlType.Edit')){continue};if([string]$e.Current.Name -match '(?<![A-Za-z0-9])e\s*4(?![A-Za-z0-9])'){return $true}}catch{}};$false}

$topology=Join-Path $PSScriptRoot 'stage1_uia_topology_v5.ps1'
$classifier=Join-Path $PSScriptRoot 'stage1_uia_topology_classify.py'
& $topology -AppPid $AppPid
if(-not (Test-Path 'uia-topology-report-v5.json')){throw 'Topology report missing'}
Copy-Item uia-topology-report-v5.json uia-topology-strict-raw.json -Force
Copy-Item uia-topology-report-v5.json uia-topology-strict.json -Force
$startupReport=Get-Content uia-topology-strict.json -Raw|ConvertFrom-Json
$errorNodes=@($startupReport.nodes|Where-Object {
  $startupText=([string]$_.name)+' '+([string]$_.value)+' '+([string]$_.ancestor_path)
  $startupText -match 'ERR_UNSAFE_PORT|Hmmm.*reach this page|Network error|chrome-error://|edge-error://'
})
if($errorNodes.Count -gt 0){
  $sample=@($errorNodes|Select-Object -First 5|ForEach-Object {([string]$_.control_type)+': '+([string]$_.name)}) -join ' | '
  throw "Chromium/WebView2 error page detected before Stage 1 interaction: $sample"
}
$appDocuments=@($startupReport.nodes|Where-Object {
  [string]$_.control_type -eq 'ControlType.Document' -and [bool]$_.source_root_connected -and [string]$_.name -eq 'Accessible Chess'
})
if($appDocuments.Count -eq 0){
  $documentNames=@($startupReport.nodes|Where-Object {[string]$_.control_type -eq 'ControlType.Document'}|ForEach-Object {[string]$_.name}) -join ' | '
  throw "Real Accessible Chess document missing before Stage 1 interaction; documents=$documentNames"
}
Write-Output "REAL ACCESSIBLE CHESS DOCUMENT STARTUP PASS documents=$($appDocuments.Count)"
python $classifier uia-topology-strict.json --product-root $ProductRoot
if($LASTEXITCODE -ne 0){throw 'Fail-closed classifier failed'}
$report=Get-Content uia-topology-strict.json -Raw|ConvertFrom-Json
if([string]$report.classification -ne 'A' -or -not [bool]$report.evidence_complete){throw "Packaged UIA not A/complete: $($report.classification) $(@($report.classification_reasons)-join ' | ')"}
$evals=@($report.move_edit_evaluations)
if($evals.Count -ne 1 -or -not [bool]$evals[0].proven_original -or -not [bool]$evals[0].strict_valid){throw 'Original Move identity not uniquely strict-valid'}
$moveRid=[string]$evals[0].best_occurrence.runtime_id
if(-not $moveRid){throw 'Move runtime ID missing'}

$summary=[ordered]@{product_sha=$env:SOURCE_INTEGRATION_SHA;app_pid=$AppPid;classification='A';evidence_complete=$true;move_runtime_id=$moveRid;e4_fen='';invalid_e9_fen_unchanged=$false;clipboard='';semantic_square_count=0;board_focus_continuity=$false;black_e5_fen='';raw_exception_noise=$false}

try{
  $els=Rewalk $report; $move=FindRuntime $els $moveRid; AssertMoveStrict $move $moveRid; NoRawError $els
  $ws=New-Object -ComObject WScript.Shell; $null=$ws.AppActivate($AppPid); $move.SetFocus(); Start-Sleep -Milliseconds 300
  $ws.SendKeys('e4'); $ws.SendKeys('{ENTER}'); Start-Sleep -Seconds 2

  $els=Rewalk $report; $move=FindRuntime $els $moveRid; AssertMoveStrict $move $moveRid; $vp=ValuePattern $move 'Move after e4'
  if([string]$vp.Current.Value -ne ''){throw 'Legal e4 did not clear input'}
  AssertFocusedRuntimeEventually $moveRid 'Legal e4 refocus'
  $fenE4=Fen $els
  if($fenE4 -ne 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1'){throw "Unexpected e4 FEN: $fenE4"}
  $summary.e4_fen=$fenE4
  if(-not (HasE4History $els)){throw 'e4 missing from accessible move/history surface'}

  $ws.SendKeys('e9'); $ws.SendKeys('{ENTER}'); Start-Sleep -Milliseconds 900
  $els=Rewalk $report; $move=FindRuntime $els $moveRid; AssertMoveStrict $move $moveRid; $vp=ValuePattern $move 'Move after e9'
  if([string]$vp.Current.Value -ne 'e9'){throw 'Invalid e9 text was not preserved'}
  if((Fen $els) -ne $fenE4){throw 'Invalid e9 mutated FEN'}
  $summary.invalid_e9_fen_unchanged=$true; NoRawError $els

  Set-Clipboard -Value '__sentinel__'
  $move.SetFocus()
  AssertFocusedRuntimeEventually $moveRid 'Clipboard focus convergence'
  $focused=[System.Windows.Automation.AutomationElement]::FocusedElement
  if((RuntimeId $focused) -ne $moveRid){throw "Clipboard keyboard focus mismatch: $(FocusDescription $focused)"}
  $vp=ValuePattern $move 'Move before clipboard'
  if([string]$vp.Current.Value -ne 'e9'){throw "Clipboard precondition ValuePattern mismatch: '$([string]$vp.Current.Value)'"}
  $ws.SendKeys('^a')
  Start-Sleep -Milliseconds 250
  AssertFocusedRuntimeEventually $moveRid 'Clipboard selection focus convergence'
  $focused=[System.Windows.Automation.AutomationElement]::FocusedElement
  try{
    $tp=$focused.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
    if($null -eq $tp){throw 'TextPattern unavailable'}
    $selection=@($tp.GetSelection())
    if($selection.Count -lt 1){throw 'No native text selection exposed'}
    $selected=(@($selection|ForEach-Object {$_.GetText(-1)}) -join '')
    if($selected -ne 'e9'){throw "Native Ctrl+A selection mismatch: '$selected'"}
  }catch{
    throw "Native selection proof failed: $($_.Exception.Message)"
  }
  Write-Output 'CLIPBOARD BOUNDED FOCUS/SELECTION PASS'
  $ws.SendKeys('^c')
  Start-Sleep -Milliseconds 400
  $clip=([string](Get-Clipboard -Raw)).Trim()
  if($clip -ne 'e9'){throw "Ctrl+A/Ctrl+C failed: '$clip'"}
  $summary.clipboard=$clip

  $vp.SetValue('e5'); if([string]$vp.Current.Value -ne 'e5'){throw 'Could not prepare e5 before board entry'}
  Write-Output 'Prepared e5 before entering board'

  $els=Rewalk $report
  $boardLauncher=FindControl $els 'board-launcher' '^(Увійти на дошку|Enter board)$' 'ControlType.Button'
  if($null -eq $boardLauncher){throw 'Board launcher missing'}
  Invoke $boardLauncher 'Board launcher'; Start-Sleep -Milliseconds 600
  $els=Rewalk $report; $sq=Squares $els; $summary.semantic_square_count=$sq.Count
  if($sq.Count -ne 64){throw "Expected 64 semantic squares, got $($sq.Count)"}
  if(-not $sq.ContainsKey('a3') -or -not $sq.ContainsKey('e4')){throw 'Required semantic squares a3/e4 missing'}
  $target=$sq['a3']; $target.SetFocus();
  AssertSemanticFocusEventually $target 'Board origin establishment'

  $els=Rewalk $report
  $submit=FindControl $els 'move-submit' '^(Зробити хід|Make move)$' 'ControlType.Button'
  if($null -eq $submit){throw 'move-submit missing during board-origin bridge'}
  $preInvoke=[System.Windows.Automation.AutomationElement]::FocusedElement
  if(-not (SameSemanticFocus $target $preInvoke)){throw "Board origin changed before move-submit Invoke; final $(FocusDescription $preInvoke)"}
  Invoke $submit 'move-submit'
  AssertSemanticFocusEventually $target 'Board focus continuity after pure submit bridge'

  $summary.board_focus_continuity=$true
  $els=Rewalk $report
  $fenE5=Fen $els
  if($fenE5 -ne 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2'){throw "Black e5 did not mutate to canonical FEN: $fenE5"}
  $summary.black_e5_fen=$fenE5
  NoRawError $els; $summary.raw_exception_noise=$false
  $summary|ConvertTo-Json -Depth 6|Set-Content -Encoding UTF8 packaged-uia-strict-summary.json
  Write-Output "STRICT PACKAGED CROSS-PROCESS UIA/E4/E9/CLIPBOARD/64-SQUARE/PURE-BOARD-BRIDGE PASS move_rid=$moveRid"
}catch{
  Write-Output "STRICT_HELPER_EXCEPTION_TYPE=$($_.Exception.GetType().FullName)"
  Write-Output "STRICT_HELPER_EXCEPTION_MESSAGE=$($_.Exception.Message)"
  Write-Output "STRICT_HELPER_STACK=$($_.ScriptStackTrace)"
  throw
}finally{
  $p=Get-Process -Id $AppPid -ErrorAction SilentlyContinue
  if($p){Stop-Process -Id $AppPid -Force -ErrorAction SilentlyContinue}
}
