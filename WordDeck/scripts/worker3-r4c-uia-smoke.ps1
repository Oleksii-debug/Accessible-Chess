param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$appPid = $null
$appProcess = $null

function Fail([string]$message) { throw "UIA R4c FAIL: $message" }

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
    $deadline = [DateTime]::UtcNow.AddSeconds(7)
    $actual = ''
    do {
        $actual = Get-FocusedName
        if ($actual -eq $expected) { return }
        Start-Sleep -Milliseconds 150
    } while ([DateTime]::UtcNow -lt $deadline)
    Fail "$context expected focus '$expected', actual '$actual'."
}

function Send-Keys([string]$keys, [int]$delayMs = 300) {
    $transport = if ($keys.Contains('+')) { 'send-input' } else { 'post-message' }
    $arguments = @('ui','send-keys',$keys,'-a',[string]$script:appPid,'--via',$transport)
    if ($keys -ieq 'alt+f4') {
        # Alt+F4 is the only system-reserved chord intentionally synthesized.
        # This verifies standard Windows close rather than an app-owned shortcut.
        $arguments += '--allow-system-keys'
    }
    Invoke-WinApp $arguments | Out-Null
    Start-Sleep -Milliseconds $delayMs
}

function Settle-MainFocus([string]$context) {
    Wait-For 'Current English word' 7000
    Focus 'Current English word'
    Assert-Focus 'Current English word' $context
    Start-Sleep -Milliseconds 250
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
        if (-not (& $invariant)) { Fail "$context key $key violated its invariant." }
    }
}

function Open-And-CancelDialog([string]$shortcut, [string]$dialogName, [string]$context) {
    Settle-MainFocus "$context pre-open"
    $wordBefore = Get-Value 'Current English word'
    Send-Keys $shortcut
    Wait-For $dialogName 10000
    Send-Keys 'esc'
    Wait-Gone $dialogName 10000
    Settle-MainFocus "$context return"
    if ((Get-Value 'Current English word') -ne $wordBefore) { Fail "$context changed the current Recall card while cancelled." }
}

function Exercise-ShortcutSettings([string]$context) {
    Settle-MainFocus "$context pre-Ctrl+K"
    Send-Keys 'ctrl+k'
    Wait-For 'Keyboard shortcuts' 10000
    Wait-For 'Shortcut actions' 7000
    Focus 'Shortcut actions'
    Assert-Focus 'Shortcut actions' "$context list focus"
    Send-Keys 'enter'
    Wait-For 'Press new shortcut' 7000
    Wait-For 'Captured shortcut' 7000
    Send-Keys 'esc'
    Wait-Gone 'Press new shortcut' 7000
    Wait-For 'Keyboard shortcuts' 5000
    Send-Keys 'alt+f4'
    Wait-Gone 'Keyboard shortcuts' 7000
    Settle-MainFocus "$context after close"
}

try {
    $exe = (Resolve-Path -LiteralPath $ExePath).Path
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { Fail "exact published EXE not found: $exe" }
    if ([IO.Path]::GetFileName($exe) -ne 'WordDeck.exe') { Fail "unexpected acceptance executable: $exe" }

    # Final acceptance attaches to the already-published artifact. It must not
    # rebuild/relaunch a project and accidentally test different bits.
    $appProcess = Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe) -PassThru
    $appPid = [int]$appProcess.Id
    if ($appPid -le 0) { Fail 'Start-Process did not return a valid WordDeck process ID.' }

    Wait-For 'Current English word' 30000
    foreach ($required in @('Ukrainian translation','Dictionary','Recall study scope','Active Recall deck')) { Wait-For $required }

    Settle-MainFocus 'startup Recall word'
    $firstWord = Get-Value 'Current English word'
    if ([string]::IsNullOrWhiteSpace($firstWord) -or $firstWord -eq 'No words') { Fail 'no Recall word became available.' }

    # Natalia P0: translation is a native explorable text surface.
    Send-Keys 'ctrl+t'
    Assert-Focus 'Ukrainian translation' 'translation reveal'
    if ((Get-Value 'Current English word') -ne $firstWord) { Fail 'Ctrl+T advanced the Recall card.' }
    Exercise-NativeTextKeys 'Ukrainian translation' { (Get-Value 'Current English word') -eq $firstWord } 'translation native navigation'

    # Natalia P0: fast Up/Down belongs only to the English word surface.
    Settle-MainFocus 'Recall navigation surface'
    Send-Keys 'down'
    Assert-Focus 'Current English word' 'Recall Down'
    $secondWord = Get-Value 'Current English word'
    if ($secondWord -eq $firstWord) { Fail 'Down on Current English word did not advance the card.' }
    Send-Keys 'up'
    Assert-Focus 'Current English word' 'Recall true previous'
    if ((Get-Value 'Current English word') -ne $firstWord) { Fail 'Up did not restore the previous actually shown Recall card.' }

    # Native selector changes need no Enter and must retain focus repeatedly.
    Exercise-Combo 'Dictionary' 8
    Exercise-Combo 'Recall study scope' 60
    Exercise-Combo 'Active Recall deck' 40

    # Menu arrows remain menu navigation rather than leaking into Recall.
    Settle-MainFocus 'File-menu test'
    $menuWord = Get-Value 'Current English word'
    Send-Keys 'alt+f'
    Send-Keys 'down'
    if ((Get-Value 'Current English word') -ne $menuWord) { Fail 'Down in the File menu changed the Recall card.' }
    Send-Keys 'esc'
    Assert-Focus 'Current English word' 'return from File menu'

    # Prove Ctrl+K before F1 so the exact historical failure becomes diagnosable.
    Exercise-ShortcutSettings 'Ctrl+K before F1'

    # F1 is acceptance evidence for the same live shortcut registry used by settings.
    Settle-MainFocus 'F1 pre-open'
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
    Settle-MainFocus 'return from F1 help'

    # Re-prove Ctrl+K after F1; this is the exact canonical candidate failure point.
    Exercise-ShortcutSettings 'Ctrl+K after F1'

    # Full-profile dialogs must be keyboard reachable/cancellable without mutation.
    Open-And-CancelDialog 'ctrl+alt+e' 'Export complete WordDeck personal progress profile' 'complete profile export dialog'
    Open-And-CancelDialog 'ctrl+shift+i' 'Import complete WordDeck personal progress profile' 'complete profile import dialog'

    # Reset is deliberately unbound: exercise the actual menu path and cancel.
    Settle-MainFocus 'reset pre-open'
    $resetWord = Get-Value 'Current English word'
    Send-Keys 'alt+f'
    Send-Keys 'r'
    Wait-For 'Reset WordDeck learning data' 7000
    Send-Keys 'esc'
    Wait-Gone 'Reset WordDeck learning data' 7000
    Settle-MainFocus 'reset return'
    if ((Get-Value 'Current English word') -ne $resetWord) { Fail 'Cancelling reset changed the current Recall card.' }

    # Spelling mode: native selector/input arrows and standard Alt+F4 close.
    Settle-MainFocus 'Spelling pre-open'
    Send-Keys 'ctrl+shift+s'
    Wait-For 'WordDeck Spelling' 10000
    foreach ($required in @('Type English spelling answer','Ukrainian spelling prompt','Spelling study scope','Active spelling deck')) { Wait-For $required }
    Exercise-Combo 'Spelling study scope' 40
    Exercise-Combo 'Active spelling deck' 40
    $spellingPrompt = Get-Value 'Ukrainian spelling prompt'
    Exercise-NativeTextKeys 'Type English spelling answer' { (Get-Value 'Ukrainian spelling prompt') -eq $spellingPrompt } 'Spelling answer native navigation'
    Send-Keys 'alt+f4'
    Wait-Gone 'WordDeck Spelling' 10000
    Settle-MainFocus 'Spelling return'

    # Sentence mode: do not require a production pack to be installed. Exercise
    # every control that must exist in the safe empty/import-capable shell.
    Send-Keys 'ctrl+shift+e'
    Wait-For 'WordDeck Sentence Spelling' 10000
    foreach ($required in @('Sentence training spelling deck','Number of target words per sentence','Type the English sentence words')) { Wait-For $required }
    Exercise-Combo 'Sentence training spelling deck' 30
    Exercise-Combo 'Number of target words per sentence' 20
    Exercise-NativeTextKeys 'Type the English sentence words' { $true } 'Sentence answer native navigation'
    Send-Keys 'alt+f4'
    Wait-Gone 'WordDeck Sentence Spelling' 10000

    # Repeated mode round-trip must return a useful main-window focus target.
    for ($round = 0; $round -lt 3; $round++) {
        Settle-MainFocus "final focus recovery $round"
    }

    Write-Host 'WordDeck Worker3 R4c ACTUAL WinApp UIA PASS: exact published EXE, Natalia translation/native arrows, Recall next/true-previous, repeated selector focus, menu arrows, Ctrl+K before/after F1, truthful F1, shortcut capture cancellation, full-profile/reset dialogs, Spelling/Sentence native inputs and Alt+F4 close verified.'
}
finally {
    if ($null -ne $appPid -and $appPid -gt 0) {
        try { Stop-Process -Id $appPid -Force -ErrorAction SilentlyContinue } catch { }
    }
}