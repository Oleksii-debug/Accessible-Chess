param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$appPid = $null
$appProcess = $null

function Fail([string]$message) { throw "UIA R4b FAIL: $message" }

function Invoke-WinApp([string[]]$arguments, [switch]$Json) {
    $output = & winapp @arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Fail "winapp $($arguments -join ' ') exited with code $exitCode. Output: $($output -join ' ')"
    }
    if ($Json) {
        try { return ($output | Out-String | ConvertFrom-Json) }
        catch { Fail "winapp returned invalid JSON for: $($arguments -join ' ')" }
    }
    return $output
}

function Wait-For([string]$selector, [int]$timeoutMs = 10000) {
    Invoke-WinApp @('ui','wait-for',$selector,'-a',[string]$script:appPid,'--timeout',[string]$timeoutMs) | Out-Null
}

function Wait-Gone([string]$selector, [int]$timeoutMs = 7000) {
    Invoke-WinApp @('ui','wait-for',$selector,'-a',[string]$script:appPid,'--gone','--timeout',[string]$timeoutMs) | Out-Null
}

function Get-Value([string]$selector) {
    $result = Invoke-WinApp @('ui','get-value',$selector,'-a',[string]$script:appPid,'--json') -Json
    return [string]$result.text
}

function Focus([string]$selector) {
    Invoke-WinApp @('ui','focus',$selector,'-a',[string]$script:appPid) | Out-Null
}

function Get-FocusedName {
    $result = Invoke-WinApp @('ui','get-focused','-a',[string]$script:appPid,'--json') -Json
    if (-not $result.hasFocus -or $null -eq $result.element) { return '' }
    return [string]$result.element.name
}

function Assert-Focus([string]$expected, [string]$context) {
    $deadline = [DateTime]::UtcNow.AddSeconds(6)
    do {
        $actual = Get-FocusedName
        if ($actual -eq $expected) { return }
        Start-Sleep -Milliseconds 150
    } while ([DateTime]::UtcNow -lt $deadline)
    Fail "$context expected focus '$expected', actual '$actual'."
}

function Send-Keys([string]$keys, [int]$delayMs = 250) {
    $transport = if ($keys.Contains('+')) { 'send-input' } else { 'post-message' }
    Invoke-WinApp @('ui','send-keys',$keys,'-a',[string]$script:appPid,'--via',$transport) | Out-Null
    Start-Sleep -Milliseconds $delayMs
}

function Exercise-Combo([string]$selector, [int]$cycles) {
    Wait-For $selector
    Focus $selector
    Assert-Focus $selector "$selector initial"
    for ($i = 0; $i -lt $cycles; $i++) {
        if (($i % 2) -eq 0) { Send-Keys 'down' 120 } else { Send-Keys 'up' 120 }
        Assert-Focus $selector "$selector stability $i"
    }
}

function Exercise-NativeTextKeys([string]$selector, [scriptblock]$invariant, [string]$context) {
    Wait-For $selector
    Focus $selector
    Assert-Focus $selector "$context initial"
    foreach ($key in @('up','down','left','right','home','end','pgup','pgdn')) {
        Send-Keys $key 150
        Assert-Focus $selector "$context key $key"
        if (-not (& $invariant)) { Fail "$context key $key violated the current-card/prompt invariant." }
    }
}

function Open-And-CancelDialog([string]$shortcut, [string]$dialogName, [string]$context) {
    Focus 'Current English word'
    $wordBefore = Get-Value 'Current English word'
    Send-Keys $shortcut
    Wait-For $dialogName 10000
    Send-Keys 'esc'
    Wait-Gone $dialogName 10000
    Wait-For 'Current English word' 5000
    if ((Get-Value 'Current English word') -ne $wordBefore) { Fail "$context changed the current Recall card while being cancelled." }
}

try {
    $exe = (Resolve-Path -LiteralPath $ExePath).Path
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { Fail "exact published EXE not found: $exe" }
    if ([IO.Path]::GetFileName($exe) -ne 'WordDeck.exe') { Fail "unexpected acceptance executable: $exe" }

    # Launch the exact self-contained EXE that passed the artifact gate. WinApp CLI
    # is used strictly as the UI Automation transport and attaches by process ID;
    # it must not rebuild or launch a project for final release acceptance.
    $appProcess = Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe) -PassThru
    $appPid = [int]$appProcess.Id
    if ($appPid -le 0) { Fail 'Start-Process did not return a valid WordDeck process ID.' }

    Wait-For 'Current English word' 30000
    foreach ($required in @('Ukrainian translation','Dictionary','Recall study scope','Active Recall deck')) { Wait-For $required }

    Focus 'Current English word'
    Assert-Focus 'Current English word' 'startup Recall word'
    $firstWord = Get-Value 'Current English word'
    if ([string]::IsNullOrWhiteSpace($firstWord) -or $firstWord -eq 'No words') { Fail 'no Recall word became available.' }

    # P0: the revealed translation remains a native text-reading surface.
    Send-Keys 'ctrl+t'
    Assert-Focus 'Ukrainian translation' 'translation reveal'
    if ((Get-Value 'Current English word') -ne $firstWord) { Fail 'Ctrl+T advanced the Recall card.' }
    Exercise-NativeTextKeys 'Ukrainian translation' { (Get-Value 'Current English word') -eq $firstWord } 'translation native navigation'

    # P0: Down/Up are next/true-previous only on the English-word surface.
    Focus 'Current English word'
    Send-Keys 'down'
    Assert-Focus 'Current English word' 'Recall Down'
    $secondWord = Get-Value 'Current English word'
    if ($secondWord -eq $firstWord) { Fail 'Down on Current English word did not advance the card.' }
    Send-Keys 'up'
    Assert-Focus 'Current English word' 'Recall true previous'
    if ((Get-Value 'Current English word') -ne $firstWord) { Fail 'Up did not restore the previous actually shown Recall card.' }

    # Repeated native selector navigation without Enter; focus must never jump to the card.
    Exercise-Combo 'Dictionary' 6
    Exercise-Combo 'Recall study scope' 40
    Exercise-Combo 'Active Recall deck' 30

    # Menu Down remains menu navigation, not card navigation.
    Focus 'Current English word'
    $menuWord = Get-Value 'Current English word'
    Send-Keys 'alt+f'
    Send-Keys 'down'
    if ((Get-Value 'Current English word') -ne $menuWord) { Fail 'Down in the File menu changed the Recall card.' }
    Send-Keys 'esc'
    Assert-Focus 'Current English word' 'return from File menu'

    # F1 must state the current keyboard model and expose the unified training registry.
    Focus 'Current English word'
    Send-Keys 'f1'
    Wait-For 'WordDeck help' 7000
    Wait-For 'WordDeck help text' 7000
    $help = Get-Value 'WordDeck help text'
    foreach ($phrase in @(
        'Fast Down Arrow/Up Arrow card navigation works only while the Current English word field is focused',
        'Ukrainian translation TextBox',
        'Open Spelling trainer',
        'Open Sentence Spelling trainer',
        'Alt+F4')) {
        if ($help -notlike "*$phrase*") { Fail "F1 help is missing required truth: $phrase" }
    }
    Send-Keys 'alt+f4'
    Wait-Gone 'WordDeck help' 7000

    # Shortcut settings: list focus, Enter capture, Escape cancel, settings remain open.
    Focus 'Current English word'
    Send-Keys 'ctrl+k'
    Wait-For 'Keyboard shortcuts' 7000
    Wait-For 'Shortcut actions' 7000
    Focus 'Shortcut actions'
    Assert-Focus 'Shortcut actions' 'shortcut settings initial focus'
    Send-Keys 'enter'
    Wait-For 'Press new shortcut' 7000
    Wait-For 'Captured shortcut' 7000
    Send-Keys 'esc'
    Wait-Gone 'Press new shortcut' 7000
    Wait-For 'Keyboard shortcuts' 5000
    Send-Keys 'alt+f4'
    Wait-Gone 'Keyboard shortcuts' 7000

    # Profile dialogs are keyboard-reachable and cancellable without mutating the current card.
    Open-And-CancelDialog 'ctrl+alt+e' 'Export WordDeck personal progress profile' 'profile export dialog'
    Open-And-CancelDialog 'ctrl+shift+i' 'Import WordDeck personal progress profile' 'profile import dialog'

    # Reset is unbound by design; exercise the actual File-menu path and cancel safely.
    Focus 'Current English word'
    $resetWord = Get-Value 'Current English word'
    Send-Keys 'alt+f'
    Send-Keys 'r'
    Wait-For 'Reset WordDeck learning data' 7000
    Send-Keys 'n'
    Wait-Gone 'Reset WordDeck learning data' 7000
    Wait-For 'Current English word' 5000
    if ((Get-Value 'Current English word') -ne $resetWord) { Fail 'Cancelling reset changed the current Recall card.' }

    # Spelling: repeated selectors and native answer-field navigation.
    Focus 'Current English word'
    Send-Keys 'ctrl+shift+s'
    Wait-For 'WordDeck Spelling' 10000
    foreach ($required in @('Type English spelling answer','Ukrainian spelling prompt','Spelling study scope','Active spelling deck')) { Wait-For $required }
    Exercise-Combo 'Spelling study scope' 30
    Exercise-Combo 'Active spelling deck' 30
    $spellingPrompt = Get-Value 'Ukrainian spelling prompt'
    Exercise-NativeTextKeys 'Type English spelling answer' { (Get-Value 'Ukrainian spelling prompt') -eq $spellingPrompt } 'Spelling answer native navigation'
    Send-Keys 'alt+f4'
    Wait-Gone 'WordDeck Spelling' 10000
    Wait-For 'Current English word' 5000

    # Sentence: pack/deck/target selectors and native answer-field navigation.
    Focus 'Current English word'
    Send-Keys 'ctrl+shift+e'
    Wait-For 'WordDeck Sentence Spelling' 10000
    foreach ($required in @('Sentence pack','Sentence training spelling deck','Number of target words per sentence','Type the English sentence words')) { Wait-For $required }
    Exercise-Combo 'Sentence pack' 10
    Exercise-Combo 'Sentence training spelling deck' 30
    Exercise-Combo 'Number of target words per sentence' 20
    Exercise-NativeTextKeys 'Type the English sentence words' { $true } 'Sentence answer native navigation'
    Send-Keys 'alt+f4'
    Wait-Gone 'WordDeck Sentence Spelling' 10000

    # One final round-trip proves useful focus after modal trainers and dialogs close.
    Wait-For 'Current English word' 5000
    Focus 'Current English word'
    Assert-Focus 'Current English word' 'final main focus recovery'

    Write-Host 'WordDeck Worker3 R4b ACTUAL WinApp UIA PASS: exact published EXE, Recall next/true-previous, translation/menu native arrows, repeated selector focus, truthful F1, shortcut capture cancellation, profile/reset dialogs, Spelling and Sentence keyboard surfaces verified.'
}
finally {
    if ($null -ne $appPid -and $appPid -gt 0) {
        try { Stop-Process -Id $appPid -Force -ErrorAction SilentlyContinue } catch { }
    }
}
