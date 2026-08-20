$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$outDir = Join-Path $PWD 'competitor-results/windows-chessx'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$meta = [ordered]@{
  startedAt = (Get-Date).ToUniversalTime().ToString('o')
  product = 'ChessX 1.6.10'
  source = 'https://downloads.sourceforge.net/project/chessx/chessx/1.6.10/setup-chessx7-64.exe'
  download = $null
  authenticode = $null
  install = $null
  executable = $null
  launch = $null
  uia = @()
  keyboard = @()
  errors = @()
}
function Add-Err([string]$kind, $err) { $script:meta.errors += [ordered]@{kind=$kind;text=[string]$err} }

$installer = Join-Path $outDir 'setup-chessx7-64.exe'
try {
  Invoke-WebRequest -Uri $meta.source -OutFile $installer -UseBasicParsing -MaximumRedirection 10
  $hash=Get-FileHash $installer -Algorithm SHA256
  $sig=Get-AuthenticodeSignature $installer
  $meta.download=[ordered]@{bytes=(Get-Item $installer).Length;sha256=$hash.Hash}
  $meta.authenticode=[ordered]@{status=[string]$sig.Status;statusMessage=$sig.StatusMessage;signer=if($sig.SignerCertificate){$sig.SignerCertificate.Subject}else{$null};thumbprint=if($sig.SignerCertificate){$sig.SignerCertificate.Thumbprint}else{$null}}
} catch { Add-Err 'download_or_signature' $_ }

if(Test-Path $installer){
  try{
    $p=Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-') -Wait -PassThru
    $meta.install=[ordered]@{exitCode=$p.ExitCode}
  }catch{Add-Err 'install' $_}
}

try{
  $roots=@($env:ProgramFiles,${env:ProgramFiles(x86)},$env:LOCALAPPDATA) | Where-Object {$_ -and (Test-Path $_)}
  $candidates=foreach($root in $roots){
    Get-ChildItem $root -Filter *.exe -Recurse -ErrorAction SilentlyContinue | Where-Object {$_.FullName -match '(?i)chessx'} | ForEach-Object {
      $v=[Diagnostics.FileVersionInfo]::GetVersionInfo($_.FullName)
      [pscustomobject]@{Path=$_.FullName;ProductName=$v.ProductName;FileDescription=$v.FileDescription;FileVersion=$v.FileVersion;Length=$_.Length}
    }
  }
  $candidates=$candidates | Sort-Object @{Expression={if($_.Path -match '(?i)\\chessx\.exe$'){0}else{1}}},Path | Select-Object -First 30
  $candidates | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 (Join-Path $outDir 'exe-candidates.json')
  $exe=$candidates | Where-Object {$_.Path -match '(?i)\\chessx\.exe$'} | Select-Object -First 1
  if(-not $exe){$exe=$candidates|Select-Object -First 1}
  if($exe){$meta.executable=$exe}
}catch{Add-Err 'find_executable' $_}

$sample=Join-Path $outDir 'sample.pgn'
@'
[Event "Accessible Chess competitor lab"]
[Site "GitHub Actions"]
[Date "2026.08.20"]
[Round "1"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 (3... Nf6 {Berlin defence variation}) 4. Ba4 Nf6 {Main-line comment} 5. O-O Be7 *
'@ | Set-Content -Encoding utf8 $sample

if($meta.executable -and (Test-Path $meta.executable.Path)){
  try{
    $proc=Start-Process -FilePath $meta.executable.Path -ArgumentList @($sample) -PassThru
    Start-Sleep -Seconds 12
    $proc.Refresh()
    $meta.launch=[ordered]@{pid=$proc.Id;exited=$proc.HasExited;mainWindowTitle=$proc.MainWindowTitle;mainWindowHandle=[int64]$proc.MainWindowHandle}

    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    $root=[System.Windows.Automation.AutomationElement]::RootElement
    $cond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty,$proc.Id)
    $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$cond)
    for($i=0;$i -lt [Math]::Min($all.Count,2000);$i++){
      try{
        $c=$all.Item($i).Current
        $patterns=@()
        foreach($pid in @([System.Windows.Automation.SelectionItemPattern]::Pattern,[System.Windows.Automation.ValuePattern]::Pattern,[System.Windows.Automation.TextPattern]::Pattern,[System.Windows.Automation.InvokePattern]::Pattern,[System.Windows.Automation.ExpandCollapsePattern]::Pattern)){
          try{if($all.Item($i).GetSupportedPatterns() -contains $pid){$patterns += $pid.ProgrammaticName}}catch{}
        }
        $meta.uia += [ordered]@{name=$c.Name;automationId=$c.AutomationId;className=$c.ClassName;frameworkId=$c.FrameworkId;controlType=$c.ControlType.ProgrammaticName;enabled=$c.IsEnabled;keyboardFocusable=$c.IsKeyboardFocusable;hasFocus=$c.HasKeyboardFocus;offscreen=$c.IsOffscreen;nativeHandle=$c.NativeWindowHandle;supportedPatterns=$patterns}
      }catch{}
    }

    try{
      Add-Type -AssemblyName System.Windows.Forms
      Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class NativeFocusChessX { [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd); }
'@
      $ok=[NativeFocusChessX]::SetForegroundWindow([IntPtr]$proc.MainWindowHandle)
      $meta.keyboard += [ordered]@{action='SetForegroundWindow';success=$ok}
      foreach($key in @('{TAB}','{TAB}','%f','{ESC}','{RIGHT}','{LEFT}','{UP}','{DOWN}','{HOME}','{END}','^f')){
        try{
          [System.Windows.Forms.SendKeys]::SendWait($key);Start-Sleep -Milliseconds 300
          $f=[System.Windows.Automation.AutomationElement]::FocusedElement
          $meta.keyboard += [ordered]@{action=$key;focusedName=$f.Current.Name;focusedControlType=$f.Current.ControlType.ProgrammaticName;focusedAutomationId=$f.Current.AutomationId;focusedClassName=$f.Current.ClassName}
        }catch{$meta.keyboard += [ordered]@{action=$key;error=[string]$_}}
      }
    }catch{Add-Err 'keyboard_probe' $_}

    try{
      Add-Type -AssemblyName System.Drawing
      Add-Type -AssemblyName System.Windows.Forms
      $bounds=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds
      $bmp=New-Object System.Drawing.Bitmap $bounds.Width,$bounds.Height
      $g=[System.Drawing.Graphics]::FromImage($bmp)
      $g.CopyFromScreen($bounds.Location,[Drawing.Point]::Empty,$bounds.Size)
      $png=Join-Path $outDir 'desktop.png'
      $bmp.Save($png,[Drawing.Imaging.ImageFormat]::Png)
      $g.Dispose();$bmp.Dispose()
      $meta.screenshot=[ordered]@{success=$true;bytes=(Get-Item $png).Length}
    }catch{Add-Err 'screenshot' $_}

    if(-not $proc.HasExited){Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue}
  }catch{Add-Err 'launch_or_uia' $_}
}

$meta.finishedAt=(Get-Date).ToUniversalTime().ToString('o')
$meta | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 (Join-Path $outDir 'chessx-probe.json')
