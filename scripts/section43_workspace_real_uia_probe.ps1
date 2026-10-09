param(
  [Parameter(Mandatory=$true)][int]$TargetProcessId,
  [Parameter(Mandatory=$true)][string]$OutputPath,
  [int]$TimeoutSeconds = 55
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

# Query the WinForms owner window first. WebView2 accessibility descendants can
# belong to renderer processes; filtering every descendant by the Python PID
# would silently discard the actual Chromium UIA providers.
$desktop = [System.Windows.Automation.AutomationElement]::RootElement
$pidCondition = [System.Windows.Automation.PropertyCondition]::new(
  [System.Windows.Automation.AutomationElement]::ProcessIdProperty, $TargetProcessId)
$windowCondition = [System.Windows.Automation.PropertyCondition]::new(
  [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
  [System.Windows.Automation.ControlType]::Window)
$ownerCondition = [System.Windows.Automation.AndCondition]::new(
  [System.Windows.Automation.Condition[]]@($pidCondition,$windowCondition))
$buttonCondition = [System.Windows.Automation.PropertyCondition]::new(
  [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
  [System.Windows.Automation.ControlType]::Button)
$editCondition = [System.Windows.Automation.PropertyCondition]::new(
  [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
  [System.Windows.Automation.ControlType]::Edit)

function Get-Controls($owner, $condition) {
  $found = $owner.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)
  $list = @()
  for($i=0;$i -lt $found.Count;$i++){$list += ,$found.Item($i)}
  return $list
}
function Get-Name($control) {
  try { return [string]$control.Current.Name } catch { return '' }
}
function Get-Toggles($owner) {
  return @(Get-Controls $owner $buttonCondition | Where-Object {
    (Get-Name $_) -match '( — | - )(Згорнути|Collapse)$'
  })
}
function Get-Expands($owner) {
  return @(Get-Controls $owner $buttonCondition | Where-Object {
    (Get-Name $_) -match '( — | - )(Розгорнути|Expand)$'
  })
}
$owner = $null
$toggles = @()
$deadline=[DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
do {
  $windows=$desktop.FindAll([System.Windows.Automation.TreeScope]::Children,$ownerCondition)
  for($i=0;$i -lt $windows.Count;$i++){
    $candidate=$windows.Item($i)
    if((Get-Name $candidate) -match 'Accessible Chess'){
      $owner=$candidate
      break
    }
  }
  if($null -ne $owner){
    $toggles = @(Get-Toggles $owner)
    if($toggles.Count -eq 12){break}
  }
  Start-Sleep -Milliseconds 350
}while([DateTime]::UtcNow -lt $deadline)

$checks=[ordered]@{}
$checks.owner_window_found = $null -ne $owner
$checks.twelve_real_panel_toggles = $toggles.Count -eq 12
$checks.twelve_keyboard_focusable_toggles = $false
$checks.native_move_edit_discovered = $false
$checks.real_toggle_expand_restore_uia = $false
$checks.screenshot_captured = $false
$errors=@()
$beforeNames=@()
$editNames=@()
$screenshot=''
$windowBounds=@{}
if($null -ne $owner){
  $beforeNames = @($toggles | ForEach-Object {Get-Name $_})
  $checks.twelve_keyboard_focusable_toggles = $toggles.Count -eq 12 -and
    @($toggles | Where-Object { -not $_.Current.IsKeyboardFocusable }).Count -eq 0
  $edits=@(Get-Controls $owner $editCondition)
  $editNames=@($edits | ForEach-Object {Get-Name $_})
  $checks.native_move_edit_discovered = @($editNames | Where-Object {
    $_ -match 'Хід|Move'
  }).Count -ge 1
  $rect=$owner.Current.BoundingRectangle
  $windowBounds=[ordered]@{x=[int]$rect.X;y=[int]$rect.Y;width=[int]$rect.Width;height=[int]$rect.Height}
  if($rect.Width -gt 100 -and $rect.Height -gt 100 -and
     $rect.Width -le 5000 -and $rect.Height -le 5000){
    try {
      $bmp=[System.Drawing.Bitmap]::new([int]$rect.Width,[int]$rect.Height)
      try{
        $g=[System.Drawing.Graphics]::FromImage($bmp)
        try{
          $g.CopyFromScreen([int]$rect.X,[int]$rect.Y,0,0,$bmp.Size)
          $screenshot=[System.IO.Path]::ChangeExtension($OutputPath,'.png')
          $bmp.Save($screenshot,[System.Drawing.Imaging.ImageFormat]::Png)
          $checks.screenshot_captured = (Test-Path -LiteralPath $screenshot) -and
            (Get-Item -LiteralPath $screenshot).Length -gt 1000
        }finally{$g.Dispose()}
      }finally{$bmp.Dispose()}
    }catch{$errors += 'screenshot: '+$_.Exception.GetType().Name}
  }
  if($toggles.Count -eq 12){
    try {
      $first=$toggles[0]
      $oldName=Get-Name $first
      $prefix=$oldName -replace '( — | - )(Згорнути|Collapse)$',''
      $invoker=$first.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
      $invoker.Invoke()
      $expanded=$false
      $expandedControl=$null
      for($retry=0;$retry -lt 30;$retry++){
        Start-Sleep -Milliseconds 150
        foreach($c in @(Get-Expands $owner)){
          if((Get-Name $c) -match [regex]::Escape($prefix)){
            $expanded=$true;$expandedControl=$c;break
          }
        }
        if($expanded){break}
      }
      if($expanded -and $null -ne $expandedControl){
        $expandedControl.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
        for($retry=0;$retry -lt 30;$retry++){
          Start-Sleep -Milliseconds 150
          if(@(Get-Toggles $owner | Where-Object {(Get-Name $_) -eq $oldName}).Count -gt 0){
            $checks.real_toggle_expand_restore_uia = $true
            break
          }
        }
      }
    }catch{$errors += 'toggle roundtrip: '+$_.Exception.GetType().Name}
  }
}
$passed = @($checks.Values | Where-Object {$_ -ne $true}).Count -eq 0 -and
  $errors.Count -eq 0
$report=[ordered]@{
  section=43
  status= $(if($passed){'PASS'}else{'FAIL'})
  scope='REAL SOURCE WebView2/WinForms external Windows UI Automation; not packaged/owner NVDA'
  process_id=$TargetProcessId
  checks=$checks
  window_bounds=$windowBounds
  panel_names=$beforeNames
  move_edit_names=$editNames
  screenshot=$screenshot
  errors=$errors
  packaged_executable_tested=$false
  human_tested=$false
  nvda_verified=$false
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding utf8
Write-Host ('SECTION43_REAL_UIA=' + $report.status)
if(-not $passed){throw 'Section43 genuine WinForms/WebView2 UIA or screenshot acceptance failed; evidence written'}
