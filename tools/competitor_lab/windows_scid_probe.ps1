$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$outDir = Join-Path $PWD 'competitor-results/windows-scid'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$meta = [ordered]@{
  startedAt = (Get-Date).ToUniversalTime().ToString('o')
  product = 'Scid 5.2'
  source = 'https://downloads.sourceforge.net/project/scid/Scid/Scid%205.2/scid-v5.2.202603_windows_x64.zip'
  download = $null
  executable = $null
  launch = $null
  uia = @()
  keyboard = @()
  errors = @()
}
function Add-Err([string]$kind, $err) { $script:meta.errors += [ordered]@{kind=$kind;text=[string]$err} }

$zip = Join-Path $outDir 'scid.zip'
$extract = Join-Path $outDir 'scid'
try {
  Invoke-WebRequest -Uri $meta.source -OutFile $zip -UseBasicParsing
  $hash = Get-FileHash $zip -Algorithm SHA256
  $meta.download = [ordered]@{ bytes=(Get-Item $zip).Length; sha256=$hash.Hash }
  Expand-Archive -Path $zip -DestinationPath $extract -Force
} catch { Add-Err 'download_or_extract' $_ }

try {
  $candidates = Get-ChildItem $extract -Recurse -Filter *.exe -ErrorAction SilentlyContinue |
    ForEach-Object {
      $v=[Diagnostics.FileVersionInfo]::GetVersionInfo($_.FullName)
      [pscustomobject]@{Path=$_.FullName;ProductName=$v.ProductName;FileDescription=$v.FileDescription;FileVersion=$v.FileVersion;Length=$_.Length}
    } | Sort-Object @{Expression={ if ($_.ProductName -match 'Scid' -or $_.FileDescription -match 'Scid' -or $_.Path -match '\\scid\.exe$') {0}else{1}}}, Path
  $candidates | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 (Join-Path $outDir 'exe-candidates.json')
  $exe = $candidates | Where-Object { $_.Path -match '(?i)\\scid.*\.exe$' -or $_.ProductName -match '(?i)Scid' } | Select-Object -First 1
  if (-not $exe) { $exe = $candidates | Select-Object -First 1 }
  if ($exe) { $meta.executable = $exe }
} catch { Add-Err 'find_executable' $_ }

$sample = Join-Path $outDir 'sample.pgn'
@'
[Event "Accessible Chess competitor lab"]
[Site "GitHub Actions"]
[Date "2026.08.20"]
[Round "1"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 (3... Nf6 {Berlin}) 4. Ba4 Nf6 {Main-line comment} *
'@ | Set-Content -Encoding ascii $sample

if ($meta.executable -and (Test-Path $meta.executable.Path)) {
  try {
    $proc = Start-Process -FilePath $meta.executable.Path -ArgumentList @($sample) -PassThru
    Start-Sleep -Seconds 10
    $proc.Refresh()
    $meta.launch = [ordered]@{ pid=$proc.Id; exited=$proc.HasExited; mainWindowTitle=$proc.MainWindowTitle; mainWindowHandle=[int64]$proc.MainWindowHandle }
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    $root=[System.Windows.Automation.AutomationElement]::RootElement
    $cond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty,$proc.Id)
    $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$cond)
    for($i=0;$i -lt [Math]::Min($all.Count,1500);$i++){
      try{
        $c=$all.Item($i).Current
        $meta.uia += [ordered]@{name=$c.Name;automationId=$c.AutomationId;className=$c.ClassName;frameworkId=$c.FrameworkId;controlType=$c.ControlType.ProgrammaticName;enabled=$c.IsEnabled;keyboardFocusable=$c.IsKeyboardFocusable;hasFocus=$c.HasKeyboardFocus;offscreen=$c.IsOffscreen;nativeHandle=$c.NativeWindowHandle}
      }catch{}
    }
    try {
      Add-Type -AssemblyName System.Windows.Forms
      Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class NativeFocusScid { [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd); }
'@
      $focused=[NativeFocusScid]::SetForegroundWindow([IntPtr]$proc.MainWindowHandle)
      $meta.keyboard += [ordered]@{action='SetForegroundWindow';success=$focused}
      foreach($key in @('{TAB}','{TAB}','%f','{ESC}','{RIGHT}','{LEFT}','{HOME}','{END}')){
        try{
          [System.Windows.Forms.SendKeys]::SendWait($key); Start-Sleep -Milliseconds 250
          $f=[System.Windows.Automation.AutomationElement]::FocusedElement
          $meta.keyboard += [ordered]@{action=$key;focusedName=$f.Current.Name;focusedControlType=$f.Current.ControlType.ProgrammaticName;focusedAutomationId=$f.Current.AutomationId}
        }catch{$meta.keyboard += [ordered]@{action=$key;error=[string]$_}}
      }
    } catch { Add-Err 'keyboard_probe' $_ }
    if(-not $proc.HasExited){Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue}
  } catch { Add-Err 'launch_or_uia' $_ }
}

$meta.finishedAt=(Get-Date).ToUniversalTime().ToString('o')
$meta | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $outDir 'scid-probe.json')
