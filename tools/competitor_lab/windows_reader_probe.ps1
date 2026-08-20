$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$outDir = Join-Path $PWD 'competitor-results/windows'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$meta = [ordered]@{
  startedAt = (Get-Date).ToUniversalTime().ToString('o')
  runner = $env:RUNNER_NAME
  os = [Environment]::OSVersion.VersionString
  product = 'ChessBase Reader 2017'
  source = 'https://download.chessbase.com/download/chessbasereader/Reader2017Setup_x86.msi'
  download = $null
  authenticode = $null
  install = $null
  executable = $null
  launch = $null
  uia = @()
  keyboard = @()
  screenshot = $null
  errors = @()
}

function Add-Err([string]$kind, $err) {
  $script:meta.errors += [ordered]@{ kind = $kind; text = [string]$err }
}

$msi = Join-Path $outDir 'Reader2017Setup_x86.msi'
try {
  Invoke-WebRequest -Uri $meta.source -OutFile $msi -UseBasicParsing
  $hash = Get-FileHash -Path $msi -Algorithm SHA256
  $sig = Get-AuthenticodeSignature -FilePath $msi
  $meta.download = [ordered]@{ exists = (Test-Path $msi); bytes = (Get-Item $msi).Length; sha256 = $hash.Hash }
  $meta.authenticode = [ordered]@{
    status = [string]$sig.Status
    statusMessage = $sig.StatusMessage
    signer = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { $null }
    issuer = if ($sig.SignerCertificate) { $sig.SignerCertificate.Issuer } else { $null }
    thumbprint = if ($sig.SignerCertificate) { $sig.SignerCertificate.Thumbprint } else { $null }
  }
} catch { Add-Err 'download_or_signature' $_ }

if (Test-Path $msi) {
  try {
    $p = Start-Process msiexec.exe -ArgumentList @('/i', $msi, '/qn', '/norestart') -Wait -PassThru
    $meta.install = [ordered]@{ exitCode = $p.ExitCode }
  } catch { Add-Err 'install' $_ }
}

try {
  $candidates = Get-ChildItem ${env:ProgramFiles(x86)}, $env:ProgramFiles -Filter *.exe -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match 'ChessBase|CBReader|Reader' } |
    ForEach-Object {
      $v = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($_.FullName)
      [pscustomobject]@{ Path=$_.FullName; ProductName=$v.ProductName; FileDescription=$v.FileDescription; FileVersion=$v.FileVersion }
    } |
    Where-Object { ($_.ProductName -match 'ChessBase.*Reader') -or ($_.FileDescription -match 'ChessBase.*Reader') -or ($_.Path -match 'CBReader') } |
    Select-Object -First 20
  $candidates | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 (Join-Path $outDir 'exe-candidates.json')
  $exe = $candidates | Select-Object -First 1
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
    Start-Sleep -Seconds 12
    $proc.Refresh()
    $meta.launch = [ordered]@{ pid = $proc.Id; exited = $proc.HasExited; mainWindowTitle = $proc.MainWindowTitle; mainWindowHandle = [int64]$proc.MainWindowHandle }

    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $proc.Id)
    $all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
    for ($i=0; $i -lt [Math]::Min($all.Count, 1000); $i++) {
      $e = $all.Item($i)
      try {
        $c = $e.Current
        $meta.uia += [ordered]@{
          name = $c.Name
          automationId = $c.AutomationId
          className = $c.ClassName
          frameworkId = $c.FrameworkId
          controlType = $c.ControlType.ProgrammaticName
          enabled = $c.IsEnabled
          keyboardFocusable = $c.IsKeyboardFocusable
          hasFocus = $c.HasKeyboardFocus
          offscreen = $c.IsOffscreen
          nativeHandle = $c.NativeWindowHandle
        }
      } catch { }
    }

    try {
      Add-Type -AssemblyName System.Windows.Forms
      Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class NativeFocus {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
}
'@
      $focused = [NativeFocus]::SetForegroundWindow([IntPtr]$proc.MainWindowHandle)
      $meta.keyboard += [ordered]@{ action='SetForegroundWindow'; success=$focused }
      foreach ($key in @('{TAB}','{TAB}','%f','{ESC}','{RIGHT}','{LEFT}')) {
        try {
          [System.Windows.Forms.SendKeys]::SendWait($key)
          Start-Sleep -Milliseconds 250
          $focusedEl = [System.Windows.Automation.AutomationElement]::FocusedElement
          $meta.keyboard += [ordered]@{
            action = $key
            focusedName = $focusedEl.Current.Name
            focusedControlType = $focusedEl.Current.ControlType.ProgrammaticName
            focusedAutomationId = $focusedEl.Current.AutomationId
          }
        } catch { $meta.keyboard += [ordered]@{ action=$key; error=[string]$_ } }
      }
    } catch { Add-Err 'keyboard_probe' $_ }

    try {
      Add-Type -AssemblyName System.Drawing
      Add-Type -AssemblyName System.Windows.Forms
      $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
      $bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
      $g = [System.Drawing.Graphics]::FromImage($bmp)
      $g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
      $png = Join-Path $outDir 'desktop.png'
      $bmp.Save($png, [System.Drawing.Imaging.ImageFormat]::Png)
      $g.Dispose(); $bmp.Dispose()
      $meta.screenshot = [ordered]@{ success=$true; path='desktop.png'; bytes=(Get-Item $png).Length }
    } catch { $meta.screenshot = [ordered]@{ success=$false; error=[string]$_ } }

    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
  } catch { Add-Err 'launch_or_uia' $_ }
}

$meta.finishedAt = (Get-Date).ToUniversalTime().ToString('o')
$meta | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $outDir 'reader2017-probe.json')
