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

function Assert-ShortcutListFocus([string]$context) {
    $before = Get-FocusedName
    if ($before -notmatch '^(Recall|Spelling|Sentence):') {
        Fail "$context expected focus inside Shortcut actions, actual '$before'."
    }
    Send-Keys 'down' 'Shortcut actions'
    $after = Get-FocusedName
    if ($after -notmatch '^(Recall|Spelling|Sentence):') {
        Fail "$context Down left Shortcut actions; actual '$after'."
    }
    if ($after -eq $before) {
        Fail "$context Down did not move to another shortcut action from '$before'."
    }
}

function Send-Keys([string]$keys, [string]$target = '') {
    # Modifier chords require real modifier state. Targeted Enter/Escape also use
    # SendInput so modal dialogs and text controls receive an actual keyboard event
    # after WinApp atomically focuses the intended accessible element.
    $modalKey = $keys -ieq 'enter' -or $keys -ieq 'esc'
    $transport = if ($keys -ieq 'alt+f4') {
        'post-message'
    } elseif ($keys.Contains('+') -or ($modalKey -and -not [string]::IsNullOrWhiteSpace($target))) {
        'send-input'
    } else {
        'post-message'
    }

    $arguments = @('ui','send-keys',$keys,'-a',[string]$script:appPid)
    if (-not [string]::IsNullOrWhiteSpace($target)) {
        $arguments += @('--target',$target)
    }
    $arguments += @('--via',$transport)
    Invoke-WinApp $arguments | Out-Null
    Start-Sleep -Milliseconds 250
}

function Send-MenuKey([string]$keys) {
    # Once a native WinForms menu loop is active, keyboard navigation belongs to
    # that foreground menu, not to the main form HWND.
    Invoke-WinApp @('ui','send-keys',$keys,'-a',[string]$script:appPid,'--via','send-input') | Out-Null
    Start-Sleep -Milliseconds 300
}

function Exercise-Combo([string]$selector, [int]$cycles) {
    Wait-For $selector
    Focus $selector
    Assert-Focus $selector "$selector initial"
    for ($i = 0; $i -lt $cycles; $i++) {
        if (($i % 2) -eq 0) { Send-Keys 'down' $selector } else { Send-Keys 'up' $selector }
        Assert-Focus $selector "$selector stability $i"
    }
}

function Exercise-NativeTextKeys([string]$selector, [scriptblock]$invariant, [string]$context) {
    Wait-For $selector
    Focus $selector
    Assert-Focus $selector "$context initial"
    foreach ($key in @('up','down','left','right','home','end','pgup','pgdn')) {
        Send-Keys $key $selector
        Assert-Focus $selector "$context key $key"
        if (-not (& $invariant)) { Fail "$context key $key violated the current-card/prompt invariant." }
    }
}

function Open-And-CancelDialog([string]$shortcut, [string]$dialogName, [string]$context) {
    Focus 'Current English word'
    $wordBefore = Get-Value 'Current English word'
    Send-Keys $shortcut 'Current English word'
    Wait-For $dialogName 12000
    # Standard Windows file dialogs were already proven with untargeted Escape.
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

    Send-Keys 'ctrl+t' 'Current English word'
    Assert-Focus 'Ukrainian translation' 'translation reveal'
    if ((Get-Value 'Current English word') -ne $firstWord) { Fail 'Ctrl+T advanced the Recall card.' }
    Exercise-NativeTextKeys 'Ukrainian translation' { (Get-Value 'Current English word') -eq $firstWord } 'translation native navigation'

    Focus 'Current English word'
    Send-Keys 'down' 'Current English word'
    Assert-Focus 'Current English word' 'Recall Down'
    $secondWord = Get-Value 'Current English word'
    if ($secondWord -eq $firstWord) { Fail 'Down on Current English word did not advance the card.' }
    Send-Keys 'up' 'Current English word'
    Assert-Focus 'Current English word' 'Recall true previous'
    if ((Get-Value 'Current English word') -ne $firstWord) { Fail 'Up did not restore the previous actually shown Recall card.' }

    Exercise-Combo 'Dictionary' 6
    Exercise-Combo 'Recall study scope' 40
    Exercise-Combo 'Active Recall deck' 20

    Focus 'Current English word'
    $menuWord = Get-Value 'Current English word'
    Send-MenuKey 'alt+f'
    Send-MenuKey 'down'
    if ((Get-Value 'Current English word') -ne $menuWord) { Fail 'Down in the File menu changed the Recall card.' }
    Send-MenuKey 'esc'
    Assert-Focus 'Current English word' 'return from File menu'

    Focus 'Current English word'
    Send-Keys 'f1' 'Current English word'
    Wait-For 'WordDeck help' 7000
    Wait-For 'WordDeck help text' 7000
    $help = Get-Value 'WordDeck help text'
    foreach ($phrase in @(
        'Fast Down Arrow/Up Arrow card navigation works only while the Current English word field is focused',
        'Ukrainian translation TextBox',
        'Open Spelling trainer: Ctrl+Shift+S',
        'Open Sentence Spelling trainer: Ctrl+Shift+E',
        'Alt+F4')) {
        if ($help -notlike "*$phrase*") { Fail "F1 help is missing required truth: $phrase" }
    }
    Send-Keys 'alt+f4'
    Wait-Gone 'WordDeck help' 7000

    Focus 'Current English word'
    Send-Keys 'ctrl+k' 'Current English word'
    Wait-For 'Keyboard shortcut settings' 15000
    Wait-For 'Shortcut actions' 7000
    Assert-ShortcutListFocus 'shortcut settings initial focus'
    Send-Keys 'alt+f4'
    Wait-Gone 'Keyboard shortcut settings' 7000

    Open-And-CancelDialog 'ctrl+alt+e' 'Export complete WordDeck personal progress profile' 'complete profile export dialog'
    Open-And-CancelDialog 'ctrl+shift+i' 'Import complete WordDeck personal progress profile' 'complete profile import dialog'

    # Reset is intentionally unbound. The File menu declares the standard
    # mnemonic "&Reset Recall learning data...". Exercise exactly that Windows
    # keyboard contract: Alt+F opens File, then R is delivered through SendInput
    # to the active native menu loop. No mouse, coordinates, popup focus inference,
    # or fixed arrow count is involved.
    Focus 'Current English word'
    $resetWord = Get-Value 'Current English word'
    Send-MenuKey 'alt+f'
    Send-MenuKey 'r'
    Wait-For 'Reset WordDeck learning data' 7000
    Send-Keys 'esc' 'Reset WordDeck learning data'
    Wait-Gone 'Reset WordDeck learning data' 7000
    Wait-For 'Current English word' 5000
    if ((Get-Value 'Current English word') -ne $resetWord) { Fail 'Cancelling reset changed the current Recall card.' }

    Focus 'Current English word'
    Send-Keys 'ctrl+shift+s' 'Current English word'
    Wait-For 'WordDeck Spelling' 10000
    foreach ($required in @('Type English spelling answer','Ukrainian spelling prompt','Spelling study scope','Active spelling deck')) { Wait-For $required }
    Exercise-Combo 'Spelling study scope' 20
    Exercise-Combo 'Active spelling deck' 20
    $spellingPrompt = Get-Value 'Ukrainian spelling prompt'
    Focus 'Type English spelling answer'
    Send-Keys 'enter' 'Type English spelling answer'
    Assert-Focus 'Type English spelling answer' 'Spelling blank Enter guard'
    if ((Get-Value 'Ukrainian spelling prompt') -ne $spellingPrompt) { Fail 'Blank Enter advanced the Spelling card.' }
    Exercise-NativeTextKeys 'Type English spelling answer' { (Get-Value 'Ukrainian spelling prompt') -eq $spellingPrompt } 'Spelling answer native navigation'
    Send-Keys 'alt+f4'
    Wait-Gone 'WordDeck Spelling' 7000
    Wait-For 'Current English word' 5000

    Focus 'Current English word'
    Send-Keys 'ctrl+shift+e' 'Current English word'
    Wait-For 'WordDeck Sentence Spelling' 10000
    foreach ($required in @('Type the English sentence words','Ukrainian sentence prompt','Sentence training spelling deck','Number of target words per sentence')) { Wait-For $required }
    Exercise-Combo 'Sentence training spelling deck' 20
    Exercise-Combo 'Number of target words per sentence' 10
    $sentencePrompt = Get-Value 'Ukrainian sentence prompt'
    Focus 'Type the English sentence words'
    Send-Keys 'enter' 'Type the English sentence words'
    Assert-Focus 'Type the English sentence words' 'Sentence blank Enter guard'
    if ((Get-Value 'Ukrainian sentence prompt') -ne $sentencePrompt) { Fail 'Blank Enter advanced the Sentence exercise.' }
    Exercise-NativeTextKeys 'Type the English sentence words' { (Get-Value 'Ukrainian sentence prompt') -eq $sentencePrompt } 'Sentence answer native navigation'
    Send-Keys 'alt+f4'
    Wait-Gone 'WordDeck Sentence Spelling' 7000

    Write-Host 'WordDeck R4 integrated UIA PASS: Recall arrows/true previous, selector focus retention, native menu/text navigation, truthful F1/current training bindings, Ctrl+K settings, complete profile/reset dialogs, blank-submit guards, Spelling scope/answer and Sentence keyboard surfaces verified.'
}
finally {
    if ($null -ne $appPid -and $appPid -gt 0) {
        try { Stop-Process -Id $appPid -Force -ErrorAction SilentlyContinue } catch { }
    }
}
