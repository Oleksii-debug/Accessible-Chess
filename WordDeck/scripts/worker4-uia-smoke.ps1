param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class WordDeckNativeWindow {
    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "UIA assertion failed: $Message" }
}

function Wait-Until([scriptblock]$Probe, [int]$TimeoutSeconds = 15, [string]$Failure = 'condition was not met') {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $value = & $Probe
        if ($null -ne $value -and $value -ne $false) { return $value }
        Start-Sleep -Milliseconds 150
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "UIA timeout: $Failure"
}

function Find-ByName(
    [System.Windows.Automation.AutomationElement]$Root,
    [string]$Name,
    [System.Windows.Automation.TreeScope]$Scope = [System.Windows.Automation.TreeScope]::Descendants
) {
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::NameProperty,
        $Name)
    return $Root.FindFirst($Scope, $condition)
}

function Focus-Window([System.Windows.Automation.AutomationElement]$Window) {
    $handle = [IntPtr]$Window.Current.NativeWindowHandle
    if ($handle -ne [IntPtr]::Zero) {
        [void][WordDeckNativeWindow]::SetForegroundWindow($handle)
    }
    Start-Sleep -Milliseconds 200
}

function Close-Window([System.Windows.Automation.AutomationElement]$Window) {
    Focus-Window $Window
    [System.Windows.Forms.SendKeys]::SendWait('%{F4}')
    Start-Sleep -Milliseconds 250
}

$resolved = (Resolve-Path $ExePath).Path
$process = Start-Process -FilePath $resolved -PassThru

try {
    $mainHandle = Wait-Until {
        $process.Refresh()
        if ($process.HasExited) { throw "WordDeck exited early with code $($process.ExitCode)." }
        if ($process.MainWindowHandle -ne 0) { return $process.MainWindowHandle }
        return $null
    } 20 'WordDeck main window did not appear.'

    $main = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$mainHandle)
    Assert-True ($null -ne $main) 'Could not obtain the main AutomationElement.'

    $requiredNames = @(
        'Dictionary',
        'Recall study scope',
        'Active Recall deck',
        'Current English word',
        'Ukrainian translation',
        'Status',
        'Keyboard hint'
    )
    foreach ($name in $requiredNames) {
        $element = Find-ByName $main $name
        Assert-True ($null -ne $element) "Accessible element '$name' was not exposed."
    }

    $word = Find-ByName $main 'Current English word'
    Wait-Until {
        $candidate = Find-ByName $main 'Current English word'
        if ($candidate -and $candidate.Current.HasKeyboardFocus) { return $candidate }
        return $null
    } 10 'Startup focus did not settle on the current English word.' | Out-Null

    Focus-Window $main
    [System.Windows.Forms.SendKeys]::SendWait('{F1}')
    $help = Wait-Until {
        Find-ByName ([System.Windows.Automation.AutomationElement]::RootElement) 'WordDeck help' ([System.Windows.Automation.TreeScope]::Children)
    } 10 'F1 did not open WordDeck help.'
    $helpText = Find-ByName $help 'WordDeck help text'
    Assert-True ($null -ne $helpText) 'F1 help text is not exposed to UI Automation.'
    $valuePattern = $helpText.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    $helpValue = $valuePattern.Current.Value
    Assert-True ($helpValue.Contains('KEYBOARD SHORTCUTS — ACTIVE NOW')) 'F1 does not identify its active binding list.'
    Assert-True ($helpValue.Contains('Spelling: show required English answer')) 'F1 omitted Spelling bindings.'
    Assert-True ($helpValue.Contains('Sentence Spelling: show required English answer')) 'F1 omitted Sentence Spelling bindings.'
    Assert-True ($helpValue.Contains('Unassigned')) 'F1 does not report unassigned actions honestly.'
    Close-Window $help

    Focus-Window $main
    [System.Windows.Forms.SendKeys]::SendWait('^k')
    $settings = Wait-Until {
        Find-ByName ([System.Windows.Automation.AutomationElement]::RootElement) 'Keyboard shortcut settings' ([System.Windows.Automation.TreeScope]::Children)
    } 10 'Configured shortcut did not open keyboard shortcut settings.'
    $shortcutList = Find-ByName $settings 'Shortcut actions'
    Assert-True ($null -ne $shortcutList) 'Shortcut action list is not exposed.'
    Wait-Until {
        $candidate = Find-ByName $settings 'Shortcut actions'
        if ($candidate -and $candidate.Current.HasKeyboardFocus) { return $candidate }
        return $null
    } 5 'Shortcut settings did not place focus on the action list.' | Out-Null
    Close-Window $settings

    Focus-Window $main
    [System.Windows.Forms.SendKeys]::SendWait('^+s')
    $spelling = Wait-Until {
        Find-ByName ([System.Windows.Automation.AutomationElement]::RootElement) 'WordDeck Spelling trainer' ([System.Windows.Automation.TreeScope]::Children)
    } 10 'Spelling trainer did not open from its configured default shortcut.'
    Assert-True ($null -ne (Find-ByName $spelling 'Active spelling deck')) 'Spelling deck selector is not exposed.'
    $spellingAnswer = Find-ByName $spelling 'Type English spelling answer'
    Assert-True ($null -ne $spellingAnswer) 'Spelling answer field is not exposed.'
    Wait-Until {
        $candidate = Find-ByName $spelling 'Type English spelling answer'
        if ($candidate -and $candidate.Current.HasKeyboardFocus) { return $candidate }
        return $null
    } 10 'Spelling did not focus the typing field after loading a card.' | Out-Null
    Close-Window $spelling

    Focus-Window $main
    [System.Windows.Forms.SendKeys]::SendWait('^+e')
    $sentence = Wait-Until {
        Find-ByName ([System.Windows.Automation.AutomationElement]::RootElement) 'WordDeck Sentence Spelling trainer' ([System.Windows.Automation.TreeScope]::Children)
    } 10 'Sentence Spelling trainer did not open from its configured default shortcut.'
    Assert-True ($null -ne (Find-ByName $sentence 'Sentence pack')) 'SentencePack selector is not exposed.'
    Assert-True ($null -ne (Find-ByName $sentence 'Sentence training spelling deck')) 'Sentence spelling-deck scope is not exposed.'
    Assert-True ($null -ne (Find-ByName $sentence 'Number of target words per sentence')) 'Sentence target-count selector is not exposed.'
    Assert-True ($null -ne (Find-ByName $sentence 'Type the English sentence words')) 'Sentence answer field is not exposed.'
    Close-Window $sentence

    Write-Host 'WordDeck Worker4 UI Automation smoke PASSED.'
}
finally {
    if ($process -and -not $process.HasExited) {
        try { $process.CloseMainWindow() | Out-Null } catch { }
        Start-Sleep -Milliseconds 300
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    }
}
