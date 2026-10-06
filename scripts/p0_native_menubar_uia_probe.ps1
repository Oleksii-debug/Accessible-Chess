param(
    [Parameter(Mandatory=$true)][int]$TargetProcessId,
    [Parameter(Mandatory=$true)][long]$MenuHandle,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$root = [System.Windows.Automation.AutomationElement]::RootElement
if($null -eq $root){ throw 'UIA desktop root is unavailable' }

$pidCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ProcessIdProperty,
    $TargetProcessId
)
$menuTypeCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::MenuBar
)
$itemTypeCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::MenuItem
)
$idCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::AutomationIdProperty,
    'AccessibleChessFullProductMenu'
)
$menuCondition = New-Object System.Windows.Automation.AndCondition(
    [System.Windows.Automation.Condition[]]@($pidCondition, $menuTypeCondition)
)
$exactCondition = New-Object System.Windows.Automation.AndCondition(
    [System.Windows.Automation.Condition[]]@($pidCondition, $menuTypeCondition, $idCondition)
)
$anyIdCondition = New-Object System.Windows.Automation.AndCondition(
    [System.Windows.Automation.Condition[]]@($pidCondition, $idCondition)
)

function Convert-UiaRow([System.Windows.Automation.AutomationElement]$Element) {
    if($null -eq $Element){ return $null }
    return [ordered]@{
        automation_id = [string]$Element.Current.AutomationId
        name = [string]$Element.Current.Name
        control_type = [string]$Element.Current.ControlType.ProgrammaticName
        process_id = [int]$Element.Current.ProcessId
        enabled = [bool]$Element.Current.IsEnabled
        offscreen = [bool]$Element.Current.IsOffscreen
        native_window_handle = [int]$Element.Current.NativeWindowHandle
    }
}

function Convert-UiaCollection([System.Windows.Automation.AutomationElementCollection]$Collection) {
    $rows = @()
    for($index = 0; $index -lt $Collection.Count; $index++) {
        $rows += ,(Convert-UiaRow $Collection.Item($index))
    }
    return @($rows)
}

function Convert-MenuBarDetail([System.Windows.Automation.AutomationElement]$MenuBar) {
    $top = $MenuBar.FindAll([System.Windows.Automation.TreeScope]::Children, $itemTypeCondition)
    $names = @()
    $patterns = @()
    for($index = 0; $index -lt $top.Count; $index++) {
        $entry = $top.Item($index)
        $names += ([string]$entry.Current.Name).Replace('&', '').Trim()
        $hasPattern = $false
        try {
            $pattern = $entry.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
            $hasPattern = $null -ne $pattern
        }
        catch {
            $hasPattern = $false
        }
        $patterns += $hasPattern
    }
    return [ordered]@{
        menu = Convert-UiaRow $MenuBar
        top_level_names = @($names)
        top_level_expand_collapse = @($patterns)
    }
}

function Test-CanonicalMenuBinding(
    [object]$FromHandle,
    [object[]]$ExactRows,
    [object[]]$AnyIdRows,
    [int]$ExpectedProcessId,
    [long]$ExpectedMenuHandle
) {
    if($null -eq $FromHandle -or $ExpectedMenuHandle -eq 0){ return $false }
    if($ExactRows.Count -ne 1 -or $AnyIdRows.Count -ne 1){ return $false }
    foreach($row in @($FromHandle, $ExactRows[0], $AnyIdRows[0])) {
        if($null -eq $row){ return $false }
        if([string]$row['automation_id'] -ne 'AccessibleChessFullProductMenu'){ return $false }
        if([string]$row['control_type'] -ne 'ControlType.MenuBar'){ return $false }
        if([int]$row['process_id'] -ne $ExpectedProcessId){ return $false }
        if([long]$row['native_window_handle'] -ne $ExpectedMenuHandle){ return $false }
        if(-not [bool]$row['enabled']){ return $false }
        if([bool]$row['offscreen']){ return $false }
    }
    return $true
}

$bars = $null
$exact = $null
$anyId = $null
$barsRows = @()
$exactRows = @()
$anyIdRows = @()
$fromHandle = $null
$fromHandleError = ''
$bindingStable = $false
$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
do {
    $bars = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $menuCondition)
    $exact = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $exactCondition)
    $anyId = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $anyIdCondition)
    $barsRows = @(Convert-UiaCollection $bars)
    $exactRows = @(Convert-UiaCollection $exact)
    $anyIdRows = @(Convert-UiaCollection $anyId)

    $fromHandle = $null
    $fromHandleError = ''
    if($MenuHandle -ne 0) {
        try {
            $handleElement = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$MenuHandle)
            if($null -ne $handleElement){ $fromHandle = Convert-UiaRow $handleElement }
        }
        catch {
            $fromHandleError = $_.Exception.GetType().Name + ': ' + $_.Exception.Message
        }
    }

    # Presence and uniqueness can precede provider stabilization.  Keep polling
    # until the exact AutomationId and FromHandle views bind the same concrete
    # MenuStrip HWND and all three views are enabled and on-screen.  Persistent
    # disagreement still times out and is rejected by the Python oracle.
    $bindingStable = Test-CanonicalMenuBinding `
        -FromHandle $fromHandle `
        -ExactRows $exactRows `
        -AnyIdRows $anyIdRows `
        -ExpectedProcessId $TargetProcessId `
        -ExpectedMenuHandle $MenuHandle
    if($bindingStable){ break }
    Start-Sleep -Milliseconds 200
} while([DateTime]::UtcNow -lt $deadline)

$barDetails = @()
for($index = 0; $index -lt $bars.Count; $index++) {
    $barDetails += ,(Convert-MenuBarDetail $bars.Item($index))
}

$topNames = @()
$topPatterns = @()
if($exact.Count -eq 1) {
    $detail = Convert-MenuBarDetail $exact.Item(0)
    $topNames = @($detail.top_level_names)
    $topPatterns = @($detail.top_level_expand_collapse)
}

$result = [ordered]@{
    same_process_menu_bars = @($barsRows)
    same_process_menu_bar_details = @($barDetails)
    same_process_elements_with_exact_automation_id = @($anyIdRows)
    exact_menu_bars = @($exactRows)
    exact_menu_bar_count = [int]$exactRows.Count
    menu_binding_stable = [bool]$bindingStable
    menu_from_handle = $fromHandle
    menu_from_handle_error = $fromHandleError
    top_level_names = @($topNames)
    top_level_expand_collapse = @($topPatterns)
}

$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $OutputPath -Encoding utf8
