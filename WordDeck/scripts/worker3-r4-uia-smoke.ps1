param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms

$script:process = $null
function Fail([string]$message) { throw "UIA R4 FAIL: $message" }

function Main-Window {
    if ($null -ne $script:process) {
        try {
            if (-not $script:process.HasExited) {
                $script:process.Refresh()
                if ($script:process.MainWindowHandle -ne [IntPtr]::Zero) {
                    return [System.Windows.Automation.AutomationElement]::FromHandle($script:process.MainWindowHandle)
                }
            }
        } catch { }
    }
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    return $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
        (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, 'WordDeck')))
}

function Find-ByName($root, [string]$name) {
    if ($null -eq $root) { return $null }
    return $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
        (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $name)))
}

function Find-WindowByName([string]$name) {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    return $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
        (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $name)))
}

function Wait-ElementByName($root, [string]$name, [int]$timeoutMs = 15000) {
    $deadline = [DateTime]::UtcNow.AddMilliseconds($timeoutMs)
    do {
        try { $element = Find-ByName $root $name; if ($null -ne $element) { return $element } } catch { }
        Start-Sleep -Milliseconds 150
    } while ([DateTime]::UtcNow -lt $deadline)
    return $null
}

function Wait-WindowByName([string]$name, [int]$timeoutMs = 12000) {
    $deadline = [DateTime]::UtcNow.AddMilliseconds($timeoutMs)
    do {
        try { $window = Find-WindowByName $name; if ($null -ne $window) { return $window } } catch { }
        Start-Sleep -Milliseconds 150
    } while ([DateTime]::UtcNow -lt $deadline)
    return $null
}

function Wait-WindowGone([string]$name, [int]$timeoutMs = 12000) {
    $deadline = [DateTime]::UtcNow.AddMilliseconds($timeoutMs)
    do {
        if ($null -eq (Find-WindowByName $name)) { return }
        Start-Sleep -Milliseconds 150
    } while ([DateTime]::UtcNow -lt $deadline)
    Fail "window '$name' did not close"
}

function Available-Names($root) {
    if ($null -eq $root) { return '<null root>' }
    try {
        $all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
        $names = @()
        foreach ($item in $all) { try { if (-not [string]::IsNullOrWhiteSpace($item.Current.Name)) { $names += $item.Current.Name } } catch { } }
        return (($names | Select-Object -Unique | Select-Object -First 100) -join ' | ')
    } catch { return "<tree enumeration failed: $($_.Exception.Message)>" }
}

function Value-Of($element) {
    if ($null -eq $element) { return $null }
    $pattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$pattern)) {
        return ([System.Windows.Automation.ValuePattern]$pattern).Current.Value
    }
    $textPattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern, [ref]$textPattern)) {
        return ([System.Windows.Automation.TextPattern]$textPattern).DocumentRange.GetText(-1).TrimEnd("`r", "`n")
    }
    return $element.Current.Name
}

function Focused-Name {
    try { $focused = [System.Windows.Automation.AutomationElement]::FocusedElement; if ($null -eq $focused) { return '' }; return $focused.Current.Name }
    catch { return '' }
}

function Assert-Focus([string]$expectedName, [string]$context) {
    $deadline = [DateTime]::UtcNow.AddSeconds(7)
    do { if ((Focused-Name) -eq $expectedName) { return }; Start-Sleep -Milliseconds 100 } while ([DateTime]::UtcNow -lt $deadline)
    Fail "${context}: focus expected '$expectedName'; actual '$(Focused-Name)'"
}

function Send([string]$keys, [int]$delayMs = 300) {
    [System.Windows.Forms.SendKeys]::SendWait($keys)
    Start-Sleep -Milliseconds $delayMs
}

function Exercise-Combo($combo, [string]$name, [int]$cycles) {
    if ($null -eq $combo) { Fail "Missing ComboBox '$name'." }
    $combo.SetFocus(); Assert-Focus $name "$name initial focus"
    for ($i = 0; $i -lt $cycles; $i++) {
        if (($i % 2) -eq 0) { Send '{DOWN}' 120 } else { Send '{UP}' 120 }
        Assert-Focus $name "$name stability cycle $i"
    }
}

function Exercise-NativeTextKeys($element, [string]$name, [scriptblock]$invariant, [string]$context) {
    if ($null -eq $element) { Fail "Missing text control '$name'." }
    $element.SetFocus(); Assert-Focus $name "$context initial focus"
    foreach ($key in @('{UP}','{DOWN}','{LEFT}','{RIGHT}','{HOME}','{END}','{PGUP}','{PGDN}')) {
        Send $key 180; Assert-Focus $name "$context key $key"
        if (-not (& $invariant)) { Fail "$context key $key violated card/prompt invariant" }
    }
}

try {
    $resolved = (Resolve-Path $ExePath).Path
    $script:process = Start-Process -FilePath $resolved -WorkingDirectory (Split-Path -Parent $resolved) -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    $main = $null
    do {
        if ($script:process.HasExited) { Fail "WordDeck exited early with code $($script:process.ExitCode)." }
        $main = Main-Window; if ($null -ne $main) { break }; Start-Sleep -Milliseconds 150
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($null -eq $main) { Fail 'main WordDeck window did not become automatable' }

    $word = Wait-ElementByName $main 'Current English word' 20000
    $translation = Wait-ElementByName $main 'Ukrainian translation' 20000
    $dictionary = Wait-ElementByName $main 'Dictionary' 20000
    $scope = Wait-ElementByName $main 'Recall study scope' 20000
    $deck = Wait-ElementByName $main 'Active Recall deck' 20000
    if ($null -eq $word -or $null -eq $translation -or $null -eq $dictionary -or $null -eq $scope -or $null -eq $deck) {
        Fail "required Recall client controls missing. UIA names: $(Available-Names $main)"
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do { if ((Value-Of $word) -notmatch '^$|No words') { break }; Start-Sleep -Milliseconds 150 } while ([DateTime]::UtcNow -lt $deadline)
    if ((Value-Of $word) -match '^$|No words') { Fail 'no Recall word became available' }

    $word.SetFocus(); Assert-Focus 'Current English word' 'startup Recall word'; $firstWord = Value-Of $word
    Send '^t'; Assert-Focus 'Ukrainian translation' 'translation reveal'; $revealedWord = Value-Of $word
    if ($revealedWord -ne $firstWord) { Fail 'Ctrl+T advanced the Recall card.' }
    Exercise-NativeTextKeys $translation 'Ukrainian translation' { (Value-Of $word) -eq $revealedWord } 'translation native navigation'

    $word.SetFocus(); Send '{DOWN}'; Assert-Focus 'Current English word' 'Recall Down'; $secondWord = Value-Of $word
    if ($secondWord -eq $revealedWord) { Fail 'Down on Current English word did not advance the card.' }
    Send '{UP}'; Assert-Focus 'Current English word' 'Recall true previous'
    if ((Value-Of $word) -ne $revealedWord) { Fail 'Up did not return to the previous actually shown Recall card.' }

    Exercise-Combo $dictionary 'Dictionary' 6
    Exercise-Combo $scope 'Recall study scope' 30
    Exercise-Combo $deck 'Active Recall deck' 20

    $word.SetFocus(); $menuWord = Value-Of $word; Send '%f'; Send '{DOWN}'
    if ((Value-Of $word) -ne $menuWord) { Fail 'Down in File menu changed Recall card.' }; Send '{ESC}'

    $word.SetFocus(); Send '{F1}'; $helpWindow = Wait-WindowByName 'WordDeck help' 10000
    if ($null -eq $helpWindow) { Fail 'F1 help did not open' }
    $helpText = Wait-ElementByName $helpWindow 'WordDeck help text' 10000
    if ($null -eq $helpText) { Fail "F1 help text missing. UIA names: $(Available-Names $helpWindow)" }
    $helpValue = Value-Of $helpText
    if ($helpValue -notmatch 'Fast Down Arrow/Up Arrow card navigation works only while the Current English word field is focused' -or $helpValue -notmatch 'Alt\+F4') {
        Fail 'F1 help does not expose current Recall/Alt+F4 keyboard truth.'
    }
    Send '%{F4}'; Wait-WindowGone 'WordDeck help' 10000

    Send '^+s'; $spelling = Wait-WindowByName 'WordDeck Spelling' 12000
    if ($null -eq $spelling) { Fail 'Spelling did not open' }
    $spellingScope = Wait-ElementByName $spelling 'Spelling study scope' 10000
    $spellingDeck = Wait-ElementByName $spelling 'Active spelling deck' 10000
    $spellingAnswer = Wait-ElementByName $spelling 'Type English spelling answer' 10000
    $spellingPrompt = Wait-ElementByName $spelling 'Ukrainian spelling prompt' 10000
    if ($null -eq $spellingScope -or $null -eq $spellingDeck -or $null -eq $spellingAnswer -or $null -eq $spellingPrompt) { Fail "Spelling controls missing. UIA names: $(Available-Names $spelling)" }
    Exercise-Combo $spellingScope 'Spelling study scope' 20
    Exercise-Combo $spellingDeck 'Active spelling deck' 20
    $spellingPromptBefore = Value-Of $spellingPrompt
    Exercise-NativeTextKeys $spellingAnswer 'Type English spelling answer' { (Value-Of $spellingPrompt) -eq $spellingPromptBefore } 'Spelling answer native navigation'
    Send '%{F4}'; Wait-WindowGone 'WordDeck Spelling' 12000

    Send '^+e'; $sentence = Wait-WindowByName 'WordDeck Sentence Spelling' 12000
    if ($null -eq $sentence) { Fail 'Sentence Spelling did not open' }
    $sentenceDeck = Wait-ElementByName $sentence 'Sentence training spelling deck' 10000
    $targetCount = Wait-ElementByName $sentence 'Number of target words per sentence' 10000
    $sentenceAnswer = Wait-ElementByName $sentence 'Type the English sentence words' 10000
    if ($null -eq $sentenceDeck -or $null -eq $targetCount -or $null -eq $sentenceAnswer) { Fail "Sentence controls missing. UIA names: $(Available-Names $sentence)" }
    Exercise-Combo $sentenceDeck 'Sentence training spelling deck' 20
    Exercise-Combo $targetCount 'Number of target words per sentence' 10
    $sentenceAnswer.SetFocus(); Assert-Focus 'Type the English sentence words' 'Sentence answer focus'
    foreach ($key in @('{UP}','{DOWN}','{LEFT}','{RIGHT}','{HOME}','{END}','{PGUP}','{PGDN}')) { Send $key 120; Assert-Focus 'Type the English sentence words' "Sentence native key $key" }
    Send '%{F4}'; Wait-WindowGone 'WordDeck Sentence Spelling' 12000

    Write-Host 'WordDeck Worker3 Round4 UIA PASS: Recall P0, native text/menu arrows, selector focus retention, F1 truth and Spelling/Sentence keyboard surfaces verified.'
}
finally {
    if ($null -ne $script:process -and -not $script:process.HasExited) {
        try { $script:process.CloseMainWindow() | Out-Null; Start-Sleep -Milliseconds 800 } catch { }
        if (-not $script:process.HasExited) { try { $script:process.Kill() } catch { } }
    }
}
