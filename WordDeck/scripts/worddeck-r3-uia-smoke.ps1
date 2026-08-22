param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectPath
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$appPid = $null

function Fail([string]$message) { throw "WordDeck R4 integrated UIA FAIL: $message" }

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

function Wait-Gone([string]$selector, [int]$timeoutMs = 5000) {
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
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    do {
        $actual = Get-FocusedName
        if ($actual -eq $expected) { return }
        Start-Sleep -Milliseconds 150
    } while ([DateTime]::UtcNow -lt $deadline)
    Fail "$context expected focus '$expected', actual '$actual'."
}

function Send-Keys([string]$keys) {
    # Application shortcut combinations need SendInput so the target process sees
    # the held modifier state. Plain navigation stays HWND-targeted. Alt+F4 is a
    # special case: WinApp refuses OS-wide injection unless system keys are opted
    # in, while PostMessage safely closes only the intended WordDeck window/dialog.
    $transport = if ($keys -ieq 'alt+f4') {
        'post-message'
    } elseif ($keys.Contains('+')) {
        'send-input'
    } else {
        'post-message'
    }
    Invoke-WinApp @('ui','send-keys',$keys,'-a',[string]$script:appPid,'--via',$transport) | Out-Null
    Start-Sleep -Milliseconds 250
}

function Exercise-Combo([string]$selector, [int]$cycles) {
    Wait-For $selector
    Focus $selector
    Assert-Focus $selector "$selector initial"
    for ($i = 0; $i -lt $cycles; $i++) {
        if (($i % 2) -eq 0) { Send-Keys 'down' } else { Send-Keys 'up' }
        Assert-Focus $selector "$selector stability $i"
    }
}

function Exercise-NativeTextKeys([string]$selector, [scriptblock]$invariant, [string]$context) {
    Wait-For $selector
    Focus $selector
    Assert-Focus $selector "$context initial"
    foreach ($key in @('up','down','left','right','home','end','pgup','pgdn')) {
        Send-Keys $key
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
    $project = (Resolve-Path -LiteralPath $ProjectPath).Path
    $launch = Invoke-WinApp @('run',$project,'-c','Release','--arch','x64','--detach','--json') -Json
    $appPid = [int]$launch.ProcessId
    if ($appPid -le 0) { Fail 'winapp run did not return a valid process ID.' }

    Wait-For 'Current English word' 30000
    foreach ($required in @('Ukrainian translation','Dictionary','Recall study scope','Active Recall deck')) { Wait-For $required }

    Focus 'Current English word'
    Assert-Focus 'Current English word' 'startup Recall word'
    $firstWord = Get-Value 'Current English word'
    if ([string]::IsNullOrWhiteSpace($firstWord) -or $firstWord -eq 'No words') { Fail 'no Recall word became available.' }

    Send-Keys 'ctrl+t'
    Assert-Focus 'Ukrainian translation' 'translation reveal'
    if ((Get-Value 'Current English word') -ne $firstWord) { Fail 'Ctrl+T advanced the Recall card.' }
    Exercise-NativeTextKeys 'Ukrainian translation' { (Get-Value 'Current English word') -eq $firstWord } 'translation native navigation'

    Focus 'Current English word'
    Send-Keys 'down'
    Assert-Focus 'Current English word' 'Recall Down'
    $secondWord = Get-Value 'Current English word'
    if ($secondWord -eq $firstWord) { Fail 'Down on Current English word did not advance the card.' }
    Send-Keys 'up'
    Assert-Focus 'Current English word' 'Recall true previous'
    if ((Get-Value 'Current English word') -ne $firstWord) { Fail 'Up did not restore the previous actually shown Recall card.' }

    Exercise-Combo 'Dictionary' 6
    Exercise-Combo 'Recall study scope' 40
    Exercise-Combo 'Active Recall deck' 20

    Focus 'Current English word'
    $menuWord = Get-Value 'Current English word'
    Send-Keys 'alt+f'
    Send-Keys 'down'
    if ((Get-Value 'Current English word') -ne $menuWord) { Fail 'Down in the File menu changed the Recall card.' }
    Send-Keys 'esc'
    Assert-Focus 'Current English word' 'return from File menu'

    Focus 'Current English word'
    Send-Keys 'f1'
    Wait-For 'WordDeck help' 5000
    Wait-For 'WordDeck help text' 5000
    $help = Get-Value 'WordDeck help text'
    foreach ($phrase in @(
        'Fast Down Arrow/Up Arrow card navigation works only while the Current English word field is focused',
        'Ukrainian translation TextBox',
        'Alt+F4')) {
        if ($help -notlike "*$phrase*") { Fail "F1 help is missing required truth: $phrase" }
    }
    Send-Keys 'alt+f4'
    Wait-Gone 'WordDeck help' 5000

    Focus 'Current English word'
    Send-Keys 'ctrl+k'
    Wait-For 'Keyboard shortcuts' 5000
    Wait-For 'Shortcut actions' 5000
    Assert-Focus 'Shortcut actions' 'shortcut settings initial focus'
    Send-Keys 'alt+f4'
    Wait-Gone 'Keyboard shortcuts' 5000

    # Standard profile shortcuts must route through the full-v1 profile service,
    # not the historical Recall-only profile path. Opening and cancelling must
    # also leave the current Recall card untouched.
    Open-And-CancelDialog 'ctrl+alt+e' 'Export complete WordDeck personal progress profile' 'complete profile export dialog'
    Open-And-CancelDialog 'ctrl+shift+i' 'Import complete WordDeck personal progress profile' 'complete profile import dialog'

    # Reset is intentionally unbound, so exercise the real File-menu keyboard path.
    Focus 'Current English word'
    $resetWord = Get-Value 'Current English word'
    Send-Keys 'alt+f'
    Send-Keys 'r'
    Wait-For 'Reset WordDeck learning data' 7000
    Send-Keys 'esc'
    Wait-Gone 'Reset WordDeck learning data' 7000
    Wait-For 'Current English word' 5000
    if ((Get-Value 'Current English word') -ne $resetWord) { Fail 'Cancelling reset changed the current Recall card.' }

    Focus 'Current English word'
    Send-Keys 'ctrl+shift+s'
    Wait-For 'WordDeck Spelling' 7000
    foreach ($required in @('Type English spelling answer','Ukrainian spelling prompt','Spelling study scope','Active spelling deck')) { Wait-For $required }
    Exercise-Combo 'Spelling study scope' 20
    Exercise-Combo 'Active spelling deck' 20
    $spellingPrompt = Get-Value 'Ukrainian spelling prompt'
    Exercise-NativeTextKeys 'Type English spelling answer' { (Get-Value 'Ukrainian spelling prompt') -eq $spellingPrompt } 'Spelling answer native navigation'
    Send-Keys 'alt+f4'
    Wait-Gone 'WordDeck Spelling' 7000
    Wait-For 'Current English word' 5000

    Focus 'Current English word'
    Send-Keys 'ctrl+shift+e'
    Wait-For 'WordDeck Sentence Spelling' 7000
    foreach ($required in @('Type the English sentence words','Sentence training spelling deck','Number of target words per sentence')) { Wait-For $required }
    Exercise-Combo 'Sentence training spelling deck' 20
    Exercise-Combo 'Number of target words per sentence' 10
    Exercise-NativeTextKeys 'Type the English sentence words' { $true } 'Sentence answer native navigation'
    Send-Keys 'alt+f4'
    Wait-Gone 'WordDeck Sentence Spelling' 7000

    Write-Host 'WordDeck R4 integrated UIA PASS: Recall arrows/true previous, selector focus retention, native menu/text navigation, F1/shortcut settings, complete profile/reset dialogs, Spelling scope/answer and Sentence keyboard surfaces verified.'
}
finally {
    if ($null -ne $appPid -and $appPid -gt 0) {
        try { Stop-Process -Id $appPid -Force -ErrorAction SilentlyContinue } catch { }
    }
}
