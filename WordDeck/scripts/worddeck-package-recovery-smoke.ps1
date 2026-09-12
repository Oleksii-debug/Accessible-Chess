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
$script:originalBackupPrepared = $false
$script:primaryFailure = $null
$script:cleanupFailures = [System.Collections.Generic.List[string]]::new()

function Fail([string]$message) { throw "WordDeck package recovery FAIL: $message" }

function Record-CleanupFailure([string]$phase, $errorRecord) {
    $message = if ($null -ne $errorRecord -and $null -ne $errorRecord.Exception) {
        $errorRecord.Exception.Message
    } else {
        [string]$errorRecord
    }
    $script:cleanupFailures.Add("$phase`: $message")
}

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

    # Keep this a real graceful product close so MainForm.FormClosing must run and
    # persist learner state. Do not infer failure from Wait-Process exceptions:
    # the UI command can close WordDeck before PowerShell resolves the PID, and a
    # missing PID is the successful state we are waiting for, not an error.
    $closingPid = [int]$script:appPid
    Send-Keys 'alt+f4' 'Current English word'
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        $remaining = Get-Process -Id $closingPid -ErrorAction SilentlyContinue
        if ($null -eq $remaining) {
            $script:appPid = $null
            return
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)

    Fail "WordDeck process $closingPid remained alive for 15 seconds after Alt+F4."
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

    # Protect any pre-existing developer/runner profile. Never remove its live
    # state tree until a separate recovery copy is proven to exist.
    if ($script:hadOriginalState) {
        Copy-Item -LiteralPath $script:stateRoot -Destination $script:originalStateBackup -Recurse -Force
        if (-not (Test-Path -LiteralPath $script:originalStateBackup -PathType Container)) {
            Fail 'could not create a recovery copy of the pre-existing WordDeck state tree.'
        }
        $script:originalBackupPrepared = $true
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
catch {
    # Do not rethrow yet. Cleanup must always run, and its failures must be reported
    # without erasing the original acceptance failure that triggered cleanup.
    $script:primaryFailure = $_
}

# Stop any process still owned by this acceptance run, but continue attempting
# learner-state restoration even if process cleanup itself fails.
if ($null -ne $script:appPid -and $script:appPid -gt 0) {
    try {
        Stop-Process -Id $script:appPid -Force -ErrorAction SilentlyContinue
        $remaining = Get-Process -Id $script:appPid -ErrorAction SilentlyContinue
        if ($null -ne $remaining) {
            Wait-Process -Id $script:appPid -Timeout 10 -ErrorAction Stop
        }
    }
    catch {
        Record-CleanupFailure 'process cleanup' $_
    }
    $script:appPid = $null
}

# Restore pre-test learner state only when the backup was successfully materialized.
# If a primary failure happened before backup preparation, leave the original live
# state tree untouched. Never delete an existing profile merely because setup failed.
if ($script:hadOriginalState) {
    if ($script:originalBackupPrepared) {
        if (-not (Test-Path -LiteralPath $script:originalStateBackup -PathType Container)) {
            $script:cleanupFailures.Add('learner state restoration: prepared pre-existing state backup is missing; live state tree was left untouched')
        }
        else {
            try {
                if (Test-Path -LiteralPath $script:stateRoot) {
                    Remove-Item -LiteralPath $script:stateRoot -Recurse -Force
                }
            }
            catch {
                Record-CleanupFailure 'remove test learner state before restoration' $_
            }

            try {
                if (Test-Path -LiteralPath $script:stateRoot) {
                    throw 'test learner state still exists; refusing to overlay the pre-test backup'
                }
                Move-Item -LiteralPath $script:originalStateBackup -Destination $script:stateRoot -Force
            }
            catch {
                Record-CleanupFailure 'learner state restoration move' $_
            }

            if (-not (Test-Path -LiteralPath $script:stateRoot -PathType Container)) {
                $script:cleanupFailures.Add('learner state restoration: pre-existing WordDeck state tree is not present after restore attempt')
            }
        }
    }
}
else {
    # This run started with no WordDeck profile, so only test-created state may be
    # present and is always safe to remove.
    try {
        if (Test-Path -LiteralPath $script:stateRoot) {
            Remove-Item -LiteralPath $script:stateRoot -Recurse -Force
        }
    }
    catch {
        Record-CleanupFailure 'remove isolated test learner state' $_
    }

    if (Test-Path -LiteralPath $script:originalStateBackup) {
        try {
            Remove-Item -LiteralPath $script:originalStateBackup -Recurse -Force
        }
        catch {
            Record-CleanupFailure 'unexpected state-backup cleanup' $_
        }
    }
}

# The replacement program tree is disposable and must be cleaned only after
# learner state has been restored or the restoration failure has been recorded.
if (Test-Path -LiteralPath $script:replacementRoot) {
    try {
        Remove-Item -LiteralPath $script:replacementRoot -Recurse -Force
    }
    catch {
        Record-CleanupFailure 'temporary replacement package cleanup' $_
    }
}

if ($null -ne $script:primaryFailure) {
    if ($script:cleanupFailures.Count -ne 0) {
        $primaryMessage = $script:primaryFailure.Exception.Message
        $cleanupMessage = $script:cleanupFailures -join ' | '
        throw "WordDeck package recovery FAIL: primary acceptance failure: $primaryMessage; cleanup/restoration failure(s): $cleanupMessage"
    }
    throw $script:primaryFailure
}

if ($script:cleanupFailures.Count -ne 0) {
    Fail ("cleanup/restoration failure(s): " + ($script:cleanupFailures -join ' | '))
}
