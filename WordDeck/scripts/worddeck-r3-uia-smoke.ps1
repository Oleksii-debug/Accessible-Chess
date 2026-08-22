param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectPath
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$appPid = $null

function Fail([string]$message) { throw "WordDeck R3 UIA FAIL: $message" }

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
    Invoke-WinApp @('ui','send-keys',$keys,'-a',[string]$script:appPid,'--via','post-message') | Out-Null
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
    foreach ($key in @('up','down','left','right','home','end','pgup','pgdn')) {
        Send-Keys $key
        Assert-Focus 'Ukrainian translation' "translation native key $key"
        if ((Get-Value 'Current English word') -ne $firstWord) { Fail "translation native key $key changed the Recall card." }
    }

    Focus 'Current English word'
    Send-Keys 'down'
    Assert-Focus 'Current English word' 'Recall Down'
    $secondWord = Get-Value 'Current English word'
    if ($secondWord -eq $firstWord) { Fail 'Down on Current English word did not advance the card.' }
    Send-Keys 'up'
    Assert-Focus 'Current English word' 'Recall true previous'
    if ((Get-Value 'Current English word') -ne $firstWord) { Fail 'Up did not restore the previous actually shown Recall card.' }

    Exercise-Combo 'Dictionary' 5
    Exercise-Combo 'Recall study scope' 40
    Exercise-Combo 'Active Recall deck' 20

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

    Focus 'Current English word'
    Send-Keys 'ctrl+shift+s'
    Wait-For 'WordDeck Spelling' 7000
    foreach ($required in @('Type English spelling answer','Active spelling deck')) { Wait-For $required }
    Exercise-Combo 'Active spelling deck' 20
    Send-Keys 'alt+f4'
    Wait-Gone 'WordDeck Spelling' 7000
    Wait-For 'Current English word' 5000

    Focus 'Current English word'
    Send-Keys 'ctrl+shift+e'
    Wait-For 'WordDeck Sentence Spelling' 7000
    foreach ($required in @('Type the English sentence words','Sentence training spelling deck','Number of target words per sentence')) { Wait-For $required }
    Exercise-Combo 'Sentence training spelling deck' 20
    Exercise-Combo 'Number of target words per sentence' 10
    Send-Keys 'alt+f4'
    Wait-Gone 'WordDeck Sentence Spelling' 7000

    Write-Host 'WordDeck R3 UIA PASS: exact-head WinForms UI Automation verified Recall focus/arrows/native controls, F1 truth, shortcut settings, Spelling and Sentence keyboard entry/control stability.'
}
finally {
    if ($null -ne $appPid -and $appPid -gt 0) {
        try { Stop-Process -Id $appPid -Force -ErrorAction SilentlyContinue } catch { }
    }
}
