param([Parameter(Mandatory=$true)][int]$AppPid)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System; using System.Runtime.InteropServices; using System.Text;
public static class UiaTopoV4 {
 public delegate bool E(IntPtr h,IntPtr l);
 [DllImport("user32.dll")] public static extern bool EnumWindows(E c,IntPtr l);
 [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr p,E c,IntPtr l);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h,uint f);
}
'@
function Get-Hwnds {
 $r=New-Object System.Collections.Generic.List[object]; $seen=New-Object 'System.Collections.Generic.HashSet[long]'
 $one={param([IntPtr]$h);$k=$h.ToInt64();if(-not $seen.Add($k)){return};[uint32]$wp=0;$tid=[UiaTopoV4]::GetWindowThreadProcessId($h,[ref]$wp);$t=New-Object Text.StringBuilder 512;[UiaTopoV4]::GetWindowText($h,$t,512)|Out-Null;$c=New-Object Text.StringBuilder 256;[UiaTopoV4]::GetClassName($h,$c,256)|Out-Null;$par=[UiaTopoV4]::GetParent($h);$root=[UiaTopoV4]::GetAncestor($h,2);$r.Add([pscustomobject]@{hwnd=('0x{0:X}'-f$k);int=$k;pid=[int]$wp;tid=[int]$tid;parent=('0x{0:X}'-f$par.ToInt64());root=('0x{0:X}'-f$root.ToInt64());class=$c.ToString();title=$t.ToString()})}
 $cb=[UiaTopoV4+E]{param($h,$l);&$one $h;[UiaTopoV4]::EnumChildWindows($h,[UiaTopoV4+E]{param($ch,$x);&$one $ch;return $true},[IntPtr]::Zero)|Out-Null;return $true};[UiaTopoV4]::EnumWindows($cb,[IntPtr]::Zero)|Out-Null; return ,$r
}
function Get-ProcRows {
 $all=@(Get-CimInstance Win32_Process|Select-Object ProcessId,ParentProcessId,Name,CommandLine);$map=@{};foreach($p in $all){$map[[int]$p.ProcessId]=$p};$out=@()
 foreach($p in $all|Where-Object{$_.Name -ieq 'msedgewebview2.exe' -or [int]$_.ProcessId -eq $AppPid}){$cur=[int]$p.ProcessId;$chain=@();$to=$false;$g=0;while($cur -gt 0 -and $g++ -lt32 -and $map.ContainsKey($cur)){$chain+=$cur;if($cur -eq $AppPid){$to=$true;break};$cur=[int]$map[$cur].ParentProcessId};$out+=[pscustomobject]@{pid=[int]$p.ProcessId;ppid=[int]$p.ParentProcessId;name=[string]$p.Name;to_app=$to;ancestor_chain=$chain;command_line=[string]$p.CommandLine}}
 return ,$out
}
$polls=@();$allH=@{};$allP=@{}
for($i=0;$i-lt12;$i++){ $ps=@(Get-ProcRows);$hs=@(Get-Hwnds);foreach($p in $ps){$allP[$p.pid]=$p};foreach($h in $hs){$allH[$h.hwnd]=$h};$polls+=[pscustomobject]@{index=$i;utc=(Get-Date).ToUniversalTime().ToString('o');processes=$ps;hwnds=$hs};Start-Sleep -Seconds 3 }
$rows=@($allH.Values);$main=@($rows|Where-Object{$_.pid -eq $AppPid -and $_.title -eq 'Accessible Chess'}|Select-Object -First 1);if(-not $main){throw 'Accessible Chess main HWND not found'};$mainH=$main.hwnd
$connected=@($rows|Where-Object{$_.hwnd -eq $mainH -or $_.root -eq $mainH});$roots=@($connected|Where-Object{$_.hwnd -eq $mainH -or $_.class -match 'Chrome|WebView'})
function P($e,$n){try{return $e.Current.$n}catch{return $null}};function CT($e){try{return [string]$e.Current.ControlType.ProgrammaticName}catch{return ''}}
$nodes=New-Object System.Collections.Generic.List[object]
function Walk($root,$src){$w=[Windows.Automation.TreeWalker]::RawViewWalker;$st=New-Object Collections.Stack;$st.Push(@($root,0,''));while($st.Count -and $nodes.Count -lt20000){$x=$st.Pop();$e=$x[0];$vp=$false;$val=$null;try{$pat=$e.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern);if($pat){$vp=$true;$val=$pat.Current.Value}}catch{};$b=P $e 'BoundingRectangle';$ct=CT $e;$cur=[pscustomobject]@{source_hwnd=$src.hwnd;source_class=$src.class;depth=[int]$x[1];control_type=$ct;name=[string](P $e 'Name');automation_id=[string](P $e 'AutomationId');framework_id=[string](P $e 'FrameworkId');pid=[int](P $e 'ProcessId');focusable=[bool](P $e 'IsKeyboardFocusable');offscreen=[bool](P $e 'IsOffscreen');bounds=if($b){@($b.Left,$b.Top,$b.Width,$b.Height)}else{$null};value_pattern=$vp;value=$val;ancestor_path=[string]$x[2]};$nodes.Add($cur);try{$kids=@();$c=$w.GetFirstChild($e);while($c){$kids+=$c;$c=$w.GetNextSibling($c)};for($j=$kids.Count-1;$j-ge0;$j--){$k=$kids[$j];$st.Push(@($k,$cur.depth+1,"$($cur.ancestor_path)>$ct/$($cur.name)/pid$($cur.pid)"))}}catch{}}}
foreach($r in $roots){try{$ae=[Windows.Automation.AutomationElement]::FromHandle([IntPtr][int64]$r.int);if($ae){Walk $ae $r}}catch{}}
$edits=@($nodes|Where-Object{$_.control_type -eq 'ControlType.Edit'});$moves=@($edits|Where-Object{$_.name -match '^(Хід|Move)$' -and $_.focusable -and -not $_.offscreen -and $_.value_pattern -and $_.bounds[2]-gt0 -and $_.bounds[3]-gt0});$edge=@($allP.Values|Where-Object{$_.name -ieq 'msedgewebview2.exe' -and $_.to_app});$provider=@($nodes|Where-Object{$_.source_class -match 'Chrome|WebView' -and ($_.depth-gt0 -or $_.framework_id -match 'Chrome|WebView|Chromium' -or $_.control_type -eq 'ControlType.Document')});if($moves.Count){$class='A'}elseif($roots.Count -gt1 -and ($edge.Count -gt0 -or $provider.Count -gt0)){$class='B'}else{$class='C'}
[ordered]@{classification=$class;product_sha=$env:SOURCE_INTEGRATION_SHA;app_pid=$AppPid;main_hwnd=$mainH;polls=$polls;related_processes=@($allP.Values);related_msedgewebview2=$edge;connected_hwnds=$connected;roots=$roots;nodes=$nodes;connected_edits=$edits;move_candidates=$moves}|ConvertTo-Json -Depth 12|Set-Content -Encoding UTF8 uia-topology-report-v4.json
Write-Output "::notice title=UIA_TOPOLOGY_CLASSIFICATION::classification=$class polls=$($polls.Count) edge=$($edge.Count) roots=$($roots.Count) nodes=$($nodes.Count) edits=$($edits.Count) moves=$($moves.Count)"
if($class -eq 'C'){Write-Output 'C_INCONCLUSIVE: no product attribution allowed.'}
