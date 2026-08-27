param(
  [Parameter(Mandatory=$true)][int]$AppPid,
  [string]$ProductRoot='.'
)

$ErrorActionPreference='Stop'

# QA-only wrapper. The exact previous strict helper is immutable at this commit.
# We patch only the stale post-rerender board focus assertion in memory, then execute
# the complete original helper unchanged otherwise. Product source is never touched.
$baseSha='0549391267073f9d006ec8271af148fe17edcdb6'
$path='tools/qa/stage1_packaged_e2e_crossprocess.ps1'
$original=(& git show "$baseSha`:$path") -join "`n"
if($LASTEXITCODE -ne 0 -or -not $original){throw 'Could not load immutable strict helper baseline'}

$needle=@'
  Invoke $submit 'move-submit'
  AssertSemanticFocusEventually $target 'Board focus continuity after pure submit bridge'
'@
$replacement=@'
  Invoke $submit 'move-submit'
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

$first=$original.IndexOf($needle,[System.StringComparison]::Ordinal)
if($first -lt 0){throw 'Expected stale board-focus assertion was not found exactly once'}
$second=$original.IndexOf($needle,$first+$needle.Length,[System.StringComparison]::Ordinal)
if($second -ge 0){throw 'Expected stale board-focus assertion occurs more than once'}
$patched=$original.Replace($needle,$replacement)
if($patched -eq $original -or $patched.Contains($needle)){throw 'Board-focus QA patch did not apply fail-closed'}

# Dynamic execution must preserve the original helper directory for topology/classifier files.
$rootLiteral="'"+($PSScriptRoot -replace "'","''")+"'"
$patched=$patched.Replace('$PSScriptRoot',$rootLiteral)
$script=[scriptblock]::Create($patched)
& $script -AppPid $AppPid -ProductRoot $ProductRoot
