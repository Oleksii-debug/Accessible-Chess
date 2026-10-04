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

$bars = $null
$exact = $null
$anyId = $null
$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
do {
    $bars = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $menuCondition)
    $exact = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $exactCondition)
    $anyId = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $anyIdCondition)
    if($exact.Count -eq 1 -or $bars.Count -gt 0){ break }
    Start-Sleep -Milliseconds 200
} while([DateTime]::UtcNow -lt $deadline)

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
    same_process_menu_bars = @(Convert-UiaCollection $bars)
    same_process_menu_bar_details = @($barDetails)
    same_process_elements_with_exact_automation_id = @(Convert-UiaCollection $anyId)
    exact_menu_bars = @(Convert-UiaCollection $exact)
    exact_menu_bar_count = [int]$exact.Count
    menu_from_handle = $fromHandle
    menu_from_handle_error = $fromHandleError
    top_level_names = @($topNames)
    top_level_expand_collapse = @($topPatterns)
}

$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $OutputPath -Encoding utf8
