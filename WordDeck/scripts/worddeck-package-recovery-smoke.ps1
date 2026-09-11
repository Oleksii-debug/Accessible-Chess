param(
    [Parameter(Mandatory = $false)]
    [string]$CandidateRoot = '.\artifacts\release'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$script:appPid = $null
$script:stateRoot = Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)) 'WordDeck'
$script:originalStateBackup = Join-Path ([IO.Path]::GetTempPath()) ("WordDeck-package-recovery-original-" + [Guid]::NewGuid().ToString('N'))
$script:replacementRoot = Join-Path ([IO.Path]::GetTempPath()) ("WordDeck package replacement Ω " + [Guid]::NewGuid().ToString('N'))
$script:hadOriginalState = Test-Path -LiteralPath $script:stateRoot

function Fail([string]$message) { throw "WordDeck package recovery FAIL: $message" }

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

function Wait-For([string]$selector, [int]$timeoutMs = 15000) {
    Invoke-WinApp @('ui','wait-for',$selector,'-a',[string]$script:appPid,'--timeout',[string]$timeoutMs) | Out-Null
}

function Get-Value([string]$selector) {
    $result = Invoke-WinApp @('ui','get-value',$selector,'-a',[string]$script:appPid,'--json') -Json
    return [string]$result.text
}

function Focus([string]$selector) {
    Invoke-WinApp @('ui','focus',$selector,'-a',[string]$script:appPid) | Out-Null
}

function Send-Keys([string]$keys, [string]$target = '') {
    $transport = if ($keys -ieq 'alt+f4') { 'post-message' } elseif ($keys.Contains('+')) { 'send-input' } else { 'post-message' }
    $arguments = @('ui','send-keys',$keys,'-a',[string]$script:appPid)
    if (-not [string]::IsNullOrWhiteSpace($target)) { $arguments += @('--target',$target) }
    $arguments += @('--via',$transport)
    Invoke-WinApp $arguments | Out-Null
    Start-Sleep -Milliseconds 350
}

function Start-Candidate([string]$root) {
    $exe = Join-Path $root 'WordDeck.exe'
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { Fail "WordDeck.exe missing from candidate root: $root" }
    $process = Start-Process -FilePath $exe -WorkingDirectory $root -PassThru
    $script:appPid = [int]$process.Id
    if ($script:appPid -le 0) { Fail 'candidate launch returned no valid process ID.' }
    Wait-For 'Current English word' 30000
    Wait-For 'Recall study scope' 10000
}

function Close-CandidateGracefully {
    if ($null -eq $script:appPid -or $script:appPid -le 0) { return }
    Send-Keys 'alt+f4' 'Current English word'
    try { Wait-Process -Id $script:appPid -Timeout 15 -ErrorAction Stop }
    catch { Fail "WordDeck process $script:appPid did not exit after Alt+F4." }
    $script:appPid = $null
}

function Assert-NoPersonalStateInPackage([string]$root, [string]$context) {
    $forbidden = @(Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object {
        $_.Name -match '^state(\.backup)?\.json$' -or
        $_.Name -match '^spelling-state(\.backup)?\.json$' -or
        $_.Name -match '^sentence-coach-state(\.backup)?\.json$' -or
        $_.Name -like 'WordDeck-profile*.json' -or
        $_.FullName -match '[\\/]Backups[\\/]'
    })
    if ($forbidden.Count -ne 0) { Fail "$context contains personal state: $($forbidden.FullName -join ', ')" }
}

function Assert-PersistedJourney([string]$expectedWord, [string]$context) {
    $scope = Get-Value 'Recall study scope'
    if ($scope -ne 'A1') { Fail "$context expected persisted Recall scope A1, actual '$scope'." }
    $word = Get-Value 'Current English word'
    if ($word -ne $expectedWord) { Fail "$context expected persisted current word '$expectedWord', actual '$word'." }
}

try {
    $candidate = (Resolve-Path -LiteralPath $CandidateRoot).Path
    Assert-NoPersonalStateInPackage $candidate 'original candidate'

    # Protect any pre-existing developer/runner profile. The acceptance run gets a
    # clean isolated WordDeck LocalAppData tree, then restores the original bytes.
    if ($script:hadOriginalState) {
        Copy-Item -LiteralPath $script:stateRoot -Destination $script:originalStateBackup -Recurse -Force
        Remove-Item -LiteralPath $script:stateRoot -Recurse -Force
    }

    Start-Candidate $candidate

    # Persist a deterministic, user-visible learning state through the real UI.
    # Home selects All Oxford 5000; Down selects A1. MainForm saves scope/current
    # state immediately and again on graceful FormClosing.
    Focus 'Recall study scope'
    Send-Keys 'home' 'Recall study scope'
    Send-Keys 'down' 'Recall study scope'
    if ((Get-Value 'Recall study scope') -ne 'A1') { Fail 'could not set Recall study scope to A1 through the packaged UI.' }
    Wait-For 'Current English word' 10000
    $persistedWord = Get-Value 'Current English word'
    if ([string]::IsNullOrWhiteSpace($persistedWord) -or $persistedWord -eq 'No words') { Fail 'A1 Recall produced no persisted current word.' }

    Close-CandidateGracefully
    $statePath = Join-Path $script:stateRoot 'state.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { Fail 'graceful close did not publish LocalAppData state.json.' }

    # First reopen: exact same packaged bits must restore semantic learning state.
    Start-Candidate $candidate
    Assert-PersistedJourney $persistedWord 'same-package reopen'
    Close-CandidateGracefully

    # Safe-update transport boundary: replace the entire program tree with a clean
    # copy while personal state remains only in LocalAppData, then launch from the
    # replacement location. This intentionally proves package/state separation;
    # schema migration remains covered by AppStateStore tests and future-version CI.
    Copy-Item -LiteralPath $candidate -Destination $script:replacementRoot -Recurse -Force
    Assert-NoPersonalStateInPackage $script:replacementRoot 'clean replacement candidate'
    Start-Candidate $script:replacementRoot
    Assert-PersistedJourney $persistedWord 'clean-package replacement reopen'
    Close-CandidateGracefully

    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { Fail 'state.json disappeared after clean package replacement.' }
    Write-Host "WordDeck package recovery PASS: graceful close/reopen preserved A1 + current Recall word; clean program-tree replacement reopened against preserved external LocalAppData state; package trees contain no personal state."
}
finally {
    if ($null -ne $script:appPid -and $script:appPid -gt 0) {
        try { Stop-Process -Id $script:appPid -Force -ErrorAction SilentlyContinue } catch { }
    }
    try {
        if (Test-Path -LiteralPath $script:replacementRoot) { Remove-Item -LiteralPath $script:replacementRoot -Recurse -Force }
    } catch { }
    try {
        if (Test-Path -LiteralPath $script:stateRoot) { Remove-Item -LiteralPath $script:stateRoot -Recurse -Force }
        if ($script:hadOriginalState -and (Test-Path -LiteralPath $script:originalStateBackup)) {
            Copy-Item -LiteralPath $script:originalStateBackup -Destination $script:stateRoot -Recurse -Force
        }
        if (Test-Path -LiteralPath $script:originalStateBackup) { Remove-Item -LiteralPath $script:originalStateBackup -Recurse -Force }
    } catch { }
}
