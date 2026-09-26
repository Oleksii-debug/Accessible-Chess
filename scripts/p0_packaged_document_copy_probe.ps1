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
  private const uint KEYEVENTF_KEYUP = 0x0002;
  public static void Ctrl(byte key) {
    keybd_event(0x11, 0, 0, UIntPtr.Zero);
    keybd_event(key, 0, 0, UIntPtr.Zero);
    keybd_event(key, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
    keybd_event(0x11, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
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

function WaitClipboard([string]$Expected,[int]$TimeoutMs=5000) {
  $watch=[System.Diagnostics.Stopwatch]::StartNew()
  $last=''
  while($watch.ElapsedMilliseconds -lt $TimeoutMs){
    try {$last=[string](Get-Clipboard -Raw -ErrorAction Stop)} catch {$last=''}
    if($last.Trim() -eq $Expected.Trim()){return $last}
    Start-Sleep -Milliseconds 100
  }
  throw "Clipboard did not receive exact selected text; expected='$Expected' actual='$last'"
}

$root=(Resolve-Path -LiteralPath $ProductRoot).Path
$exe=(Resolve-Path -LiteralPath (Join-Path $root 'AccessibleChess.exe')).Path
$process=Start-Process -FilePath $exe -WorkingDirectory $root -PassThru
try {
  $report=ReadTopology $process ($TimeoutSeconds*1000)
  $elements=ControlElements (ProviderRoots $report)
  $documents=@($elements | Where-Object {
    try {
      [string]$_.Current.ControlType.ProgrammaticName -eq 'ControlType.Document' -and
      [string]$_.Current.Name -eq 'Accessible Chess'
    } catch {$false}
  })
  if($documents.Count -lt 1){throw 'Accessible Chess Document missing from connected provider-root ControlView'}
  $document=$documents[0]
  try {$textPattern=$document.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)}
  catch {throw "Packaged WebView Document lacks TextPattern: $($_.Exception.Message)"}
  if($null -eq $textPattern){throw 'Packaged WebView Document lacks TextPattern'}
  if(([string]$textPattern.SupportedTextSelection) -match 'None$'){throw 'Packaged WebView Document reports no text selection support'}

  $all=$textPattern.DocumentRange.Clone()
  $target=$all.FindText('Інформація про гру',$false,$false)
  if($null -eq $target){$target=$all.FindText('Game information',$false,$false)}
  if($null -eq $target){throw 'Stable static document text not found through provider-root TextPattern'}
  $selected=([string]$target.GetText(-1)).Trim()
  if(-not $selected){throw 'Static TextPattern target is empty'}
  $enclosing=$target.GetEnclosingElement()
  if($null -ne $enclosing -and [string]$enclosing.Current.ControlType.ProgrammaticName -eq 'ControlType.Edit'){
    throw 'Static text proof accidentally targeted an edit control'
  }

  $shell=New-Object -ComObject WScript.Shell
  $null=$shell.AppActivate($process.Id)
  try {$document.SetFocus()} catch {}
  $target.Select()
  Start-Sleep -Milliseconds 100
  Set-Clipboard -Value 'P0_COPY_STATIC_SENTINEL'
  Start-Sleep -Milliseconds 150
  [AccessibleChessCopyKeys]::Ctrl([byte]0x43)
  $null=WaitClipboard $selected
  Write-Host "PACKAGED_STATIC_DOCUMENT_SELECTION_COPY=PASS text='$selected'"

  $elements=ControlElements (ProviderRoots $report)
  $move=FindControl $elements 'move-input' 'ControlType.Edit'
  if($null -eq $move){throw 'Move Input UIA element not found from connected provider roots'}
  try {$value=$move.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)}
  catch {throw "Move Input lacks ValuePattern: $($_.Exception.Message)"}
  if($null -eq $value){throw 'Move Input lacks ValuePattern'}
  $value.SetValue('e2e4')
  $null=$shell.AppActivate($process.Id)
  $move.SetFocus()
  Start-Sleep -Milliseconds 100
  Set-Clipboard -Value 'P0_COPY_EDIT_SENTINEL'
  Start-Sleep -Milliseconds 100
  [AccessibleChessCopyKeys]::Ctrl([byte]0x41)
  [AccessibleChessCopyKeys]::Ctrl([byte]0x43)
  $null=WaitClipboard 'e2e4'
  $value.SetValue('')
  Write-Host 'PACKAGED_MOVE_INPUT_NATIVE_CTRL_A_CTRL_C=PASS'

  $summary=[ordered]@{
    product_sha=$ProductSha
    discovery='connected provider-root ControlView from retained topology handles'
    static_document_text=$selected
    static_document_outside_edit=$true
    textpattern_selection_supported=$true
    ctrl_c_exact_clipboard=$true
    move_input_native_ctrl_a_ctrl_c=$true
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
if($bounded -match '(?i)[A-Z]:\\\\|/home/|/Users/|/tmp/'){throw 'Local path leaked into document-copy evidence'}
