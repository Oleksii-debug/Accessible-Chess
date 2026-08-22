param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms

function Fail([string]$message) { throw "WordDeck R3 UIA FAIL: $message" }
function Wait-Until([scriptblock]$condition, [int]$timeoutMs = 10000, [string]$message = 'condition timed out') {
    $deadline = [DateTime]::UtcNow.AddMilliseconds($timeoutMs)
    do {
        if (& $condition) { return }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    Fail $message
}
function Find-Window([string]$name) {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    return $root.FindFirst(
        [System.Windows.Automation.TreeScope]::Children,
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::NameProperty, $name)))
}
function Find-ByName($root, [string]$name) {
    if ($null -eq $root) { return $null }
    return $root.FindFirst(
        [System.Windows.Automation.TreeScope]::Descendants,
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::NameProperty, $name)))
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
function Assert-Focus([string]$expected, [string]$context) {
    Wait-Until { (Focused-Name) -eq $expected } 5000 "${context}: expected focus '$expected', actual '$(Focused-Name)'"
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
    Start-Sleep -Milliseconds 300
    $combo.SetFocus()
    Assert-Focus $name "$name initial"
    $before = Combo-SelectionText $combo
    Send '{DOWN}'
    Assert-Focus $name "$name Down"
    if ((Combo-SelectionText $combo) -eq $before) { Send '{UP}'; Assert-Focus $name "$name Up fallback" }
    for ($i = 0; $i -lt $cycles; $i++) {
        if (($i % 2) -eq 0) { Send '{UP}' } else { Send '{DOWN}' }
        Assert-Focus $name "$name stability $i"
    }
}

$process = $null
try {
    $resolved = (Resolve-Path -LiteralPath $ExePath).Path
    $process = Start-Process -FilePath $resolved -PassThru
    Wait-Until { $null -ne (Find-Window 'WordDeck') } 15000 'main WordDeck window did not appear'
    $main = Find-Window 'WordDeck'

    $word = Find-ByName $main 'Current English word'
    $translation = Find-ByName $main 'Ukrainian translation'
    $dictionary = Find-ByName $main 'Dictionary'
    $scope = Find-ByName $main 'Recall study scope'
    $deck = Find-ByName $main 'Active Recall deck'
    if ($null -eq $word -or $null -eq $translation -or $null -eq $dictionary -or $null -eq $scope -or $null -eq $deck) {
        Fail 'required Recall controls are not fully exposed through UI Automation'
    }

    Wait-Until { (Value-Of $word) -notmatch '^$|No words' } 15000 'no Recall word became available'
    $word.SetFocus(); Assert-Focus 'Current English word' 'startup Recall word'
    $firstWord = Value-Of $word

    Send '^t'
    Assert-Focus 'Ukrainian translation' 'translation reveal'
    if ((Value-Of $word) -ne $firstWord) { Fail 'Ctrl+T advanced the Recall card.' }
    foreach ($key in @('{UP}','{DOWN}','{LEFT}','{RIGHT}','{HOME}','{END}','{PGUP}','{PGDN}')) {
        Send $key
        Assert-Focus 'Ukrainian translation' "translation native key $key"
        if ((Value-Of $word) -ne $firstWord) { Fail "translation native key $key changed the Recall card" }
    }

    $word.SetFocus(); Send '{DOWN}'
    Assert-Focus 'Current English word' 'Recall Down'
    $secondWord = Value-Of $word
    if ($secondWord -eq $firstWord) { Fail 'Down on Current English word did not advance the card.' }
    Send '{UP}'
    Assert-Focus 'Current English word' 'Recall true previous'
    if ((Value-Of $word) -ne $firstWord) { Fail 'Up did not restore the previous actually shown Recall card.' }

    Exercise-Combo $dictionary 'Dictionary' 5
    Exercise-Combo $scope 'Recall study scope' 40
    Exercise-Combo $deck 'Active Recall deck' 20

    $word.SetFocus(); Send '{F1}'
    Wait-Until { $null -ne (Find-Window 'WordDeck help') } 5000 'F1 help did not open'
    $help = Find-Window 'WordDeck help'
    $helpText = Find-ByName $help 'WordDeck help text'
    if ($null -eq $helpText) { Fail 'F1 help text is not exposed to UI Automation.' }
    $helpValue = Value-Of $helpText
    if ($helpValue -notmatch 'Fast Down Arrow/Up Arrow card navigation works only while the Current English word field is focused' -or
        $helpValue -notmatch 'Ukrainian translation TextBox' -or
        $helpValue -notmatch 'Alt\+F4') {
        Fail 'F1 help does not match the integrated keyboard/focus contract.'
    }
    Send '%{F4}'
    Wait-Until { $null -eq (Find-Window 'WordDeck help') } 5000 'help did not close with Alt+F4'

    Send '^k'
    Wait-Until { $null -ne (Find-Window 'Keyboard shortcuts') } 5000 'shortcut settings did not open'
    Assert-Focus 'Shortcut actions' 'shortcut settings initial focus'
    if ($null -eq (Find-ByName (Find-Window 'Keyboard shortcuts') 'Shortcut actions')) { Fail 'shortcut actions list missing from UIA' }
    Send '%{F4}'
    Wait-Until { $null -eq (Find-Window 'Keyboard shortcuts') } 5000 'shortcut settings did not close'

    Send '^+s'
    Wait-Until { $null -ne (Find-Window 'WordDeck Spelling') } 7000 'Spelling did not open'
    $spelling = Find-Window 'WordDeck Spelling'
    $spellingAnswer = Find-ByName $spelling 'Type English spelling answer'
    $spellingDeck = Find-ByName $spelling 'Active spelling deck'
    if ($null -eq $spellingAnswer -or $null -eq $spellingDeck) { Fail 'Spelling accessible controls missing' }
    Exercise-Combo $spellingDeck 'Active spelling deck' 20
    Send '%{F4}'
    Wait-Until { $null -eq (Find-Window 'WordDeck Spelling') } 7000 'Spelling did not close with Alt+F4'
    Wait-Until { $null -ne (Find-Window 'WordDeck') } 5000 'main window did not resume after Spelling close'

    Send '^+e'
    Wait-Until { $null -ne (Find-Window 'WordDeck Sentence Spelling') } 7000 'Sentence Spelling did not open'
    $sentence = Find-Window 'WordDeck Sentence Spelling'
    $sentenceAnswer = Find-ByName $sentence 'Type the English sentence words'
    $sentenceDeck = Find-ByName $sentence 'Sentence training spelling deck'
    $targetCount = Find-ByName $sentence 'Number of target words per sentence'
    if ($null -eq $sentenceAnswer -or $null -eq $sentenceDeck -or $null -eq $targetCount) { Fail 'Sentence Spelling accessible controls missing' }
    Exercise-Combo $sentenceDeck 'Sentence training spelling deck' 20
    Exercise-Combo $targetCount 'Number of target words per sentence' 10
    Send '%{F4}'
    Wait-Until { $null -eq (Find-Window 'WordDeck Sentence Spelling') } 7000 'Sentence Spelling did not close with Alt+F4'

    Write-Host 'WordDeck R3 UIA PASS: Recall focus/arrows/native controls, F1 truth, shortcut dialog, Spelling and Sentence keyboard entry/control stability verified on packaged EXE.'
}
finally {
    if ($null -ne $process -and -not $process.HasExited) {
        try { $process.CloseMainWindow() | Out-Null; Start-Sleep -Milliseconds 500 } catch { }
        if (-not $process.HasExited) { try { $process.Kill() } catch { } }
    }
}
