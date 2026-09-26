param(
  [Parameter(Mandatory=$true)][int]$AppPid,
  [Parameter(Mandatory=$true)][string]$ReportPath,
  [Parameter(Mandatory=$true)][string]$SummaryPath
)

$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

function Hwnd([string]$value) {
  $token=$value.Trim()
  if($token.StartsWith('0x',[StringComparison]::OrdinalIgnoreCase)) {
    return [IntPtr]([Convert]::ToInt64($token.Substring(2),16))
  }
  return [IntPtr]([int64]$token)
}

function RuntimeKey($element) {
  try { return (($element.GetRuntimeId() | ForEach-Object {[string]$_}) -join '.') } catch { return '' }
}

function ConnectedRoots($report) {
  $roots=@()
  foreach($row in @($report.root_attempts)) {
    if(-not [bool]$row.connected_to_app -or -not [bool]$row.from_handle_success -or -not [bool]$row.provider_subtree_seen) { continue }
    try {
      $root=[System.Windows.Automation.AutomationElement]::FromHandle((Hwnd ([string]$row.hwnd)))
      if($null -ne $root) { $roots += ,$root }
    } catch {}
  }
  if($roots.Count -eq 0) { throw 'SEMANTIC_COPY_NO_CONNECTED_PROVIDER_ROOT' }
  return $roots
}

function FindAccessibleChessDocument($roots,[int]$timeoutMs=5000) {
  $watch=[System.Diagnostics.Stopwatch]::StartNew()
  while($watch.ElapsedMilliseconds -lt $timeoutMs) {
    foreach($root in @($roots)) {
      try {
        $condition=New-Object System.Windows.Automation.AndCondition(
          (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Document)),
          (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'Accessible Chess'))
        )
        $hits=$root.FindAll([System.Windows.Automation.TreeScope]::Subtree,$condition)
        foreach($doc in @($hits)) {
          if($null -eq $doc) { continue }
          if([string]$doc.Current.ControlType.ProgrammaticName -eq 'ControlType.Edit') { continue }
          try {
            $pattern=$doc.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
            if($null -ne $pattern) { return @($doc,$pattern) }
          } catch {}
        }
      } catch {}
    }
    Start-Sleep -Milliseconds 100
  }
  throw 'SEMANTIC_COPY_DOCUMENT_TEXTPATTERN_NOT_FOUND'
}

if(-not ('AccessibleChessQaSemanticNativeKeysV1' -as [type])) {
  Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class AccessibleChessQaSemanticNativeKeysV1 {
  [DllImport("user32.dll")]
  private static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
  private const uint KEYEVENTF_KEYUP = 0x0002;
  public static void Ctrl(byte vk) {
    keybd_event(0x11, 0, 0, UIntPtr.Zero);
    keybd_event(vk, 0, 0, UIntPtr.Zero);
    keybd_event(vk, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
    keybd_event(0x11, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
  }
}
"@
}

$report=Get-Content $ReportPath -Raw | ConvertFrom-Json
$roots=ConnectedRoots $report
$result=FindAccessibleChessDocument $roots
$document=$result[0]
$textPattern=$result[1]
if([string]$document.Current.ControlType.ProgrammaticName -eq 'ControlType.Edit') {
  throw 'SEMANTIC_COPY_DOCUMENT_IS_EDIT'
}

$documentRange=$textPattern.DocumentRange
if($null -eq $documentRange) { throw 'SEMANTIC_COPY_DOCUMENT_RANGE_MISSING' }
$needle='Accessible Chess'
$target=$documentRange.FindText($needle,$false,$false)
if($null -eq $target) {
  $sample=[string]$documentRange.GetText(512)
  throw "SEMANTIC_COPY_H1_NOT_FOUND sample='$sample'"
}
$selected=[string]$target.GetText(-1)
if($selected.Trim() -ne $needle) { throw "SEMANTIC_COPY_SELECTION_MISMATCH selected='$selected'" }

Set-Clipboard -Value '__accessible_chess_semantic_copy_sentinel__'
$target.Select()
Start-Sleep -Milliseconds 200
$selection=@($textPattern.GetSelection())
if($selection.Count -lt 1) { throw 'SEMANTIC_COPY_SELECTION_NOT_EXPOSED_BY_TEXTPATTERN' }
$selectionText=(@($selection | ForEach-Object {[string]$_.GetText(-1)}) -join '').Trim()
if($selectionText -ne $needle) { throw "SEMANTIC_COPY_TEXTPATTERN_SELECTION_MISMATCH selected='$selectionText'" }

$ws=New-Object -ComObject WScript.Shell
$null=$ws.AppActivate($AppPid)
Start-Sleep -Milliseconds 150
[AccessibleChessQaSemanticNativeKeysV1]::Ctrl([byte]0x43)
$watch=[System.Diagnostics.Stopwatch]::StartNew()
$clipboard=''
while($watch.ElapsedMilliseconds -lt 3000) {
  try { $clipboard=([string](Get-Clipboard -Raw)).Trim() } catch { $clipboard='' }
  if($clipboard -eq $needle) { break }
  Start-Sleep -Milliseconds 100
}
if($clipboard -ne $needle) {
  throw "SEMANTIC_COPY_NATIVE_CTRL_C_MISMATCH clipboard='$clipboard' expected='$needle'"
}

$summary=Get-Content $SummaryPath -Raw | ConvertFrom-Json
$summary | Add-Member -NotePropertyName semantic_document_copy -NotePropertyValue $true -Force
$summary | Add-Member -NotePropertyName semantic_document_copy_outside_edit -NotePropertyValue $true -Force
$summary | Add-Member -NotePropertyName semantic_document_clipboard -NotePropertyValue $clipboard -Force
$summary | Add-Member -NotePropertyName semantic_document_runtime_id -NotePropertyValue (RuntimeKey $document) -Force
$summary | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $SummaryPath

Write-Output "PACKAGED_SEMANTIC_DOCUMENT_COPY=PASS text='$clipboard' outside_edit=true"
