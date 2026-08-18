param([Parameter(Mandatory=$true)][int]$AppPid)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class UiaTopoV6 {
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
  [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr h);
}
'@

$NodeCap=12000
function Hex([IntPtr]$h) { return ('0x{0:X}' -f $h.ToInt64()) }
function HResultText($err) { try { return ('0x{0:X8}' -f ([uint32]$err.Exception.HResult)) } catch { return '' } }
function RuntimeIdLoose($e) { try { return (($e.GetRuntimeId() | ForEach-Object { [string]$_ }) -join '.') } catch { return '' } }
function ElementKey($e) {
  $rid=RuntimeIdLoose $e
  if($rid){ return 'rid:'+ $rid }
  try { return 'obj:'+([string]$e.GetHashCode()) } catch { return '' }
}

$procRows=@(Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine)
$procMap=@{}
foreach($p in $procRows){$procMap[[int]$p.ProcessId]=$p}
function ProcessName([int]$processId){if($procMap.ContainsKey($processId)){return [string]$procMap[$processId].Name};return ''}
function ReachesApp([int]$processId){
  $seen=New-Object 'System.Collections.Generic.HashSet[int]'
  $cur=$processId
  for($i=0;$i -lt 64 -and $cur -gt 0;$i++){
    if(-not $seen.Add($cur)){break}
    if($cur -eq $AppPid){return $true}
    if(-not $procMap.ContainsKey($cur)){break}
    $cur=[int]$procMap[$cur].ParentProcessId
  }
  return $false
}

$hwndMap=@{}
function AddHwnd([IntPtr]$h){
  $key=$h.ToInt64();if($key -eq 0 -or $hwndMap.ContainsKey($key)){return}
  [uint32]$windowPid=0;$tid=[UiaTopoV6]::GetWindowThreadProcessId($h,[ref]$windowPid)
  $t=New-Object System.Text.StringBuilder 1024;[UiaTopoV6]::GetWindowText($h,$t,1024)|Out-Null
  $c=New-Object System.Text.StringBuilder 256;[UiaTopoV6]::GetClassName($h,$c,256)|Out-Null
  $parent=[UiaTopoV6]::GetParent($h);$root=[UiaTopoV6]::GetAncestor($h,2);$owner=[UiaTopoV6]::GetWindow($h,4)
  $processId=[int]$windowPid
  $hwndMap[$key]=[pscustomobject]@{
    hwnd=(Hex $h);hwnd_int=[int64]$key;pid=$processId;process_name=(ProcessName $processId);tid=[int]$tid;
    class=$c.ToString();title=$t.ToString();visible=[bool][UiaTopoV6]::IsWindowVisible($h);enabled=[bool][UiaTopoV6]::IsWindowEnabled($h);
    parent=(Hex $parent);root=(Hex $root);owner=(Hex $owner)
  }
}
$childCb=[UiaTopoV6+EnumProc]{param($ch,$x);AddHwnd $ch;return $true}
$topCb=[UiaTopoV6+EnumProc]{param($h,$l);AddHwnd $h;[UiaTopoV6]::EnumChildWindows($h,$childCb,[IntPtr]::Zero)|Out-Null;return $true}
[UiaTopoV6]::EnumWindows($topCb,[IntPtr]::Zero)|Out-Null
$allHwnds=@($hwndMap.Values|Sort-Object hwnd_int)
$main=@($allHwnds|Where-Object{$_.pid -eq $AppPid -and $_.title -eq 'Accessible Chess'}|Select-Object -First 1)
if($main.Count -eq 0){throw 'Accessible Chess main HWND not found'}
$mainRow=$main[0];$mainHwnd=[string]$mainRow.hwnd

$relatedProcesses=@()
foreach($p in $procRows){
  $processId=[int]$p.ProcessId
  if($processId -eq $AppPid -or $p.Name -ieq 'msedgewebview2.exe' -or (ReachesApp $processId)){
    $relatedProcesses += [pscustomobject]@{pid=$processId;ppid=[int]$p.ParentProcessId;name=[string]$p.Name;to_app=(ReachesApp $processId);command_line=[string]$p.CommandLine}
  }
}

function NativeConnected($h){
  return ([string]$h.hwnd -eq $mainHwnd -or [string]$h.root -eq $mainHwnd -or [string]$h.parent -eq $mainHwnd -or [string]$h.owner -eq $mainHwnd)
}
$candidates=@()
foreach($h in $allHwnds){
  $class=[string]$h.class
  $webClass=($class -match 'Chrome_WidgetWin_[01]|Chrome_RenderWidgetHostHWND|WebView|Chrome')
  $procConnected=($h.pid -eq $AppPid -or (ReachesApp ([int]$h.pid)))
  $nativeConnected=NativeConnected $h
  if(([string]$h.hwnd -eq $mainHwnd) -or $nativeConnected -or ($webClass -and $procConnected)){
    $candidates += [pscustomobject]@{
      hwnd=$h.hwnd;hwnd_int=$h.hwnd_int;pid=$h.pid;process_name=$h.process_name;tid=$h.tid;class=$h.class;title=$h.title;
      visible=$h.visible;enabled=$h.enabled;parent=$h.parent;root=$h.root;owner=$h.owner;
      webview_class=$webClass;process_connected_to_app=$procConnected;native_connected_to_app=$nativeConnected;
      connected_to_app=($procConnected -or $nativeConnected)
    }
  }
}
$candidates=@($candidates|Sort-Object hwnd_int -Unique)

$nodes=New-Object System.Collections.Generic.List[object]
$transitions=New-Object System.Collections.Generic.List[object]
$rootAttempts=New-Object System.Collections.Generic.List[object]

function NewTraversalSummary([string]$view,[string]$sourceHwnd,[int]$sourcePid){
  return [ordered]@{
    view=$view;source_hwnd=$sourceHwnd;source_pid=$sourcePid;started=$false;completed=$false;node_count=0;max_depth=0;
    error_count=0;first_error=$null;last_error=$null;errors=@();cap=$NodeCap;cap_reached=$false;truncated=$false;
    cycle_or_duplicate_count=0;disconnected_count=0;provider_transition_count=0
  }
}
function RecordTraversalError($summary,[string]$stage,$err,[int]$depth,[string]$path){
  $record=[pscustomobject]@{stage=$stage;type=$err.Exception.GetType().FullName;message=$err.Exception.Message;hresult=(HResultText $err);depth=$depth;path=$path}
  $summary.error_count=[int]$summary.error_count+1
  if($null -eq $summary.first_error){$summary.first_error=$record}
  $summary.last_error=$record
  $summary.errors=@($summary.errors)+@($record)
  if($record.type -match 'ElementNotAvailable' -or $record.message -match 'not available|disconnected'){$summary.disconnected_count=[int]$summary.disconnected_count+1}
}
function GetProp($e,[string]$name,$summary,[int]$depth,[string]$path){
  try{return $e.Current.$name}catch{RecordTraversalError $summary ('property:'+ $name) $_ $depth $path;return $null}
}
function GetRuntimeIdTracked($e,$summary,[int]$depth,[string]$path){
  try{return (($e.GetRuntimeId()|ForEach-Object{[string]$_}) -join '.')}catch{RecordTraversalError $summary 'runtime_id' $_ $depth $path;return ''}
}
function DescribeNode($e,[string]$view,$src,[int]$depth,[string]$path,$summary){
  $rid=GetRuntimeIdTracked $e $summary $depth $path
  $ct='';try{$ct=[string]$e.Current.ControlType.ProgrammaticName}catch{RecordTraversalError $summary 'property:ControlType' $_ $depth $path}
  $name=[string](GetProp $e 'Name' $summary $depth $path)
  $automationId=[string](GetProp $e 'AutomationId' $summary $depth $path)
  $framework=[string](GetProp $e 'FrameworkId' $summary $depth $path)
  $native=GetProp $e 'NativeWindowHandle' $summary $depth $path;if($null -eq $native){$native=0}
  $processId=GetProp $e 'ProcessId' $summary $depth $path;if($null -eq $processId){$processId=0}
  $bounds=GetProp $e 'BoundingRectangle' $summary $depth $path
  $vp=$false;$value=$null
  try{$pat=$e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern);if($pat){$vp=$true;$value=$pat.Current.Value}}catch{}
  return [pscustomobject]@{
    view=$view;source_root_hwnd=[string]$src.hwnd;source_root_pid=[int]$src.pid;source_root_class=[string]$src.class;
    source_root_connected=[bool]$src.connected_to_app;depth=$depth;runtime_id=$rid;native_window_handle=[int]$native;process_id=[int]$processId;
    process_name=(ProcessName ([int]$processId));control_type=$ct;name=$name;automation_id=$automationId;framework_id=$framework;
    enabled=[bool](GetProp $e 'IsEnabled' $summary $depth $path);keyboard_focusable=[bool](GetProp $e 'IsKeyboardFocusable' $summary $depth $path);
    has_keyboard_focus=[bool](GetProp $e 'HasKeyboardFocus' $summary $depth $path);offscreen=[bool](GetProp $e 'IsOffscreen' $summary $depth $path);
    is_control_element=[bool](GetProp $e 'IsControlElement' $summary $depth $path);is_content_element=[bool](GetProp $e 'IsContentElement' $summary $depth $path);
    bounds=if($bounds){@($bounds.Left,$bounds.Top,$bounds.Width,$bounds.Height)}else{$null};value_pattern=$vp;value=$value;ancestor_path=$path
  }
}
function WalkTree($root,$walker,[string]$view,$src){
  $summary=NewTraversalSummary $view ([string]$src.hwnd) ([int]$src.pid)
  $stack=New-Object System.Collections.Stack
  $stack.Push(@($root,0,''))
  $seen=New-Object 'System.Collections.Generic.HashSet[string]'
  $summary.started=$true
  while($stack.Count -gt 0){
    if([int]$summary.node_count -ge $NodeCap){$summary.cap_reached=$true;$summary.truncated=$true;break}
    $item=$stack.Pop();$e=$item[0];$depth=[int]$item[1];$path=[string]$item[2]
    $key=ElementKey $e
    if($key -and -not $seen.Add($key)){$summary.cycle_or_duplicate_count=[int]$summary.cycle_or_duplicate_count+1;continue}
    try{$row=DescribeNode $e $view $src $depth $path $summary}catch{RecordTraversalError $summary 'describe_node' $_ $depth $path;continue}
    $nodes.Add($row);$summary.node_count=[int]$summary.node_count+1;if($depth -gt [int]$summary.max_depth){$summary.max_depth=$depth}
    try{
      $kids=New-Object System.Collections.Generic.List[object]
      $ch=$walker.GetFirstChild($e)
      while($null -ne $ch){$kids.Add($ch);$ch=$walker.GetNextSibling($ch)}
      for($i=$kids.Count-1;$i -ge 0;$i--){
        $k=$kids[$i]
        $kPid=0;$kH=0
        try{$kPid=[int]$k.Current.ProcessId}catch{}
        try{$kH=[int]$k.Current.NativeWindowHandle}catch{}
        if(($kPid -ne 0 -and $kPid -ne [int]$row.process_id) -or ($kH -ne 0 -and $kH -ne [int]$row.native_window_handle)){
          $transition=[pscustomobject]@{view=$view;source_root_hwnd=$src.hwnd;from_pid=$row.process_id;to_pid=$kPid;from_native_hwnd=$row.native_window_handle;to_native_hwnd=$kH;parent_runtime_id=$row.runtime_id;child_runtime_id=(RuntimeIdLoose $k);ancestor_path=$path}
          $transitions.Add($transition);$summary.provider_transition_count=[int]$summary.provider_transition_count+1
        }
        $seg="$($row.control_type)|$($row.name)|pid=$($row.process_id)|hwnd=$($row.native_window_handle)"
        $nextPath=$(if($path){$path+' > '+$seg}else{$seg})
        $stack.Push(@($k,$depth+1,$nextPath))
      }
    }catch{RecordTraversalError $summary 'child_enumeration' $_ $depth $path}
  }
  $summary.completed=($stack.Count -eq 0 -and [int]$summary.error_count -eq 0 -and -not [bool]$summary.cap_reached -and -not [bool]$summary.truncated -and [int]$summary.disconnected_count -eq 0 -and [int]$summary.cycle_or_duplicate_count -eq 0)
  return [pscustomobject]$summary
}

foreach($h in $candidates){
  $relevantProvider=[bool]($h.webview_class -and $h.connected_to_app)
  $attempt=[ordered]@{
    hwnd=$h.hwnd;pid=$h.pid;process_name=$h.process_name;class=$h.class;title=$h.title;visible=$h.visible;enabled=$h.enabled;
    parent=$h.parent;root=$h.root;owner=$h.owner;connected_to_app=$h.connected_to_app;process_connected_to_app=$h.process_connected_to_app;
    native_connected_to_app=$h.native_connected_to_app;relevant_provider_root=$relevantProvider;from_handle_success=$false;
    exception_type='';exception_message='';hresult='';root_runtime_id='';root_name='';root_control_type='';root_framework_id='';root_pid=0;root_native_hwnd=0;
    raw_view=$null;control_view=$null;provider_subtree_seen=$false
  }
  try{
    $ae=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]([int64]$h.hwnd_int))
    if($null -eq $ae){throw 'AutomationElement.FromHandle returned null'}
    $attempt.from_handle_success=$true
    $attempt.root_runtime_id=RuntimeIdLoose $ae
    try{$attempt.root_name=[string]$ae.Current.Name}catch{}
    try{$attempt.root_control_type=[string]$ae.Current.ControlType.ProgrammaticName}catch{}
    try{$attempt.root_framework_id=[string]$ae.Current.FrameworkId}catch{}
    try{$attempt.root_pid=[int]$ae.Current.ProcessId}catch{}
    try{$attempt.root_native_hwnd=[int]$ae.Current.NativeWindowHandle}catch{}
    $attempt.raw_view=WalkTree $ae ([System.Windows.Automation.TreeWalker]::RawViewWalker) 'RawView' $h
    $attempt.control_view=WalkTree $ae ([System.Windows.Automation.TreeWalker]::ControlViewWalker) 'ControlView' $h
    $providerNodes=@($nodes|Where-Object{$_.source_root_hwnd -eq $h.hwnd -and ($_.control_type -eq 'ControlType.Document' -or $_.framework_id -match 'Chrome|Chromium|WebView')})
    $attempt.provider_subtree_seen=($providerNodes.Count -gt 0)
  }catch{
    $attempt.exception_type=$_.Exception.GetType().FullName;$attempt.exception_message=$_.Exception.Message;$attempt.hresult=HResultText $_
  }
  $rootAttempts.Add([pscustomobject]$attempt)
}

$html=Get-Content 'web\index.html' -Raw
$moveIdCount=[regex]::Matches($html,'id="move-input"').Count
$moveInputCount=[regex]::Matches($html,'<input\s+id="move-input"').Count
$sourceContract=[ordered]@{
  unique_original_move_edit=($moveIdCount -eq 1 -and $moveInputCount -eq 1);
  move_input_id_occurrences=$moveIdCount;move_input_input_occurrences=$moveInputCount;
  no_qa_proxy_in_product_tree=(-not (Test-Path 'tools\qa'))
}

$edits=@($nodes|Where-Object{$_.control_type -eq 'ControlType.Edit'})
foreach($e in $edits){
  $e|Add-Member -NotePropertyName connected_to_app -NotePropertyValue ([bool]$e.source_root_connected) -Force
  $e|Add-Member -NotePropertyName source_contract_original_possible -NotePropertyValue ([bool]($sourceContract.unique_original_move_edit -and $sourceContract.no_qa_proxy_in_product_tree)) -Force
}
$relevantRoots=@($rootAttempts|Where-Object{$_.relevant_provider_root})
$connectedRelevant=@($relevantRoots|Where-Object{$_.connected_to_app})
$unresolved=0
foreach($r in $relevantRoots){
  $rawOk=($r.raw_view -and $r.raw_view.completed -and $r.raw_view.error_count -eq 0 -and -not $r.raw_view.truncated -and -not $r.raw_view.cap_reached -and $r.raw_view.disconnected_count -eq 0 -and $r.raw_view.cycle_or_duplicate_count -eq 0)
  $controlOk=($r.control_view -and $r.control_view.completed -and $r.control_view.error_count -eq 0 -and -not $r.control_view.truncated -and -not $r.control_view.cap_reached -and $r.control_view.disconnected_count -eq 0 -and $r.control_view.cycle_or_duplicate_count -eq 0)
  if(-not ($r.connected_to_app -and $r.from_handle_success -and $r.provider_subtree_seen -and $rawOk -and $controlOk)){$unresolved++}
}
$nativeRelationship=(@($relevantRoots|Where-Object{$_.native_connected_to_app}).Count -gt 0)
$processRelationship=(@($relevantRoots|Where-Object{$_.process_connected_to_app}).Count -gt 0)
$providerEntry=(@($relevantRoots|Where-Object{$_.from_handle_success}).Count -gt 0)
$subtreeProven=(@($relevantRoots|Where-Object{$_.provider_subtree_seen}).Count -gt 0)
$transitionProven=($transitions.Count -gt 0)
$providerChain=[ordered]@{
  host_found=$true;main_hwnd=$mainHwnd;native_relationship_proven=$nativeRelationship;process_relationship_proven=$processRelationship;
  provider_entry_proven=$providerEntry;uia_subtree_proven=$subtreeProven;provider_transition_proven=$transitionProven;
  relevant_provider_root_count=$relevantRoots.Count;connected_provider_root_count=$connectedRelevant.Count;unresolved_boundary_count=$unresolved
}

$report=[ordered]@{
  classification='C';classification_reasons=@('classification not yet evaluated by fail-closed classifier');evidence_complete=$false;
  product_sha=$env:SOURCE_INTEGRATION_SHA;app_pid=$AppPid;main_hwnd=$mainHwnd;node_cap=$NodeCap;
  candidate_hwnds=$candidates;root_attempts=$rootAttempts;related_processes=$relatedProcesses;nodes=$nodes;provider_transitions=$transitions;
  connected_edits=$edits;provider_chain=$providerChain;source_contract=$sourceContract
}
$report|ConvertTo-Json -Depth 18|Set-Content -Encoding UTF8 uia-topology-report-v5.json
Write-Output "::notice title=UIA_TOPOLOGY_V6_EVIDENCE::hwnds=$($candidates.Count) relevant_roots=$($relevantRoots.Count) roots_ok=$(@($rootAttempts|Where-Object{$_.from_handle_success}).Count) nodes=$($nodes.Count) edits=$($edits.Count) transitions=$($transitions.Count) unresolved=$unresolved"
foreach($a in $rootAttempts){
  $raw=if($a.raw_view){"nodes=$($a.raw_view.node_count),complete=$($a.raw_view.completed),errors=$($a.raw_view.error_count),truncated=$($a.raw_view.truncated)"}else{'none'}
  $ctl=if($a.control_view){"nodes=$($a.control_view.node_count),complete=$($a.control_view.completed),errors=$($a.control_view.error_count),truncated=$($a.control_view.truncated)"}else{'none'}
  Write-Output "HWND $($a.hwnd) pid=$($a.pid) process='$($a.process_name)' class='$($a.class)' connected=$($a.connected_to_app) provider=$($a.relevant_provider_root) fromHandle=$($a.from_handle_success) hr=$($a.hresult) raw=[$raw] control=[$ctl] err='$($a.exception_message)'"
}
