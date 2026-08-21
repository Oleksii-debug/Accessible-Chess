param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms

function Fail([string]$message) { throw "UIA R2 FAIL: $message" }
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
    Wait-Until { (Focused-Name) -eq $expectedName } 5000 "$context: focus did not remain on '$expectedName'; actual '$(Focused-Name)'"
}
function Send([string]$keys) {
    [System.Windows.Forms.SendKeys]::SendWait($keys)
    Start-Sleep -Milliseconds 250
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
    Start-Sleep -Milliseconds 350
    $combo.SetFocus()
    Assert-Focus $name "$name initial focus"
    $before = Combo-SelectionText $combo
    Send '{DOWN}'
    Assert-Focus $name "$name Down"
    $afterDown = Combo-SelectionText $combo
    if ($afterDown -eq $before) {
        Send '{UP}'
        Assert-Focus $name "$name Up fallback"
    }
    for ($i = 0; $i -lt $cycles; $i++) {
        if (($i % 2) -eq 0) { Send '{UP}' } else { Send '{DOWN}' }
        Assert-Focus $name "$name stability cycle $i"
    }
}

$process = $null
try {
    $resolved = (Resolve-Path $ExePath).Path
    $process = Start-Process -FilePath $resolved -PassThru
    Wait-Until { $null -ne (Main-Window) } 15000 'main WordDeck window did not appear'
    $main = Main-Window

    $word = Find-ByName $main 'Current English word'
    $translation = Find-ByName $main 'Ukrainian translation'
    $dictionary = Find-ByName $main 'Dictionary'
    $scope = Find-ByName $main 'Recall study scope'
    $deck = Find-ByName $main 'Active Recall deck'
    if ($null -eq $word -or $null -eq $translation -or $null -eq $dictionary -or $null -eq $scope -or $null -eq $deck) {
        Fail 'one or more required Recall controls are missing from UI Automation'
    }

    Wait-Until { (Value-Of $word) -notmatch '^$|No words' } 15000 'no Recall word became available'
    $word.SetFocus()
    Assert-Focus 'Current English word' 'startup Recall word'
    $firstWord = Value-Of $word

    # Translation regression: Ctrl+T reveals and focuses translation; native
    # navigation keys must never advance the card.
    Send '^t'
    Assert-Focus 'Ukrainian translation' 'translation reveal'
    $revealedWord = Value-Of $word
    if ($revealedWord -ne $firstWord) { Fail 'Ctrl+T advanced the Recall card.' }
    foreach ($key in @('{UP}','{DOWN}','{LEFT}','{RIGHT}','{HOME}','{END}','{PGUP}','{PGDN}')) {
        Send $key
        Assert-Focus 'Ukrainian translation' "translation key $key"
        if ((Value-Of $word) -ne $revealedWord) { Fail "translation key $key changed the Recall card" }
    }

    # Fast arrows remain available on the English word surface.
    $word.SetFocus()
    Send '{DOWN}'
    Assert-Focus 'Current English word' 'Recall Down after translation'
    $secondWord = Value-Of $word
    if ($secondWord -eq $revealedWord) { Fail 'Down on Current English word did not advance the card.' }
    Send '{UP}'
    Assert-Focus 'Current English word' 'Recall true previous'
    if ((Value-Of $word) -ne $revealedWord) { Fail 'Up on Current English word did not restore the previous shown card.' }

    # Native selectors: no Enter prerequisite and no forced focus to card.
    Exercise-Combo $dictionary 'Dictionary' 5
    Exercise-Combo $scope 'Recall study scope' 100
    Exercise-Combo $deck 'Active Recall deck' 30

    # F1 must expose corrected help truth including fixed Spelling Alt+F4.
    $word.SetFocus(); Send '{F1}'
    Wait-Until { $null -ne (Find-WindowByName 'WordDeck help') } 5000 'F1 help did not open'
    $helpWindow = Find-WindowByName 'WordDeck help'
    $helpText = Find-ByName $helpWindow 'WordDeck help text'
    if ($null -eq $helpText) { Fail 'F1 help text is not exposed to UI Automation.' }
    Wait-Until { (Value-Of $helpText) -match 'ROUND 2 KEYBOARD FOCUS RULES' } 5000 'F1 did not receive the Round 2 focus-truth patch'
    $helpValue = Value-Of $helpText
    if ($helpValue -notmatch 'translation has focus' -or $helpValue -notmatch 'Alt\+F4') {
        Fail 'F1 help does not expose translation-native navigation and Spelling Alt+F4 truth.'
    }
    Send '%{F4}'
    Wait-Until { $null -eq (Find-WindowByName 'WordDeck help') } 5000 'help did not close with Alt+F4'

    # Shortcut settings should enter on the action list and close cleanly.
    Send '^k'
    Wait-Until { $null -ne (Find-WindowByName 'Keyboard shortcuts') } 5000 'shortcut settings did not open'
    $settings = Find-WindowByName 'Keyboard shortcuts'
    Assert-Focus 'Shortcut actions' 'shortcut settings initial focus'
    $list = Find-ByName $settings 'Shortcut actions'
    if ($null -eq $list) { Fail 'shortcut action list is not exposed to UIA' }
    Send '%{F4}'
    Wait-Until { $null -eq (Find-WindowByName 'Keyboard shortcuts') } 5000 'shortcut settings did not close'

    # Spelling: answer field is accessible, deck selector keeps focus, Alt+F4
    # closes using native Windows behavior.
    Send '^+s'
    Wait-Until { $null -ne (Find-WindowByName 'WordDeck Spelling') } 7000 'Spelling did not open'
    $spelling = Find-WindowByName 'WordDeck Spelling'
    $spellingAnswer = Find-ByName $spelling 'Type English spelling answer'
    $spellingDeck = Find-ByName $spelling 'Active spelling deck'
    if ($null -eq $spellingAnswer -or $null -eq $spellingDeck) { Fail 'Spelling accessible controls missing' }
    Start-Sleep -Milliseconds 500
    Exercise-Combo $spellingDeck 'Active spelling deck' 20
    Send '%{F4}'
    Wait-Until { $null -eq (Find-WindowByName 'WordDeck Spelling') } 7000 'Spelling did not close with Alt+F4'
    Wait-Until { $null -ne (Main-Window) } 5000 'main window did not resume after Spelling close'

    # Sentence Spelling: selector focus should be stable even when there is no
    # installed SentencePack.
    Send '^+e'
    Wait-Until { $null -ne (Find-WindowByName 'WordDeck Sentence Spelling') } 7000 'Sentence Spelling did not open'
    $sentence = Find-WindowByName 'WordDeck Sentence Spelling'
    $sentenceAnswer = Find-ByName $sentence 'Type the English sentence words'
    $sentenceDeck = Find-ByName $sentence 'Sentence training spelling deck'
    $targetCount = Find-ByName $sentence 'Number of target words per sentence'
    if ($null -eq $sentenceAnswer -or $null -eq $sentenceDeck -or $null -eq $targetCount) { Fail 'Sentence accessible controls missing' }
    Start-Sleep -Milliseconds 500
    Exercise-Combo $sentenceDeck 'Sentence training spelling deck' 20
    Exercise-Combo $targetCount 'Number of target words per sentence' 10
    Send '%{F4}'
    Wait-Until { $null -eq (Find-WindowByName 'WordDeck Sentence Spelling') } 7000 'Sentence Spelling did not close with Alt+F4'

    Write-Host 'WordDeck Worker4 Round2 UIA PASS: translation arrows do not change cards; fast Recall arrows are English-word-only; selectors retain focus without Enter; F1 exposes corrected truth; Spelling/Sentence keyboard entry and Alt+F4 close verified.'
}
finally {
    if ($null -ne $process -and -not $process.HasExited) {
        try { $process.CloseMainWindow() | Out-Null; Start-Sleep -Milliseconds 500 } catch {}
        if (-not $process.HasExited) { try { $process.Kill() } catch {} }
    }
}
