param([Parameter(Mandatory=$true)][int]$AppPid)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class UiaTopoV5 {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc c, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr p, EnumProc c, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint flags);
  [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr h, uint cmd);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
}
'@

function Hex([IntPtr]$h) { return ('0x{0:X}' -f $h.ToInt64()) }
function SafeProp($e, [string]$name) { try { return $e.Current.$name } catch { return $null } }
function RuntimeId($e) { try { return (($e.GetRuntimeId() | ForEach-Object { [string]$_ }) -join '.') } catch { return '' } }
function HResultText($ex) { try { return ('0x{0:X8}' -f ([uint32]$ex.Exception.HResult)) } catch { return '' } }

$procRows = @(Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine)
$procMap = @{}
foreach($p in $procRows){ $procMap[[int]$p.ProcessId] = $p }
function ReachesApp([int]$processId){
  $seen = New-Object 'System.Collections.Generic.HashSet[int]'
  $cur=$processId
  for($i=0;$i -lt 64 -and $cur -gt 0;$i++){
    if(-not $seen.Add($cur)){ break }
    if($cur -eq $AppPid){ return $true }
    if(-not $procMap.ContainsKey($cur)){ break }
    $cur=[int]$procMap[$cur].ParentProcessId
  }
  return $false
}

$hwndMap=@{}
function AddHwnd([IntPtr]$h){
  $key=$h.ToInt64(); if($key -eq 0 -or $hwndMap.ContainsKey($key)){ return }
  [uint32]$windowPid=0; $tid=[UiaTopoV5]::GetWindowThreadProcessId($h,[ref]$windowPid)
  $t=New-Object System.Text.StringBuilder 1024; [UiaTopoV5]::GetWindowText($h,$t,1024)|Out-Null
  $c=New-Object System.Text.StringBuilder 256; [UiaTopoV5]::GetClassName($h,$c,256)|Out-Null
  $parent=[UiaTopoV5]::GetParent($h); $root=[UiaTopoV5]::GetAncestor($h,2); $owner=[UiaTopoV5]::GetWindow($h,4)
  $hwndMap[$key]=[pscustomobject]@{
    hwnd=Hex $h; hwnd_int=[int64]$key; pid=[int]$windowPid; tid=[int]$tid;
    class=$c.ToString(); title=$t.ToString(); visible=[bool][UiaTopoV5]::IsWindowVisible($h);
    parent=Hex $parent; root=Hex $root; owner=Hex $owner
  }
}
$topCb=[UiaTopoV5+EnumProc]{param($h,$l); AddHwnd $h; [UiaTopoV5]::EnumChildWindows($h,[UiaTopoV5+EnumProc]{param($ch,$x);AddHwnd $ch;return $true},[IntPtr]::Zero)|Out-Null; return $true}
[UiaTopoV5]::EnumWindows($topCb,[IntPtr]::Zero)|Out-Null
$allHwnds=@($hwndMap.Values | Sort-Object hwnd_int)
$main=@($allHwnds | Where-Object { $_.pid -eq $AppPid -and $_.title -eq 'Accessible Chess' } | Select-Object -First 1)
if($main.Count -eq 0){ throw 'Accessible Chess main HWND not found' }
$mainRow=$main[0]; $mainHwnd=[string]$mainRow.hwnd

$relatedProcesses=@()
foreach($p in $procRows){
  $processId=[int]$p.ProcessId
  if($processId -eq $AppPid -or $p.Name -ieq 'msedgewebview2.exe' -or (ReachesApp $processId)){
    $relatedProcesses += [pscustomobject]@{pid=$processId;ppid=[int]$p.ParentProcessId;name=[string]$p.Name;to_app=(ReachesApp $processId);command_line=[string]$p.CommandLine}
  }
}

# Keep each candidate HWND scalar. Never wrap the candidate collection as one nested value.
$candidates=@()
foreach($h in $allHwnds){
  $class=[string]$h.class
  $isMain=([string]$h.hwnd -eq $mainHwnd)
  $sameRoot=([string]$h.root -eq $mainHwnd)
  $webClass=($class -match 'Chrome_WidgetWin_[01]|Chrome_RenderWidgetHostHWND|WebView|Chrome')
  $procConnected=($h.pid -eq $AppPid -or (ReachesApp ([int]$h.pid)))
  if($isMain -or $sameRoot -or ($webClass -and $procConnected)){
    $candidates += $h
  }
}
$candidates=@($candidates | Sort-Object hwnd_int -Unique)

$rootAttempts=New-Object System.Collections.Generic.List[object]
$nodes=New-Object System.Collections.Generic.List[object]
$transitions=New-Object System.Collections.Generic.List[object]

function DescribeNode($e,[string]$view,[string]$sourceHwnd,[string]$sourceClass,[int]$depth,[string]$path){
  $vp=$false;$value=$null
  try{$pat=$e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern);if($pat){$vp=$true;$value=$pat.Current.Value}}catch{}
  $b=SafeProp $e 'BoundingRectangle'; $ct=''; try{$ct=[string]$e.Current.ControlType.ProgrammaticName}catch{}
  $native=SafeProp $e 'NativeWindowHandle'; if($null -eq $native){$native=0}
  return [pscustomobject]@{
    view=$view;source_hwnd=$sourceHwnd;source_class=$sourceClass;depth=$depth;
    runtime_id=(RuntimeId $e);native_hwnd=[int]$native;pid=[int](SafeProp $e 'ProcessId');
    control_type=$ct;name=[string](SafeProp $e 'Name');automation_id=[string](SafeProp $e 'AutomationId');framework_id=[string](SafeProp $e 'FrameworkId');
    enabled=[bool](SafeProp $e 'IsEnabled');focusable=[bool](SafeProp $e 'IsKeyboardFocusable');has_focus=[bool](SafeProp $e 'HasKeyboardFocus');offscreen=[bool](SafeProp $e 'IsOffscreen');
    bounds=if($b){@($b.Left,$b.Top,$b.Width,$b.Height)}else{$null};value_pattern=$vp;value=$value;ancestor_path=$path
  }
}
function WalkTree($root,$walker,[string]$view,$src){
  $stack=New-Object System.Collections.Stack
  $stack.Push(@($root,0,''))
  $count=0
  while($stack.Count -gt 0 -and $count -lt 12000){
    $item=$stack.Pop();$e=$item[0];$depth=[int]$item[1];$path=[string]$item[2]
    $row=DescribeNode $e $view ([string]$src.hwnd) ([string]$src.class) $depth $path
    $nodes.Add($row);$count++
    try{
      $kids=New-Object System.Collections.Generic.List[object]
      $ch=$walker.GetFirstChild($e)
      while($null -ne $ch){$kids.Add($ch);$ch=$walker.GetNextSibling($ch)}
      for($i=$kids.Count-1;$i-ge0;$i--){
        $k=$kids[$i]
        $kPid=[int](SafeProp $k 'ProcessId');$kH=[int](SafeProp $k 'NativeWindowHandle')
        if(($kPid -ne $row.pid -and $kPid -ne 0) -or ($kH -ne 0 -and $kH -ne $row.native_hwnd)){
          $transitions.Add([pscustomobject]@{view=$view;source_hwnd=$src.hwnd;from_pid=$row.pid;to_pid=$kPid;from_native_hwnd=$row.native_hwnd;to_native_hwnd=$kH;parent_runtime_id=$row.runtime_id;child_runtime_id=(RuntimeId $k)})
        }
        $seg="$($row.control_type)|$($row.name)|pid=$($row.pid)|hwnd=$($row.native_hwnd)"
        $stack.Push(@($k,$depth+1,($(if($path){$path+' > '+$seg}else{$seg}))))
      }
    }catch{}
  }
  return $count
}

foreach($h in $candidates){
  $attempt=[ordered]@{hwnd=$h.hwnd;pid=$h.pid;class=$h.class;title=$h.title;visible=$h.visible;parent=$h.parent;root=$h.root;owner=$h.owner;from_handle_success=$false;exception_type='';exception_message='';hresult='';root_name='';root_control_type='';root_framework_id='';root_pid=0;root_native_hwnd=0;raw_nodes=0;control_nodes=0}
  try{
    $ae=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]([int64]$h.hwnd_int))
    if($null -eq $ae){throw 'AutomationElement.FromHandle returned null'}
    $attempt.from_handle_success=$true
    $attempt.root_name=[string](SafeProp $ae 'Name')
    try{$attempt.root_control_type=[string]$ae.Current.ControlType.ProgrammaticName}catch{}
    $attempt.root_framework_id=[string](SafeProp $ae 'FrameworkId')
    $attempt.root_pid=[int](SafeProp $ae 'ProcessId')
    $attempt.root_native_hwnd=[int](SafeProp $ae 'NativeWindowHandle')
    $attempt.raw_nodes=WalkTree $ae ([System.Windows.Automation.TreeWalker]::RawViewWalker) 'RawView' $h
    $attempt.control_nodes=WalkTree $ae ([System.Windows.Automation.TreeWalker]::ControlViewWalker) 'ControlView' $h
  }catch{
    $attempt.exception_type=$_.Exception.GetType().FullName
    $attempt.exception_message=$_.Exception.Message
    $attempt.hresult=HResultText $_
  }
  $rootAttempts.Add([pscustomobject]$attempt)
}

$edits=@($nodes | Where-Object {$_.control_type -eq 'ControlType.Edit'})
$moveCandidates=@($edits | Where-Object {
  $_.name -match '^(Хід|Move)$' -and $_.enabled -and $_.focusable -and -not $_.offscreen -and $_.value_pattern -and $_.bounds -and $_.bounds[2] -gt 0 -and $_.bounds[3] -gt 0
})
$providerRoots=@($rootAttempts | Where-Object {$_.from_handle_success -and ($_.class -match 'Chrome_RenderWidgetHostHWND|Chrome_WidgetWin_1|WebView')})
$providerNodes=@($nodes | Where-Object {$_.control_type -eq 'ControlType.Document' -or $_.framework_id -match 'Chrome|Chromium|WebView'})
$providerTraversalComplete=($providerRoots.Count -gt 0 -and $providerNodes.Count -gt 0 -and (@($nodes|Where-Object{$_.view -eq 'RawView'}).Count -gt 0) -and (@($nodes|Where-Object{$_.view -eq 'ControlView'}).Count -gt 0))
if($moveCandidates.Count -gt 0){$classification='A'}elseif($providerTraversalComplete){$classification='B'}else{$classification='C'}

$report=[ordered]@{
  classification=$classification;product_sha=$env:SOURCE_INTEGRATION_SHA;app_pid=$AppPid;main_hwnd=$mainHwnd;
  candidate_hwnds=$candidates;root_attempts=$rootAttempts;related_processes=$relatedProcesses;
  nodes=$nodes;provider_transitions=$transitions;connected_edits=$edits;move_candidates=$moveCandidates;
  provider_roots=$providerRoots;provider_nodes=$providerNodes;provider_traversal_complete=$providerTraversalComplete
}
$report|ConvertTo-Json -Depth 14|Set-Content -Encoding UTF8 uia-topology-report-v5.json
Write-Output "::notice title=UIA_TOPOLOGY_V5::classification=$classification hwnds=$($candidates.Count) roots_ok=$(@($rootAttempts|Where-Object{$_.from_handle_success}).Count) roots_fail=$(@($rootAttempts|Where-Object{-not $_.from_handle_success}).Count) nodes=$($nodes.Count) edits=$($edits.Count) moves=$($moveCandidates.Count) provider_complete=$providerTraversalComplete"
foreach($a in $rootAttempts){Write-Output "HWND $($a.hwnd) pid=$($a.pid) class='$($a.class)' fromHandle=$($a.from_handle_success) hr=$($a.hresult) raw=$($a.raw_nodes) control=$($a.control_nodes) err='$($a.exception_message)'"}
if($classification -eq 'A'){Write-Output 'A_QA_HARNESS_DEFECT: connected Move Edit proven.'}elseif($classification -eq 'B'){Write-Output 'B_PRODUCT_DEFECT_EVIDENCE: provider traversal complete but Move Edit absent.'}else{Write-Output 'C_INCONCLUSIVE: provider boundary still incomplete; no product attribution allowed.'}
