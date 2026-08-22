param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms

function Fail([string]$message) { throw "UIA R3 FAIL: $message" }
function Wait-Until([scriptblock]$condition, [int]$timeoutMs = 10000, [string]$message = 'condition timed out') {
    $deadline = [DateTime]::UtcNow.AddMilliseconds($timeoutMs)
    do {
        if (& $condition) { return }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    Fail $message
}
function Main-Window {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    return $root.FindFirst(
        [System.Windows.Automation.TreeScope]::Children,
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::NameProperty,
            'WordDeck')))
}
function Find-ByName($root, [string]$name) {
    if ($null -eq $root) { return $null }
    return $root.FindFirst(
        [System.Windows.Automation.TreeScope]::Descendants,
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::NameProperty,
            $name)))
}
function Find-WindowByName([string]$name) {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    return $root.FindFirst(
        [System.Windows.Automation.TreeScope]::Children,
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::NameProperty,
            $name)))
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
    $focused = [System.Windows.Automation.AutomationElement]::FocusedElement
    if ($null -eq $focused) { return '' }
    return $focused.Current.Name
}
function Assert-Focus([string]$expectedName, [string]$context) {
    Wait-Until { (Focused-Name) -eq $expectedName } 5000 "${context}: focus expected '$expectedName'; actual '$(Focused-Name)'"
}
function Send([string]$keys, [int]$delayMs = 300) {
    [System.Windows.Forms.SendKeys]::SendWait($keys)
    Start-Sleep -Milliseconds $delayMs
}
function Combo-SelectionText($combo) {
    $pattern = $null
    if ($combo.TryGetCurrentPattern([System.Windows.Automation.SelectionPattern]::Pattern, [ref]$pattern)) {
        $selected = ([System.Windows.Automation.SelectionPattern]$pattern).Current.GetSelection()
        if ($selected.Count -gt 0) { return $selected[0].Current.Name }
    }
    return Value-Of $combo
}
function Exercise-Combo($combo, [string]$name, [int]$cycles) {
    if ($null -eq $combo) { Fail "Missing ComboBox '$name'." }
    Start-Sleep -Milliseconds 400
    $combo.SetFocus()
    Assert-Focus $name "$name initial focus"
    for ($i = 0; $i -lt $cycles; $i++) {
        if (($i % 2) -eq 0) { Send '{DOWN}' } else { Send '{UP}' }
        Assert-Focus $name "$name stability cycle $i"
    }
}
function Exercise-NativeTextKeys($element, [string]$name, [scriptblock]$invariant, [string]$context) {
    if ($null -eq $element) { Fail "Missing text control '$name'." }
    $element.SetFocus()
    Assert-Focus $name "$context initial focus"
    foreach ($key in @('{UP}','{DOWN}','{LEFT}','{RIGHT}','{HOME}','{END}','{PGUP}','{PGDN}')) {
        Send $key
        Assert-Focus $name "$context key $key"
        if (-not (& $invariant)) { Fail "$context key $key violated exercise/card invariant" }
    }
}

$process = $null
try {
    $resolved = (Resolve-Path $ExePath).Path
    $process = Start-Process -FilePath $resolved -PassThru
    Wait-Until { $null -ne (Main-Window) } 20000 'main WordDeck window did not appear'
    $main = Main-Window

    $word = Find-ByName $main 'Current English word'
    $translation = Find-ByName $main 'Ukrainian translation'
    $dictionary = Find-ByName $main 'Dictionary'
    $scope = Find-ByName $main 'Recall study scope'
    $deck = Find-ByName $main 'Active Recall deck'
    if ($null -eq $word -or $null -eq $translation -or $null -eq $dictionary -or $null -eq $scope -or $null -eq $deck) {
        Fail 'one or more required Recall controls are missing from UI Automation'
    }

    Wait-Until { (Value-Of $word) -notmatch '^$|No words' } 20000 'no Recall word became available'
    $word.SetFocus()
    Assert-Focus 'Current English word' 'startup Recall word'
    $firstWord = Value-Of $word

    Send '^t'
    Assert-Focus 'Ukrainian translation' 'translation reveal'
    $revealedWord = Value-Of $word
    if ($revealedWord -ne $firstWord) { Fail 'Ctrl+T advanced the Recall card.' }
    Exercise-NativeTextKeys $translation 'Ukrainian translation' { (Value-Of $word) -eq $revealedWord } 'translation native navigation'

    $word.SetFocus()
    Send '{DOWN}'
    Assert-Focus 'Current English word' 'Recall Down'
    $secondWord = Value-Of $word
    if ($secondWord -eq $revealedWord) { Fail 'Down on Current English word did not advance the card.' }
    Send '{UP}'
    Assert-Focus 'Current English word' 'Recall true previous'
    if ((Value-Of $word) -ne $revealedWord) { Fail 'Up on Current English word did not return to the previous actually shown card.' }

    Exercise-Combo $dictionary 'Dictionary' 6
    Exercise-Combo $scope 'Recall study scope' 100
    Exercise-Combo $deck 'Active Recall deck' 40

    $word.SetFocus()
    $menuWord = Value-Of $word
    Send '%f'
    Send '{DOWN}'
    if ((Value-Of $word) -ne $menuWord) { Fail 'Down in the File menu changed the Recall card.' }
    Send '{ESC}'

    $word.SetFocus(); Send '{F1}'
    Wait-Until { $null -ne (Find-WindowByName 'WordDeck help') } 7000 'F1 help did not open'
    $helpWindow = Find-WindowByName 'WordDeck help'
    $helpText = Find-ByName $helpWindow 'WordDeck help text'
    if ($null -eq $helpText) { Fail 'F1 help text is not exposed to UI Automation.' }
    $helpValue = Value-Of $helpText
    if ($helpValue -notmatch 'Fast Down Arrow/Up Arrow card navigation works only while the Current English word field is focused' -or
        $helpValue -notmatch 'arrow keys keep their native control behavior' -or
        $helpValue -notmatch 'Alt\+F4') {
        Fail 'F1 help does not expose the current word/translation/selector/Alt+F4 keyboard truth.'
    }
    Send '%{F4}'
    Wait-Until { $null -eq (Find-WindowByName 'WordDeck help') } 7000 'help did not close with Alt+F4'

    Send '^k'
    Wait-Until { $null -ne (Find-WindowByName 'Keyboard shortcuts') } 7000 'shortcut settings did not open'
    $settings = Find-WindowByName 'Keyboard shortcuts'
    Assert-Focus 'Shortcut actions' 'shortcut settings initial focus'
    $list = Find-ByName $settings 'Shortcut actions'
    if ($null -eq $list) { Fail 'shortcut action list is not exposed to UIA' }
    $fixedClose = Find-ByName $settings 'Spelling: close trainer — standard Windows Alt+F4'
    if ($null -eq $fixedClose) { Fail 'fixed Spelling Alt+F4 is not exposed in shortcut settings.' }
    Send '%{F4}'
    Wait-Until { $null -eq (Find-WindowByName 'Keyboard shortcuts') } 7000 'shortcut settings did not close'

    Send '^+s'
    Wait-Until { $null -ne (Find-WindowByName 'WordDeck Spelling') } 10000 'Spelling did not open'
    $spelling = Find-WindowByName 'WordDeck Spelling'
    $spellingAnswer = Find-ByName $spelling 'Type English spelling answer'
    $spellingDeck = Find-ByName $spelling 'Active spelling deck'
    $spellingPrompt = Find-ByName $spelling 'Ukrainian spelling prompt'
    if ($null -eq $spellingAnswer -or $null -eq $spellingDeck -or $null -eq $spellingPrompt) { Fail 'Spelling accessible controls missing' }
    Exercise-Combo $spellingDeck 'Active spelling deck' 40
    $spellingPromptBefore = Value-Of $spellingPrompt
    Exercise-NativeTextKeys $spellingAnswer 'Type English spelling answer' { (Value-Of $spellingPrompt) -eq $spellingPromptBefore } 'Spelling answer native navigation'
    Send '%{F4}'
    Wait-Until { $null -eq (Find-WindowByName 'WordDeck Spelling') } 10000 'Spelling did not close with Alt+F4'
    Wait-Until { $null -ne (Main-Window) } 7000 'main window did not resume after Spelling close'

    Send '^+e'
    Wait-Until { $null -ne (Find-WindowByName 'WordDeck Sentence Spelling') } 10000 'Sentence Spelling did not open'
    $sentence = Find-WindowByName 'WordDeck Sentence Spelling'
    $sentenceAnswer = Find-ByName $sentence 'Type the English sentence words'
    $sentenceDeck = Find-ByName $sentence 'Sentence training spelling deck'
    $targetCount = Find-ByName $sentence 'Number of target words per sentence'
    $sentencePrompt = Find-ByName $sentence 'Ukrainian sentence prompt'
    if ($null -eq $sentenceAnswer -or $null -eq $sentenceDeck -or $null -eq $targetCount -or $null -eq $sentencePrompt) { Fail 'Sentence accessible controls missing' }
    Exercise-Combo $sentenceDeck 'Sentence training spelling deck' 40
    Exercise-Combo $targetCount 'Number of target words per sentence' 20
    $sentencePromptBefore = Value-Of $sentencePrompt
    Exercise-NativeTextKeys $sentenceAnswer 'Type the English sentence words' { (Value-Of $sentencePrompt) -eq $sentencePromptBefore } 'Sentence answer native navigation'
    Send '%{F4}'
    Wait-Until { $null -eq (Find-WindowByName 'WordDeck Sentence Spelling') } 10000 'Sentence Spelling did not close with Alt+F4'

    Write-Host 'WordDeck Worker4 Round3 UIA PASS: canonical Recall P0 preserved; menus/text controls keep native arrows; main/Spelling/Sentence selectors retain focus; shared F1/settings truth includes fixed Alt+F4; trainer close paths verified.'
}
finally {
    if ($null -ne $process -and -not $process.HasExited) {
        try { $process.CloseMainWindow() | Out-Null; Start-Sleep -Milliseconds 800 } catch {}
        if (-not $process.HasExited) { try { $process.Kill() } catch {} }
    }
}
