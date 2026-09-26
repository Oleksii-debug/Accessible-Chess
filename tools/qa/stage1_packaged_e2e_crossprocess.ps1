param(
  [Parameter(Mandatory=$true)][int]$AppPid,
  [string]$ProductRoot='.'
)

$ErrorActionPreference='Stop'

# QA-only wrapper. Load the immutable strict helper baseline, replace exactly one
# stale post-rerender board-focus assertion, then execute the complete helper.
# Product source and all other strict assertions remain unchanged.
$baseSha='0549391267073f9d006ec8271af148fe17edcdb6'
$path='tools/qa/stage1_packaged_e2e_crossprocess.ps1'
$original=((& git show "$baseSha`:$path") -join "`n") -replace "`r`n","`n"
if($LASTEXITCODE -ne 0 -or -not $original){throw 'Could not load immutable strict helper baseline'}

$pattern='(?m)^[ \t]*AssertSemanticFocusEventually[ \t]+\$target[ \t]+''Board focus continuity after pure submit bridge''[ \t]*$'
$matches=[regex]::Matches($original,$pattern)
if($matches.Count -ne 1){throw "Expected exactly one stale board-focus assertion, found $($matches.Count)"}

$replacement=@'
  $expectedBoardSquare='a3'
  $expectedBoardId='sq-a3'
  $boardFocusWatch=[System.Diagnostics.Stopwatch]::StartNew()
  $focusedBoard=$null
  $freshBoardTarget=$null
  while($boardFocusWatch.ElapsedMilliseconds -lt 4000){
    try{
      $focusedBoard=[System.Windows.Automation.AutomationElement]::FocusedElement
      $focusedId=[string]$focusedBoard.Current.AutomationId
      $focusedSquare=SquareToken $focusedBoard
      if($focusedId -eq $expectedBoardId -and $focusedSquare -eq $expectedBoardSquare){
        $freshEls=Rewalk $report
        $freshSquares=Squares $freshEls
        if($freshSquares.ContainsKey($expectedBoardSquare)){
          $candidate=$freshSquares[$expectedBoardSquare]
          if([string]$candidate.Current.AutomationId -eq $expectedBoardId -and (SquareToken $candidate) -eq $expectedBoardSquare){
            $freshBoardTarget=$candidate
            break
          }
        }
      }
    }catch{}
    Start-Sleep -Milliseconds 100
  }
  if($null -eq $freshBoardTarget){
    throw "Board focus continuity after pure submit bridge did not converge to semantic square='$expectedBoardSquare' automation_id='$expectedBoardId'; final $(FocusDescription $focusedBoard)"
  }
  $target=$freshBoardTarget
  Write-Output 'BOARD FOCUS CONTINUITY PASS a3/sq-a3 after rerender'
'@

$patched=[regex]::Replace($original,$pattern,[System.Text.RegularExpressions.MatchEvaluator]{param($m) $replacement},1)
if($patched -eq $original -or [regex]::Matches($patched,$pattern).Count -ne 0){throw 'Board-focus QA patch did not apply fail-closed'}

# Dynamic execution must preserve the original helper directory for topology/classifier files.
$rootLiteral="'"+($PSScriptRoot -replace "'","''")+"'"
$patched=$patched.Replace('$PSScriptRoot',$rootLiteral)
$script=[scriptblock]::Create($patched)
& $script -AppPid $AppPid -ProductRoot $ProductRoot
